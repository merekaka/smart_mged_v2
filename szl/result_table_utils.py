from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pymysql

from utils.db_conf import get_mysql_conf

logger = logging.getLogger(__name__)


def get_result_table_dir() -> Path:
    return Path(__file__).resolve().parent / "result_table"


def get_result_table_name(conversation_id: int) -> str:
    return f"result{conversation_id}"


def delete_result_table(conversation_id: int) -> bool:
    """删除对话对应的 MySQL result 表（以及本地 JSON 备份，如存在）。"""
    deleted = False
    table_name = get_result_table_name(conversation_id)
    logger.info(f"Deleting result table: {table_name}")
    db_conf = get_mysql_conf()
    conn = pymysql.connect(**db_conf)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS smart_mged.`{table_name}`")
        conn.commit()
        deleted = True
        logger.info(f"Result table {table_name} deleted from MySQL")
    finally:
        conn.close()

    # 兼容旧的 JSON 备份文件
    path = get_result_table_dir() / f"{table_name}.json"
    if path.exists():
        path.unlink()
        deleted = True
        logger.info(f"Result table JSON backup {path} deleted")

    return deleted


def save_result_table_for_conversation(
    conversation_id: int,
    executor_result: Optional[Dict[str, Any]] = None,
    fallback_rows: Optional[List[Dict[str, Any]]] = None,
    structured_query: Optional[Dict[str, Any]] = None,
    original_query: Optional[str] = None,
) -> Path:
    """
    将 executor 的执行结果落盘为 MySQL 表 result{conversation_id}，并同步写入 JSON 备份。

    - 若为 data_id 结果：输出 entity_table + value_table + entity_property_link 的宽结果
    - 若为聚合数值：仅输出 property_name / property_id / result
    """
    logger.info(f"Building result table for conversation_id={conversation_id}")
    table = build_result_table_from_executor_result(
        executor_result,
        fallback_rows=fallback_rows,
        structured_query=structured_query,
        original_query=original_query,
    )
    table["conversation_id"] = conversation_id
    logger.info(f"Result table built: type={table.get('result_type')}, row_count={table.get('row_count', 0)}")

    _write_result_table_to_db(conversation_id, table)

    out_dir = get_result_table_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"result{conversation_id}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=2)
    logger.info(f"Result table JSON saved to {out_path}")
    return out_path


def build_result_table_from_executor_result(
    executor_result: Optional[Dict[str, Any]],
    fallback_rows: Optional[List[Dict[str, Any]]] = None,
    structured_query: Optional[Dict[str, Any]] = None,
    original_query: Optional[str] = None,
) -> Dict[str, Any]:
    logger.info(f"build_result_table_from_executor_result called: has_executor_result={bool(executor_result)}, fallback_rows={len(fallback_rows) if fallback_rows else 0}")
    if not executor_result:
        executor_result = {}

    answer = executor_result.get("answer") or {}
    source_sql_json = executor_result.get("sql_json") or {}
    aggregations = source_sql_json.get("aggregation_sql") or answer.get("aggregations") or []
    structured_query = structured_query or executor_result.get("structured_query") or {}

    sql_json: Dict[str, Any] = {
        "query_mode": executor_result.get("query_mode") or structured_query.get("query_mode"),
        "sql": executor_result.get("sql"),
        "sql_params": executor_result.get("sql_params", []),
        "sql_rendered": executor_result.get("sql_rendered"),
        "final_sql": executor_result.get("final_sql"),
        "final_sql_params": executor_result.get("final_sql_params", []),
        "final_sql_rendered": executor_result.get("final_sql_rendered"),
        "group_sql": executor_result.get("group_sql", []),
        "aggregation_sql": aggregations,
        "structured_query": structured_query,
    }

    agg_funcs = {str(a.get("agg_func") or "").lower() for a in aggregations}
    matched_data_ids = []
    for value in answer.get("matched_data_ids", []) or []:
        try:
            matched_data_ids.append(int(value))
        except Exception:
            continue

    if not matched_data_ids and fallback_rows and not aggregations:
        for row in fallback_rows:
            did = row.get("data_id") if isinstance(row, dict) else None
            try:
                if did is not None:
                    matched_data_ids.append(int(did))
            except Exception:
                continue

    # 只要存在聚合结果，就优先按标量表输出；不要被 fallback_rows 覆盖成宽表。
    if aggregations:
        rows: List[Dict[str, Any]] = []
        for agg in aggregations:
            rows.append(
                {
                    "property_name": agg.get("field") or "",
                    "property_id": _get_property_id(agg.get("field")),
                    "result": agg.get("agg_value"),
                }
            )
        return {
            "result_type": "scalar",
            "columns": ["property_name", "property_id", "result"],
            "row_count": len(rows),
            "rows": rows,
            "structured_query": structured_query,
            "sql_json": sql_json,
        }

    if not aggregations and fallback_rows:
        # 缓存命中时，如果已经有标量结果（例如聚合查询返回的 rows），直接落盘
        sample = fallback_rows[0] if fallback_rows else {}
        if isinstance(sample, dict) and set(sample.keys()).issubset({"property_name", "property_id", "result"}):
            rows = [
                {
                    "property_name": row.get("property_name", ""),
                    "property_id": row.get("property_id"),
                    "result": row.get("result"),
                }
                for row in fallback_rows
            ]
            return {
                "result_type": "scalar",
                "columns": ["property_name", "property_id", "result"],
                "row_count": len(rows),
                "rows": rows,
                "structured_query": structured_query,
                "sql_json": sql_json,
            }

    if not matched_data_ids:
        return {
            "result_type": "table",
            "columns": [
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
            ],
            "row_count": 0,
            "rows": [],
            "structured_query": structured_query,
            "sql_json": sql_json,
        }

    db_conf = get_mysql_conf()
    conn = pymysql.connect(**db_conf)
    try:
        placeholders = ", ".join(["%s"] * len(matched_data_ids))
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
            cursor.execute(sql, matched_data_ids)
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

        return {
            "result_type": "table",
            "columns": [
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
            ],
            "source_data_ids": matched_data_ids,
            "row_count": len(table_rows),
            "rows": table_rows,
            "structured_query": structured_query,
            "sql_json": sql_json,
        }
    finally:
        conn.close()


def _get_property_id(field: Any) -> Optional[int]:
    if not field:
        return None

    db_conf = get_mysql_conf()
    conn = pymysql.connect(**db_conf)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT property_id FROM smart_mged.property_table WHERE property_name = %s",
                (str(field),),
            )
            row = cursor.fetchone()
        return int(row["property_id"]) if row else None
    finally:
        conn.close()


def _write_result_table_to_db(conversation_id: int, table: Dict[str, Any]) -> None:
    """把 result 表写入 MySQL，表名为 result{conversation_id}。"""
    table_name = get_result_table_name(conversation_id)
    logger.info(f"Writing result table to MySQL: {table_name}, rows={table.get('row_count', 0)}")
    db_conf = get_mysql_conf()
    conn = pymysql.connect(**db_conf)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS smart_mged.`{table_name}`")

            result_type = str(table.get("result_type") or "table").lower()
            if result_type == "scalar":
                cursor.execute(
                    f"""
                    CREATE TABLE smart_mged.`{table_name}` (
                        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        property_name VARCHAR(255) NOT NULL DEFAULT '',
                        property_id BIGINT UNSIGNED NULL,
                        result TEXT NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                rows = table.get("rows", []) or []
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
                rows = table.get("rows", []) or []
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

        conn.commit()
    finally:
        conn.close()