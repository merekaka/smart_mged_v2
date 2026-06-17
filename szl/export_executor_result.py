from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pymysql


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.db_conf import get_mysql_conf


def _project_root() -> Path:
    return ROOT


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"找不到文件: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _safe_int_list(values: Any) -> List[int]:
    out: List[int] = []
    if not isinstance(values, list):
        return out
    for v in values:
        try:
            out.append(int(v))
        except Exception:
            continue
    return out


def _load_property_map(conn: pymysql.connections.Connection) -> Dict[str, int]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT property_id, property_name FROM smart_mged.property_table")
        rows = cursor.fetchall()
    return {str(r["property_name"]): int(r["property_id"]) for r in rows}


def _get_property_id(property_map: Dict[str, int], field: Any) -> Optional[int]:
    if field is None:
        return None
    return property_map.get(str(field))


def _build_sql_json(exec_result: Dict[str, Any], sidecar_sql: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    sql_json = {
        "query_mode": exec_result.get("query_mode"),
        "sql": exec_result.get("sql"),
        "sql_params": exec_result.get("sql_params", []),
        "sql_rendered": exec_result.get("sql_rendered"),
        "final_sql": exec_result.get("final_sql"),
        "final_sql_params": exec_result.get("final_sql_params", []),
        "final_sql_rendered": exec_result.get("final_sql_rendered"),
        "group_sql": exec_result.get("group_sql", []),
        "aggregation_sql": [],
    }

    if sidecar_sql:
        for key in [
            "query_mode",
            "sql",
            "sql_params",
            "sql_rendered",
            "final_sql",
            "final_sql_params",
            "final_sql_rendered",
            "group_sql",
            "aggregation_sql",
        ]:
            if not sql_json.get(key) and sidecar_sql.get(key) is not None:
                sql_json[key] = sidecar_sql.get(key)

    answer = exec_result.get("answer") or {}
    if answer.get("aggregations"):
        sql_json["aggregation_sql"] = answer.get("aggregations", [])

    return sql_json


def _build_scalar_rows(
    exec_result: Dict[str, Any],
    property_map: Dict[str, int],
) -> List[Dict[str, Any]]:
    answer = exec_result.get("answer") or {}
    aggregations = answer.get("aggregations") or []
    rows: List[Dict[str, Any]] = []
    for agg in aggregations:
        rows.append(
            {
                "property_name": agg.get("field") or "",
                "property_id": _get_property_id(property_map, agg.get("field")),
                "result": agg.get("agg_value"),
            }
        )
    return rows


def _build_wide_rows(
    data_ids: Sequence[int],
    conn: pymysql.connections.Connection,
) -> List[Dict[str, Any]]:
    if not data_ids:
        return []

    placeholders = ", ".join(["%s"] * len(data_ids))
    sql = (
        "SELECT e.data_id, e.title, e.data_producers, e.data_organizations, "
        "v.value_id, v.property_id, v.property_name, l.bitmap_role, v.value AS value "
        "FROM smart_mged.entity_table e "
        "JOIN smart_mged.value_table v ON v.data_id = e.data_id "
        "LEFT JOIN smart_mged.entity_property_link l "
        "  ON l.data_id = v.data_id AND l.property_id = v.property_id "
        f"WHERE e.data_id IN ({placeholders}) "
        "ORDER BY e.data_id, v.property_id, v.value_id"
    )

    with conn.cursor() as cursor:
        cursor.execute(sql, list(data_ids))
        rows = cursor.fetchall()

    table_rows: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        table_rows.append(
            {
                "id": idx,
                "data_id": row.get("data_id"),
                "title": row.get("title") or "",
                "value_id": row.get("value_id"),
                "property_id": row.get("property_id"),
                "property_name": row.get("property_name") or "",
                "bitmap_role": row.get("bitmap_role") or "",
                "value": row.get("value") or "",
                "data_producers": row.get("data_producers") or "",
                "data_organizations": row.get("data_organizations") or "",
            }
        )
    return table_rows


def _write_result_json(output_path: Path, payload: Dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _write_mysql_table(
    conversation_id: int,
    table_type: str,
    rows: List[Dict[str, Any]],
    conn: pymysql.connections.Connection,
) -> None:
    table_name = f"result{conversation_id}"
    with conn.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS smart_mged.`{table_name}`")

        if table_type == "scalar":
            cursor.execute(
                f"""
                CREATE TABLE smart_mged.`{table_name}` (
                    property_name VARCHAR(255) NOT NULL DEFAULT '',
                    property_id BIGINT UNSIGNED NULL,
                    result TEXT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            if rows:
                cursor.executemany(
                    f"INSERT INTO smart_mged.`{table_name}` (property_name, property_id, result) VALUES (%s, %s, %s)",
                    [
                        (
                            row.get("property_name", ""),
                            row.get("property_id"),
                            row.get("result"),
                        )
                        for row in rows
                    ],
                )
        else:
            cursor.execute(
                f"""
                CREATE TABLE smart_mged.`{table_name}` (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    data_id BIGINT UNSIGNED NOT NULL,
                    title VARCHAR(255) NOT NULL DEFAULT '',
                    value_id BIGINT UNSIGNED NULL,
                    property_id BIGINT UNSIGNED NULL,
                    property_name VARCHAR(255) NOT NULL DEFAULT '',
                    bitmap_role VARCHAR(64) NOT NULL DEFAULT '',
                    value TEXT NULL,
                    data_producers VARCHAR(255) NULL,
                    data_organizations VARCHAR(255) NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            if rows:
                cursor.executemany(
                    f"""
                    INSERT INTO smart_mged.`{table_name}`
                    (data_id, title, value_id, property_id, property_name, bitmap_role, value, data_producers, data_organizations)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row.get("data_id"),
                            row.get("title", ""),
                            row.get("value_id"),
                            row.get("property_id"),
                            row.get("property_name", ""),
                            row.get("bitmap_role", ""),
                            row.get("value"),
                            row.get("data_producers"),
                            row.get("data_organizations"),
                        )
                        for row in rows
                    ],
                )


def export_result_table(
    conversation_id: int,
    executor_output_path: Path,
    sql_output_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    exec_result = _load_json(executor_output_path)
    sidecar_sql = _load_json(sql_output_path) if sql_output_path and sql_output_path.exists() else None

    answer = exec_result.get("answer") or {}
    property_map: Dict[str, int] = {}
    db_conf = get_mysql_conf()
    conn = pymysql.connect(**db_conf)
    try:
        property_map = _load_property_map(conn)

        data_ids = _safe_int_list(answer.get("matched_data_ids", []))
        aggregations = answer.get("aggregations") or []

        if data_ids:
            rows = _build_wide_rows(data_ids, conn)
            table_type = "table"
        elif aggregations:
            rows = _build_scalar_rows(exec_result, property_map)
            table_type = "scalar"
        else:
            rows = []
            table_type = "table"

        sql_json = _build_sql_json(exec_result, sidecar_sql=sidecar_sql)
        payload: Dict[str, Any] = {
            "conversation_id": conversation_id,
            "structured_query": exec_result.get("structured_query", {}),
            "sql_json": sql_json,
            "result_type": table_type,
            "rows": rows,
            "row_count": len(rows),
        }

        if table_type == "table":
            payload["columns"] = [
                "id",
                "data_id",
                "title",
                "value_id",
                "property_id",
                "property_name",
                "bitmap_role",
                "value",
                "data_producers",
                "data_organizations",
            ]
        else:
            payload["columns"] = ["property_name", "property_id", "result"]

        if output_dir is None:
            output_dir = _project_root() / "szl" / "result_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"result{conversation_id}.json"
        _write_result_json(json_path, payload)

        _write_mysql_table(conversation_id, table_type, rows, conn)
        conn.commit()
        return json_path
    finally:
        conn.close()


def main() -> None:
    base_dir = _project_root()
    default_executor_output = base_dir / "cache_data" / "query_answers" / "query_answer_latest.json"
    default_sql_output = base_dir / "cache_data" / "sql_json" / "sql_latest.json"
    default_output_dir = base_dir / "szl" / "result_output"

    parser = argparse.ArgumentParser(description="将 intent_sql_executor 的执行结果导出为 resultN 表和 JSON")
    parser.add_argument("--conversation-id", type=int, required=True, help="对话编号，用于命名 resultN")
    parser.add_argument("--executor-output", type=Path, default=default_executor_output, help="intent_sql_executor 的输出 JSON")
    parser.add_argument("--sql-output", type=Path, default=default_sql_output, help="SQL 输出 JSON（可选，用于补全 sql_json）")
    parser.add_argument("--output-dir", type=Path, default=default_output_dir, help="导出 JSON 的目录")
    args = parser.parse_args()

    out_path = export_result_table(
        conversation_id=args.conversation_id,
        executor_output_path=args.executor_output,
        sql_output_path=args.sql_output,
        output_dir=args.output_dir,
    )
    print(f"已导出: {out_path}")


if __name__ == "__main__":
    main()