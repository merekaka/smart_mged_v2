

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pymysql

from utils.db_conf import get_mysql_conf

logger = logging.getLogger(__name__)


FIELD_ALIASES = {
    "material_type": "material_name",
}


def _num_expr(column_sql: str) -> str:
    """兼容旧逻辑的数值表达式（默认精度）。"""
    return f"CAST({column_sql} AS DECIMAL(30,15))"


def _num_not_null_expr(column_sql: str) -> str:
    return f"{column_sql} != '' AND {column_sql} IS NOT NULL"


def _is_numeric_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, Decimal)):
        return True
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return False
        try:
            Decimal(s)
            return True
        except InvalidOperation:
            return False
    return False


def _get_decimal_scale(value: Any) -> int:
    """
    根据 value 决定 DECIMAL 的 scale（小数位数）。
    规则：
    - 默认返回 scale=15
    - precision 固定为 30。
    """
    if not _is_numeric_value(value):
        return 15  # 默认返回 15

    try:
        d = Decimal(str(value)).copy_abs()
    except (InvalidOperation, ValueError):
        return 15

    sign, digits, exponent = d.as_tuple()
    _ = sign
    frac_digits = max(-exponent, 0)
    int_digits = len(digits) - frac_digits
    if int_digits <= 0:
        int_digits = 1
    
    # 统一使用 15 位小数
    return 15


def _decimal_precision_from_value(value: Any, default: Tuple[int, int] = (30, 15)) -> Tuple[int, int]:
    """
    DEPRECATED: 改用 _get_decimal_scale() 方案，返回固定的 (30, scale)。
    precision 固定为 30，scale 固定为 15。
    """
    scale = _get_decimal_scale(value)
    return 30, scale


def _decimal_precision_from_between_value(value: Any, default: Tuple[int, int] = (30, 15)) -> Tuple[int, int]:
    """
    处理 BETWEEN 的上下界，precision 固定 30。
    scale 固定 15。
    """
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return 30, 15
    if isinstance(value, str) and "," in value:
        return 30, 15
    return 30, 15


@dataclass
class SqlBuildResult:
    sql: str
    params: List[Any]


class IntentSqlExecutor:
    def __init__(
        self,
        base_dir: Optional[Path] = None,
        intent_payload: Optional[Dict[str, Any]] = None,
    ):
        self.base_dir = base_dir or Path(__file__).resolve().parents[1]
        self.intent_json_path = self.base_dir / "cache_data" / "intent_json" / "intent_latest.json"
        self.output_path = self.base_dir / "cache_data" / "query_answers" / "query_answer_latest.json"
        self.sql_output_path = self.base_dir / "cache_data" / "sql_json" / "sql_latest.json"

        # 若外部传入 intent_payload，则不再从文件读取
        self._intent_payload = intent_payload

        self.db_conf = get_mysql_conf()
        self.property_id_map: Dict[str, int] = {}
        self.dataset_property_map: Dict[str, set] = {}

    @classmethod
    def from_intent_dict(cls, intent_dict: Dict[str, Any], original_query: str = "", **kwargs) -> "IntentSqlExecutor":
        """
        从 apps.intent_engine 的 Intent.to_dict() 输出构建 executor。

        自动完成格式转换：
          - Intent.conditions1 / datasets1  ->  simple 模式的 conditions + datasets
          - Intent.conditions2 / datasets2  ->  complex 模式的 sub_queries[1]
        """
        # 只接受标准的 `groups` 格式，不再兼容旧的 conditions1/datasets1
        query_mode = str(intent_dict.get("query_mode") or "").lower()
        groups = intent_dict.get("groups") or []

        if query_mode not in {"simple", "complex"}:
            query_mode = "complex" if len(groups) > 1 else "simple"

        payload: Dict[str, Any] = {
            "original_query": original_query or intent_dict.get("explanation", ""),
            "intent": intent_dict,
            "structured_query": {
                "query_mode": query_mode,
                "group_logic_op": str(intent_dict.get("group_logic_op", "and")).lower(),
                "groups": groups,
            },
        }

        return cls(intent_payload=payload, **kwargs)

    def run(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        执行查询。
        若调用方已提供 payload（如通过 from_intent_dict 创建时），则直接使用；
        否则回退到从 JSON 文件读取（兼容旧用法）。
        """
        if payload is None:
            payload = self._intent_payload or self._load_intent_payload()

        structured_query = payload.get("structured_query") or {}
        query_mode = str(structured_query.get("query_mode", "simple")).lower()
        original_query = payload.get("original_query", "")

        logger.info(f"IntentSqlExecutor.run starting: query_mode={query_mode}, original_query={original_query[:100]!r}")

        with pymysql.connect(**self.db_conf) as conn:
            self._load_property_id_map(conn)
            logger.info(f"IntentSqlExecutor: loaded {len(self.property_id_map)} property mappings")
            # 仅 query_mode=complex 时才走跨数据集检索。
            # 其它情况（含 simple/缺省/异常值）统一按单数据集模式处理。
            if query_mode == "complex":
                logger.info("IntentSqlExecutor: executing complex query")
                result = self._execute_complex(conn, payload)
            else:
                logger.info("IntentSqlExecutor: executing simple query")
                result = self._execute_simple(conn, payload)

        matched_total = result.get("answer", {}).get("total", 0)
        logger.info(f"IntentSqlExecutor.run finished: matched_total={matched_total}")
        self._write_output(result)
        self._write_sql_output(result)
        return result

    def _quote_sql_value(self, value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value).replace("\\", "\\\\").replace("'", "''")
        return f"'{text}'"

    def _render_sql(self, sql: str, params: Sequence[Any]) -> str:
        """将参数化 SQL 渲染为可直接阅读/执行的 SQL 字符串。"""
        parts = sql.split("%s")
        if len(parts) == 1:
            return sql

        rendered: List[str] = []
        for idx, part in enumerate(parts[:-1]):
            rendered.append(part)
            if idx < len(params):
                rendered.append(self._quote_sql_value(params[idx]))
            else:
                rendered.append("%s")
        rendered.append(parts[-1])
        return "".join(rendered)

    def _load_intent_payload(self) -> Dict[str, Any]:
        if not self.intent_json_path.exists():
            raise FileNotFoundError(f"找不到输入 JSON: {self.intent_json_path}")

        with self.intent_json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if "structured_query" not in data:
            raise ValueError("intent_latest.json 中缺少 structured_query 字段")

        return data

    def _load_property_id_map(self, conn: pymysql.connections.Connection) -> None:
        """加载 property_name -> property_id 映射。"""
        sql = "SELECT property_id, property_name FROM smart_mged.property_table"
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
        self.property_id_map = {str(r["property_name"]): int(r["property_id"]) for r in rows}

        # 加载 title -> property_id 集合（用于“属性覆盖所有数据集”规则）
        sql2 = (
            "SELECT e.title AS title, l.property_id AS property_id "
            "FROM smart_mged.entity_property_link l "
            "JOIN smart_mged.entity_table e ON e.data_id = l.data_id "
            "GROUP BY e.title, l.property_id"
        )
        with conn.cursor() as cursor:
            cursor.execute(sql2)
            rows2 = cursor.fetchall()

        dataset_map: Dict[str, set] = {}
        for r in rows2:
            dataset_map.setdefault(str(r["title"]), set()).add(int(r["property_id"]))
        self.dataset_property_map = dataset_map

    def _get_property_id(self, field: str) -> Optional[int]:
        return self.property_id_map.get(field)

    def _split_conditions(self, conditions: List[Any]) -> Tuple[str, List[Dict[str, Any]]]:
        if not conditions:
            return "and", []
        if isinstance(conditions[0], str):
            return conditions[0].lower(), [c for c in conditions[1:] if isinstance(c, dict)]
        return "and", [c for c in conditions if isinstance(c, dict)]

    def _normalize_field(self, field: Any) -> str:
        field_str = str(field or "").strip()
        return FIELD_ALIASES.get(field_str, field_str)

    def _get_condition_op(self, c: Dict[str, Any]) -> str:
        op = str(c.get("op") or c.get("operator") or "=").strip().lower()
        if op in {"range", "in_range"}:
            return "between"
        return op

    def _build_simple_data_ids_sql(
        self,
        conditions: List[Any],
        datasets: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> SqlBuildResult:
        logic_op, cond_dicts = self._split_conditions(conditions)
        logic_join = " OR " if logic_op == "or" else " AND "

        normal_conditions = [c for c in cond_dicts if not c.get("agg_func")]
        joins: List[str] = []
        where_clauses: List[str] = []
        params: List[Any] = []

        effective_datasets = datasets if datasets is not None else [
            c.get("value") for c in cond_dicts if c.get("field") == "dataset" and c.get("value")
        ]
        if effective_datasets:
            placeholders = ", ".join(["%s"] * len(effective_datasets))
            where_clauses.append(f"e.title IN ({placeholders})")
            params.extend(effective_datasets)

        cond_blocks: List[str] = []
        for idx, c in enumerate(normal_conditions, start=1):
            field = self._normalize_field(c.get("field"))
            if field == "dataset":
                continue

            property_id = self._get_property_id(field)
            if property_id is None:
                # 严格按 property_table 解析字段，未匹配则跳过
                continue

            op = self._get_condition_op(c)
            value = c.get("value")
            alias = f"v{idx}"
            one_clause, one_params = self._build_single_condition_clause(alias, c, property_id)

            if logic_op == "or":
                cond_blocks.append(
                    f"EXISTS (SELECT 1 FROM smart_mged.value_table {alias} "
                    f"WHERE {alias}.data_id = e.data_id AND {one_clause})"
                )
                params.extend(one_params)
            elif logic_op == "not":
                cond_blocks.append(
                    f"NOT EXISTS (SELECT 1 FROM smart_mged.value_table {alias} "
                    f"WHERE {alias}.data_id = e.data_id AND {one_clause})"
                )
                params.extend(one_params)
            else:
                joins.append(f"JOIN smart_mged.value_table {alias} ON {alias}.data_id = e.data_id")
                cond_blocks.append(one_clause)
                params.extend(one_params)

        sql = "SELECT DISTINCT e.data_id\nFROM smart_mged.entity_table e"
        if joins:
            sql += "\n" + "\n".join(joins)

        final_where = []
        if where_clauses:
            final_where.extend(where_clauses)
        if cond_blocks:
            if len(cond_blocks) == 1:
                final_where.append(cond_blocks[0])
            else:
                final_where.append("(" + logic_join.join(cond_blocks) + ")")

        if final_where:
            sql += "\nWHERE " + "\n    AND ".join(final_where)

        sql += "\nORDER BY e.data_id ASC"

        return SqlBuildResult(sql=sql + ";", params=params)

    def _parse_between_bounds(self, value: Any) -> Tuple[Any, Any]:
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return value[0], value[1]
        if isinstance(value, str):
            text = value.strip()
            for sep in [",", "~", "-", "到"]:
                if sep in text:
                    left, right = [x.strip() for x in text.split(sep, 1)]
                    return left, right
        raise ValueError(f"between 条件 value 格式不正确: {value}")

    def _extract_agg_conditions(self, conditions: List[Any]) -> List[Dict[str, Any]]:
        _, cond_dicts = self._split_conditions(conditions)
        return [c for c in cond_dicts if c.get("agg_func")]

    def _execute_aggregations(
        self,
        conn: pymysql.connections.Connection,
        base_conditions: List[Any],
        agg_conditions: List[Dict[str, Any]],
        datasets: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not agg_conditions:
            return []

        _, cond_dicts = self._split_conditions(base_conditions)
        normal_conditions = [c for c in cond_dicts if not c.get("agg_func")]

        results: List[Dict[str, Any]] = []
        with conn.cursor() as cursor:
            for agg in agg_conditions:
                field = self._normalize_field(agg.get("field"))
                func = str(agg.get("agg_func", "")).lower()
                if func not in {"max", "min", "avg", "variance", "sum", "count"}:
                    continue

                property_id = self._get_property_id(field)
                if property_id is None:
                    continue

                agg_alias = {
                    "max": "max_value",
                    "min": "min_value",
                    "avg": "average_value",
                    "variance": "variance_value",
                    "sum": "sum_value",
                    "count": "count_value",
                }[func]

                stat_params: List[Any] = []
                joins: List[str] = []
                where_parts: List[str] = ["v.property_id = %s"]
                stat_params.append(property_id)

                use_entity_join = bool(datasets)

                if datasets:
                    placeholders = ", ".join(["%s"] * len(datasets))
                    where_parts.insert(0, f"e.title IN ({placeholders})")
                    stat_params = list(datasets) + stat_params
                    use_entity_join = True

                if func != "count":
                    where_parts.append("v.value != ''")
                    where_parts.append("v.value IS NOT NULL")

                join_idx = 0
                for c in normal_conditions:
                    nf = self._normalize_field(c.get("field"))
                    if nf == "dataset":
                        continue
                    npid = self._get_property_id(nf)
                    if npid is None:
                        continue
                    join_idx += 1
                    alias = f"vf{join_idx}"
                    joins.append(f"JOIN smart_mged.value_table {alias} ON {alias}.data_id = e.data_id")
                    sub_clause, sub_params = self._build_single_condition_clause(alias, c, npid)
                    where_parts.append(sub_clause)
                    stat_params.extend(sub_params)

                    use_entity_join = True

                # 聚合字段 CAST 精度按聚合条件 value 调整（若无 value 则回退默认）
                p, s = _decimal_precision_from_value(agg.get("value"))
                cast_expr = f"CAST(v.value AS DECIMAL({p}, {s}))"
                sql_func = "VARIANCE" if func == "variance" else func.upper()
                if func == "count":
                    select_expr = f"COUNT(*) AS {agg_alias}"
                else:
                    select_expr = f"{sql_func}({cast_expr}) AS {agg_alias}"

                from_clause = "FROM smart_mged.value_table v"
                if use_entity_join:
                    from_clause = "FROM smart_mged.entity_table e\nJOIN smart_mged.value_table v ON v.data_id = e.data_id"

                stat_sql = (
                    f"SELECT {select_expr}\n"
                    f"{from_clause}"
                    + ("\n" + "\n".join(joins) if joins else "")
                    + "\nWHERE "
                    + "\n    AND ".join(where_parts)
                    + ";"
                )

                cursor.execute(stat_sql, stat_params)
                row = cursor.fetchone() or {}
                agg_value = row.get(agg_alias)

                matched_ids: List[int] = []
                # max/min: 取最值对应的一条记录；avg: 取所有参与计算的数据
                if agg_value is not None and func in {"max", "min"}:
                    # 为避免等值匹配带来多个或错误的 id，按 CAST 排序取第一条（max => DESC, min => ASC）。
                    if _is_numeric_value(agg_value):
                        p_id, s_id = _decimal_precision_from_value(agg_value)
                        ids_from_clause = "FROM smart_mged.value_table v"
                        ids_where = [
                            "v.property_id = %s",
                            "v.value != ''",
                            "v.value IS NOT NULL",
                        ]
                        ids_params = [property_id]
                        if datasets or normal_conditions:
                            ids_from_clause = "FROM smart_mged.entity_table e\nJOIN smart_mged.value_table v ON v.data_id = e.data_id"
                        if datasets:
                            ids_where.insert(0, "e.title IN (%s)")
                            ids_params = list(datasets) + ids_params
                        for c in normal_conditions:
                            nf = self._normalize_field(c.get("field"))
                            if nf == "dataset":
                                continue
                            npid = self._get_property_id(nf)
                            if npid is None:
                                continue
                            join_idx += 1
                            alias = f"vf{join_idx}"
                            ids_from_clause += f"\nJOIN smart_mged.value_table {alias} ON {alias}.data_id = e.data_id"
                            sub_clause, sub_params = self._build_single_condition_clause(alias, c, npid)
                            ids_where.append(sub_clause)
                            ids_params.extend(sub_params)

                        order_expr = f"CAST(v.value AS DECIMAL({p_id}, {s_id}))"
                        # 为避免 DISTINCT + ORDER BY 导致 MySQL 3065 错误，使用子查询先计算排序字段再取第一条
                        id_field = "e.data_id" if (datasets or normal_conditions) else "v.data_id"
                        inner_select = (
                            f"SELECT {id_field} AS data_id, {order_expr} AS __ord\n"
                            f"{ids_from_clause}\n"
                            + "WHERE "
                            + "\n    AND ".join(ids_where)
                        )
                        ids_sql = (
                            f"SELECT data_id FROM (\n{inner_select}\n"
                            f"    ORDER BY __ord {'DESC' if func == 'max' else 'ASC'}\n"
                            f"    LIMIT 1\n) __t;"
                        )
                    else:
                        ids_from_clause = "FROM smart_mged.value_table v"
                        ids_where = ["v.property_id = %s", "v.value = %s"]
                        ids_params = [property_id, str(agg_value)]
                        if datasets or normal_conditions:
                            ids_from_clause = "FROM smart_mged.entity_table e\nJOIN smart_mged.value_table v ON v.data_id = e.data_id"
                        if datasets:
                            ids_where.insert(0, "e.title IN (%s)")
                            ids_params = list(datasets) + ids_params

                        for c in normal_conditions:
                            nf = self._normalize_field(c.get("field"))
                            if nf == "dataset":
                                continue
                            npid = self._get_property_id(nf)
                            if npid is None:
                                continue
                            join_idx += 1
                            alias = f"vf{join_idx}"
                            ids_from_clause += f"\nJOIN smart_mged.value_table {alias} ON {alias}.data_id = e.data_id"
                            sub_clause, sub_params = self._build_single_condition_clause(alias, c, npid)
                            ids_where.append(sub_clause)
                            ids_params.extend(sub_params)

                        id_field = "e.data_id" if (datasets or normal_conditions) else "v.data_id"
                        inner_select = (
                            f"SELECT {id_field} AS data_id\n"
                            f"{ids_from_clause}\n"
                            + "WHERE "
                            + "\n    AND ".join(ids_where)
                        )
                        ids_sql = (
                            f"SELECT data_id FROM (\n{inner_select}\n"
                            f"    ORDER BY data_id ASC\n"
                            f"    LIMIT 1\n) __t;"
                        )

                    cursor.execute(ids_sql, ids_params)
                    matched_ids = [int(x["data_id"]) for x in cursor.fetchall()]

                elif agg_value is not None and func == "avg":
                    # avg: 返回所有参与平均值计算的数据（具有该属性且值非空）
                    ids_from_clause = "FROM smart_mged.value_table v"
                    ids_where = [
                        "v.property_id = %s",
                        "v.value != ''",
                        "v.value IS NOT NULL",
                    ]
                    ids_params = [property_id]
                    if datasets or normal_conditions:
                        ids_from_clause = "FROM smart_mged.entity_table e\nJOIN smart_mged.value_table v ON v.data_id = e.data_id"
                    if datasets:
                        ids_where.insert(0, "e.title IN (%s)")
                        ids_params = list(datasets) + ids_params

                    for c in normal_conditions:
                        nf = self._normalize_field(c.get("field"))
                        if nf == "dataset":
                            continue
                        npid = self._get_property_id(nf)
                        if npid is None:
                            continue
                        join_idx += 1
                        alias = f"vf{join_idx}"
                        ids_from_clause += f"\nJOIN smart_mged.value_table {alias} ON {alias}.data_id = e.data_id"
                        sub_clause, sub_params = self._build_single_condition_clause(alias, c, npid)
                        ids_where.append(sub_clause)
                        ids_params.extend(sub_params)

                    id_field = "e.data_id" if (datasets or normal_conditions) else "v.data_id"
                    ids_sql = (
                        f"SELECT DISTINCT {id_field} AS data_id\n"
                        f"{ids_from_clause}\n"
                        + "WHERE "
                        + "\n    AND ".join(ids_where)
                        + "\nORDER BY data_id ASC;"
                    )

                    cursor.execute(ids_sql, ids_params)
                    matched_ids = [int(x["data_id"]) for x in cursor.fetchall()]

                results.append(
                    {
                        "field": field,
                        "agg_func": func,
                        "agg_value": float(agg_value) if agg_value is not None else None,
                        # max/min/avg 返回匹配到的 data_id，供前端展示对应数据详情
                        "matched_data_ids": matched_ids,
                        "stat_sql": stat_sql,
                        "stat_sql_params": stat_params,
                        "stat_sql_rendered": self._render_sql(stat_sql, stat_params),
                    }
                )

        return results

    def _build_single_condition_clause(self, alias: str, cond: Dict[str, Any], property_id: int) -> Tuple[str, List[Any]]:
        op = self._get_condition_op(cond)
        value = cond.get("value")
        clause = f"{alias}.property_id = %s"
        params: List[Any] = [property_id]

        if op == "between":
            lo, hi = self._parse_between_bounds(value)
            # 仅当上下界均为数值时使用 CAST，否则使用字符串比较
            if _is_numeric_value(lo) and _is_numeric_value(hi):
                p, s = _decimal_precision_from_between_value((lo, hi))
                clause += (
                    f" AND {alias}.value != '' AND {alias}.value IS NOT NULL"
                    f" AND CAST({alias}.value AS DECIMAL({p}, {s})) BETWEEN %s AND %s"
                )
                params.extend([lo, hi])
            else:
                clause += f" AND {alias}.value BETWEEN %s AND %s"
                params.extend([str(lo), str(hi)])
        elif op in {">", "<", ">=", "<=", "="} and _is_numeric_value(value):
            p, s = _decimal_precision_from_value(value)
            clause += (
                f" AND {alias}.value != '' AND {alias}.value IS NOT NULL"
                f" AND CAST({alias}.value AS DECIMAL({p}, {s})) {op} %s"
            )
            params.append(value)
        elif op in {"!=", "neq"} and _is_numeric_value(value):
            p, s = _decimal_precision_from_value(value)
            clause += (
                f" AND {alias}.value != '' AND {alias}.value IS NOT NULL"
                f" AND CAST({alias}.value AS DECIMAL({p}, {s})) != %s"
            )
            params.append(value)
        elif op == "contains":
            clause += f" AND {alias}.value LIKE %s"
            params.append(f"%{value}%")
        elif op in {"!=", "neq"}:
            clause += f" AND {alias}.value != %s"
            params.append(str(value))
        else:
            clause += f" AND {alias}.value = %s"
            params.append(str(value))

        return clause, params

    def _execute_simple(self, conn: pymysql.connections.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
        structured_query = payload.get("structured_query", {})
        groups = structured_query.get("groups") or (payload.get("intent") or {}).get("groups") or []
        first_group = groups[0] if groups else {}
        conditions = first_group.get("conditions", []) if isinstance(first_group, dict) else []
        datasets = first_group.get("datasets", []) if isinstance(first_group, dict) else []
        limit = ((payload.get("intent") or {}).get("limit") or structured_query.get("limit") or 0)

        agg_conditions = self._extract_agg_conditions(conditions)
        agg_results = self._execute_aggregations(
            conn,
            base_conditions=conditions,
            agg_conditions=agg_conditions,
            datasets=datasets,
        )

        if agg_results:
            primary_agg = agg_results[0]
            sql_result = SqlBuildResult(
                sql=str(primary_agg.get("stat_sql") or ""),
                params=list(primary_agg.get("stat_sql_params") or []),
            )
            # 从聚合结果中提取匹配的 data_ids（如 max/min 查询已找到对应记录）
            data_ids: List[int] = primary_agg.get("matched_data_ids", [])
            total = len(agg_results)
        else:
            sql_result = self._build_simple_data_ids_sql(conditions, datasets=datasets, limit=limit)
            with conn.cursor() as cursor:
                cursor.execute(sql_result.sql, sql_result.params)
                rows = cursor.fetchall()
            data_ids = [int(r["data_id"]) for r in rows]
            total = len(data_ids)

        return {
            "original_query": payload.get("original_query"),
            "query_mode": "simple",
            "structured_query": structured_query,
            "sql": sql_result.sql,
            "sql_params": sql_result.params,
            "sql_rendered": self._render_sql(sql_result.sql, sql_result.params),
            "answer": {
                "matched_data_ids": data_ids,
                "total": total,
                "aggregations": agg_results,
            },
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _run_group_query(
        self,
        conn: pymysql.connections.Connection,
        group_conditions: List[Any],
        datasets: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        sql_result = self._build_simple_data_ids_sql(group_conditions, datasets=datasets, limit=limit)
        with conn.cursor() as cursor:
            cursor.execute(sql_result.sql, sql_result.params)
            rows = cursor.fetchall()

        return {
            "data_ids": [int(r["data_id"]) for r in rows],
            "sql": sql_result.sql,
            "params": sql_result.params,
            "sql_rendered": self._render_sql(sql_result.sql, sql_result.params),
        }

    def _build_complex_final_sql(
        self,
        group_sql_results: List[Dict[str, Any]],
        group_logic: str,
        limit: Optional[int] = None,
    ) -> SqlBuildResult:
        """将多个子查询 SQL 组合成最终跨数据集 SQL（数据库侧执行）。"""
        if not group_sql_results:
            return SqlBuildResult(
                sql="SELECT e0.data_id FROM (SELECT NULL AS data_id) e0 WHERE 1=0",
                params=[],
            )

        logic = (group_logic or "and").lower()
        params: List[Any] = []

        # 包装子查询，避免 ORDER BY/LIMIT 对集合运算的影响
        wrapped = []
        for idx, g in enumerate(group_sql_results):
            alias = f"g{idx + 1}"
            group_sql = str(g["sql"]).strip().rstrip(";")
            wrapped_sql = f"(SELECT DISTINCT x.data_id FROM ({group_sql}) x) {alias}"
            wrapped.append((alias, wrapped_sql, g.get("params", [])))

        if logic == "or":
            union_parts = []
            for _, wrapped_sql, p in wrapped:
                union_parts.append(f"SELECT data_id FROM {wrapped_sql}")
                params.extend(p)
            final_sql = "SELECT DISTINCT data_id FROM (" + " UNION ".join(union_parts) + ") u"

        elif logic == "not":
            # g1 \ (g2 ∪ g3 ∪ ...)
            first_alias, first_sql, first_params = wrapped[0]
            params.extend(first_params)
            if len(wrapped) == 1:
                final_sql = f"SELECT {first_alias}.data_id FROM {first_sql}"
            else:
                rhs_parts = []
                for _, rhs_sql, rhs_params in wrapped[1:]:
                    rhs_parts.append(f"SELECT data_id FROM {rhs_sql}")
                    params.extend(rhs_params)
                rhs_union_sql = "SELECT DISTINCT data_id FROM (" + " UNION ".join(rhs_parts) + ") rhs"
                final_sql = (
                    f"SELECT {first_alias}.data_id FROM {first_sql} "
                    f"LEFT JOIN ({rhs_union_sql}) ru ON ru.data_id = {first_alias}.data_id "
                    f"WHERE ru.data_id IS NULL"
                )

        else:
            # 默认 and：多子查询交集
            first_alias, first_sql, first_params = wrapped[0]
            params.extend(first_params)
            joins = []
            for idx in range(1, len(wrapped)):
                alias, join_sql, join_params = wrapped[idx]
                joins.append(f"INNER JOIN {join_sql} ON {alias}.data_id = {first_alias}.data_id")
                params.extend(join_params)
            final_sql = f"SELECT DISTINCT {first_alias}.data_id FROM {first_sql} " + " ".join(joins)

        final_sql += " ORDER BY data_id"

        return SqlBuildResult(sql=final_sql, params=params)

    def _execute_complex(self, conn: pymysql.connections.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
        structured_query = payload.get("structured_query", {})
        groups = structured_query.get("groups", [])
        sub_queries = groups or structured_query.get("sub_queries", [])
        group_logic = str(structured_query.get("group_logic_op", "and")).lower()
        limit = ((payload.get("intent") or {}).get("limit") or structured_query.get("limit") or 0)

        group_results: List[Dict[str, Any]] = []
        for sq in sub_queries:
            group_conditions = sq.get("conditions", []) if isinstance(sq, dict) else []
            group_datasets = sq.get("datasets", []) if isinstance(sq, dict) else []
            group_results.append(self._run_group_query(conn, group_conditions, datasets=group_datasets, limit=None))

        final_sql_result = self._build_complex_final_sql(group_results, group_logic=group_logic, limit=limit)
        with conn.cursor() as cursor:
            cursor.execute(final_sql_result.sql, final_sql_result.params)
            final_rows = cursor.fetchall()
        final_ids = [int(r["data_id"]) for r in final_rows]

        return {
            "original_query": payload.get("original_query"),
            "query_mode": "complex",
            "structured_query": structured_query,
            "group_sql": [
                {
                    "index": idx + 1,
                    "sql": g["sql"],
                    "sql_params": g["params"],
                    "sql_rendered": g.get("sql_rendered"),
                    "data_ids": g["data_ids"],
                }
                for idx, g in enumerate(group_results)
            ],
            "final_sql": final_sql_result.sql,
            "final_sql_params": final_sql_result.params,
            "final_sql_rendered": self._render_sql(final_sql_result.sql, final_sql_result.params),
            "answer": {
                "matched_data_ids": final_ids,
                "total": len(final_ids),
                "group_logic_op": group_logic,
            },
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _write_output(self, result: Dict[str, Any]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.debug(f"IntentSqlExecutor: result written to {self.output_path}")

    def _write_sql_output(self, result: Dict[str, Any]) -> None:
        """将构建出的 SQL（每次覆盖）输出到 cache_data/sql_json/sql_latest.json。"""
        self.sql_output_path.parent.mkdir(parents=True, exist_ok=True)

        payload: Dict[str, Any] = {
            "original_query": result.get("original_query"),
            "query_mode": result.get("query_mode"),
            "generated_at": result.get("generated_at"),
        }

        if result.get("query_mode") == "complex":
            payload["group_sql"] = result.get("group_sql", [])
            payload["final_sql"] = result.get("final_sql")
            payload["final_sql_params"] = result.get("final_sql_params", [])
            payload["final_sql_rendered"] = result.get("final_sql_rendered")
        else:
            payload["sql"] = result.get("sql")
            payload["sql_params"] = result.get("sql_params", [])
            payload["sql_rendered"] = result.get("sql_rendered")

            aggs = (result.get("answer") or {}).get("aggregations") or []
            if aggs:
                payload["aggregation_sql"] = [
                    {
                        "field": a.get("field"),
                        "agg_func": a.get("agg_func"),
                        "stat_sql": a.get("stat_sql"),
                        "stat_sql_params": a.get("stat_sql_params", []),
                        "stat_sql_rendered": a.get("stat_sql_rendered"),
                    }
                    for a in aggs
                ]

        with self.sql_output_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.debug(f"IntentSqlExecutor: SQL info written to {self.sql_output_path}")


def main() -> None:
    executor = IntentSqlExecutor()
    result = executor.run()
    print("查询完成，结果已写入:", executor.output_path)
    print("命中 data_id 数:", result.get("answer", {}).get("total", 0))


def run_from_intent(intent_dict: Dict[str, Any], original_query: str = "") -> Dict[str, Any]:
    """
    便捷入口：直接接收 apps.intent_engine 的 Intent.to_dict() 输出并执行。
    """
    logger.info(f"run_from_intent called: original_query={original_query[:100]!r}")
    executor = IntentSqlExecutor.from_intent_dict(intent_dict, original_query=original_query)
    return executor.run()


if __name__ == "__main__":
    main()
