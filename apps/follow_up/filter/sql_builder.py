"""
Intent-to-SQL 转换器
将 Intent.to_dict() 输出的结构化条件转换为可在 ResultStore 上执行的 SQL。
"""
import logging
from typing import List, Dict, Tuple, Optional, Any

logger = logging.getLogger(__name__)


class IntentSQLBuilder:
    """
    支持两种查询模式：
    1. 条件过滤（agg_func 为空）
    2. 聚合查询（agg_func 非空）

    聚合查询策略：
    - max / min：返回使聚合成立的完整记录（策略 B）
    - avg / sum / count / variance：返回聚合值本身

    列名解析：
    - 支持宽表中带前缀的列名（object_xxx / operate_xxx / result_xxx）
    - 当意图中的 field 与 ResultStore 表列名不完全匹配时自动解析

    多组逻辑组合：
    - 支持 group_logic_op: and / or / not
    - and：各 group 条件取交集
    - or：各 group 条件取并集
    - not：第一个 group 为主集，排除后续 group（差集语义）
    """

    OP_MAP = {
        "=": "=",
        ">": ">",
        "<": "<",
        ">=": ">=",
        "<=": "<=",
        "!=": "!=",
        "neq": "!=",
        "contains": "LIKE",
        "between": "BETWEEN",
    }

    AGG_MAP = {
        "max": "MAX",
        "min": "MIN",
        "max_n": "MAX",   # 逻辑名，实际用 ORDER BY DESC + LIMIT
        "min_n": "MIN",   # 逻辑名，实际用 ORDER BY ASC + LIMIT
        "avg": "AVG",
        "variance": None,  # SQLite 无原生 VARIANCE，用公式计算
        "sum": "SUM",
        "count": "COUNT",
    }

    def __init__(self, intent_dict: dict, table_name: str = "round_results", columns: Optional[List[str]] = None):
        self.intent = intent_dict
        self.table = table_name
        self.columns = columns or []

    def build(self) -> Tuple[str, tuple]:
        """
        返回 (sql: str, params: tuple)
        """
        groups = self.intent.get("groups", [])
        group_logic_op = self.intent.get("group_logic_op", "and").lower()

        if not groups:
            logger.info("IntentSQLBuilder.build: no groups, returning SELECT *")
            sql, params = self._assemble_sql("", ())
            sql = self._append_limit(sql)
            return sql, params

        # 收集所有条件，判断是否存在聚合查询
        all_conditions = []
        for g in groups:
            all_conditions.extend(g.get("conditions", []))

        agg_conds = [c for c in all_conditions if c.get("agg_func")]

        if agg_conds:
            # 聚合查询：目前只处理第一个 group（多组聚合语义较复杂，暂简化）
            group = groups[0]
            conditions = group.get("conditions", [])
            logic_op = group.get("logic_op", "and")

            # 分离聚合条件和普通条件
            group_agg_conds = [c for c in conditions if c.get("agg_func")]
            group_normal_conds = [c for c in conditions if not c.get("agg_func")]

            normal_where, normal_params = self._build_where_clause(group_normal_conds, logic_op)
            sql, params = self._build_aggregate_sql(group_agg_conds, normal_where, normal_params)
            # 注意：_build_aggregate_sql 中 max_n/min_n 的场景已自带 LIMIT
            # 其他聚合（avg/sum/count/variance）返回标量值，不需要 LIMIT
            agg_func_lower = agg_conds[0].get("agg_func", "").lower()
            if agg_func_lower not in ("max_n", "min_n", "avg", "sum", "count", "variance"):
                sql = self._append_limit(sql)
            logger.info(f"IntentSQLBuilder.build: aggregate SQL built, length={len(sql)}")
            return sql, params
        else:
            # 普通查询：支持多组逻辑组合
            sql, params = self._build_multi_group_sql(groups, group_logic_op)
            sql = self._append_limit(sql)
            logger.info(f"IntentSQLBuilder.build: filter SQL built, length={len(sql)}")
            return sql, params

    def _resolve_field(self, field: str) -> str:
        """
        解析意图中的 field 到 ResultStore 表的实际列名。
        优先匹配无前缀列名，其次按 result_ / operate_ / object_ 顺序尝试前缀。
        （result_ 优先：用户查询的多为结果/性能属性，如 tensile_strength）
        """
        if field in self.columns:
            return field
        for prefix in ("result_", "operate_", "object_"):
            prefixed = prefix + field
            if prefixed in self.columns:
                return prefixed
        return field

    def _build_select_clause(self) -> str:
        """根据 target_properties 构建 SELECT 子句，空则 SELECT *。"""
        target = self.intent.get("target_properties", [])
        if not target:
            return "SELECT *"
        resolved = [self._resolve_field(f) for f in target]
        cols = ", ".join(f'"{c}"' for c in resolved)
        return f"SELECT {cols}"

    def _assemble_sql(self, where_str: str, params: tuple) -> Tuple[str, tuple]:
        """组装最终 SQL（不含 ORDER BY）。"""
        select = self._build_select_clause()
        sql = f"{select} FROM {self.table}"
        if where_str:
            sql += f" WHERE {where_str}"
        return sql, params

    def _append_limit(self, sql: str) -> str:
        """追加 LIMIT 子句（如果 intent 中有 limit）。"""
        limit = self.intent.get("limit")
        if limit is not None:
            try:
                limit_val = int(limit)
                if limit_val > 0:
                    sql += f" LIMIT {limit_val}"
            except (ValueError, TypeError):
                pass
        return sql

    def _build_multi_group_sql(self, groups: List[dict], group_logic_op: str) -> Tuple[str, tuple]:
        """
        构建多组普通条件的 WHERE 子句。
        每组的条件先按组内 logic_op 组合，再按 group_logic_op 组合。
        """
        group_wheres: List[str] = []
        all_params: List[Any] = []

        for group in groups:
            conditions = group.get("conditions", [])
            logic_op = group.get("logic_op", "and")
            where_str, params = self._build_where_clause(conditions, logic_op)
            if where_str:
                group_wheres.append(f"({where_str})")
                all_params.extend(params)
            else:
                # 空组视为恒真
                group_wheres.append("1=1")

        if not group_wheres:
            return self._assemble_sql("", ())

        if len(group_wheres) == 1:
            final_where = group_wheres[0]
        else:
            if group_logic_op == "or":
                final_where = f"({' OR '.join(group_wheres)})"
            elif group_logic_op == "not":
                # 差集语义：g1 AND NOT g2 AND NOT g3 ...
                parts = [group_wheres[0]]
                for w in group_wheres[1:]:
                    parts.append(f"NOT ({w})")
                final_where = f"({' AND '.join(parts)})"
            else:  # and
                final_where = f"({' AND '.join(group_wheres)})"

        return self._assemble_sql(final_where, tuple(all_params))

    def _build_where_clause(self, conditions: List[dict], logic_op: str) -> Tuple[str, tuple]:
        """构建 WHERE 子句，返回 (where_string, params)。

        支持范围字符串（如 "525~575"）：
        - >, >=  : 取范围上限进行比较
        - <, <=  : 取范围下限进行比较
        - =      : 判断值是否在 [min, max] 范围内
        - !=     : 判断值是否在 [min, max] 范围外
        """
        if not conditions:
            return "", ()

        parts = []
        params = []
        for c in conditions:
            field = self._resolve_field(c.get("field", ""))
            op_raw = c.get("operator", "=")
            op = self.OP_MAP.get(op_raw, "=")
            value = c.get("value")

            if op_raw == "contains":
                parts.append(f'"{field}" {op} ?')
                params.append(f"%{value}%")
            elif op_raw in ("between", "range"):
                lo, hi = self._parse_between_bounds(value)
                parts.append(f'"{field}" BETWEEN ? AND ?')
                params.extend([lo, hi])
            elif op_raw in (">", ">="):
                # 取范围上限：x~y 取 y，纯数字取本身
                expr = (
                    f'CAST(CASE WHEN INSTR("{field}", \'~\') > 0 '
                    f'THEN SUBSTR("{field}", INSTR("{field}", \'~\') + 1) '
                    f'ELSE "{field}" END AS REAL)'
                )
                parts.append(f'{expr} {op} ?')
                params.append(value)
            elif op_raw in ("<", "<="):
                # 取范围下限：x~y 取 x，纯数字取本身
                expr = (
                    f'CAST(CASE WHEN INSTR("{field}", \'~\') > 0 '
                    f'THEN SUBSTR("{field}", 1, INSTR("{field}", \'~\') - 1) '
                    f'ELSE "{field}" END AS REAL)'
                )
                parts.append(f'{expr} {op} ?')
                params.append(value)
            elif op_raw == "=":
                # 判断值是否为纯数字（整数或浮点数）
                is_numeric = False
                try:
                    float(str(value))
                    is_numeric = True
                except (ValueError, TypeError):
                    pass
                
                if is_numeric:
                    # 数值型：支持纯数字匹配或范围匹配
                    expr = (
                        f'('
                        f'CAST("{field}" AS REAL) = ? '
                        f'OR ('
                        f'INSTR("{field}", \'~\') > 0 '
                        f'AND ? BETWEEN CAST(SUBSTR("{field}", 1, INSTR("{field}", \'~\') - 1) AS REAL) '
                        f'AND CAST(SUBSTR("{field}", INSTR("{field}", \'~\') + 1) AS REAL)'
                        f')'
                        f')'
                    )
                    parts.append(expr)
                    params.extend([value, value])
                else:
                    # 非数值型（如"余量"）：纯文本等值匹配
                    parts.append(f'"{field}" = ?')
                    params.append(value)
            elif op_raw == "!=":
                # 判断值是否为纯数字
                is_numeric = False
                try:
                    float(str(value))
                    is_numeric = True
                except (ValueError, TypeError):
                    pass
                
                if is_numeric:
                    # 数值型：支持纯数字不等或范围外
                    expr = (
                        f'('
                        f'CAST("{field}" AS REAL) != ? '
                        f'AND ('
                        f'INSTR("{field}", \'~\') = 0 '
                        f'OR ? NOT BETWEEN CAST(SUBSTR("{field}", 1, INSTR("{field}", \'~\') - 1) AS REAL) '
                        f'AND CAST(SUBSTR("{field}", INSTR("{field}", \'~\') + 1) AS REAL)'
                        f')'
                        f')'
                    )
                    parts.append(expr)
                    params.extend([value, value])
                else:
                    # 非数值型：纯文本不等匹配
                    parts.append(f'"{field}" != ?')
                    params.append(value)
            else:
                parts.append(f'"{field}" {op} ?')
                params.append(value)

        connector = f" {logic_op.upper()} "
        # 处理 NOT：SQL 中没有 NOT 作为二元连接符，转为 AND NOT
        if logic_op.lower() == "not":
            connector = " AND NOT "

        where_str = connector.join(parts)
        return where_str, tuple(params)

    def _parse_between_bounds(self, value: Any) -> Tuple[Any, Any]:
        """解析 between 的上下界。"""
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return value[0], value[1]
        if isinstance(value, str):
            text = value.strip()
            for sep in [",", "~", "-", "到"]:
                if sep in text:
                    left, right = [x.strip() for x in text.split(sep, 1)]
                    return left, right
        raise ValueError(f"between 条件 value 格式不正确: {value}")

    def _build_filter_sql(self, where_str: str, params: tuple) -> Tuple[str, tuple]:
        """普通过滤查询。"""
        return self._assemble_sql(where_str, params)

    def _build_aggregate_sql(
        self,
        agg_conds: List[dict],
        normal_where: str,
        normal_params: tuple,
    ) -> Tuple[str, tuple]:
        """
        聚合查询。
        当前只处理单聚合条件（多聚合条件场景极少，后续可扩展）。
        """
        if not agg_conds:
            return self._build_filter_sql(normal_where, normal_params)

        agg = agg_conds[0]
        field = self._resolve_field(agg.get("field", ""))
        agg_func = agg.get("agg_func", "").lower()
        sql_agg = self.AGG_MAP.get(agg_func, "MAX")

        # max / min：策略 B，返回使聚合成立的完整记录（单条）
        if agg_func in ("max", "min"):
            if normal_where:
                sql = (
                    f'SELECT * FROM {self.table} '
                    f'WHERE {normal_where} AND "{field}" = ('
                    f'SELECT {sql_agg}("{field}") FROM {self.table} WHERE {normal_where}'
                    f')'
                )
                # WHERE 中参数出现两次（外层 + 子查询）
                return sql, normal_params + normal_params
            else:
                sql = (
                    f'SELECT * FROM {self.table} '
                    f'WHERE "{field}" = (SELECT {sql_agg}("{field}") FROM {self.table})'
                )
                return sql, ()

        # max_n / min_n：ORDER BY + LIMIT 返回前 N 条
        if agg_func in ("max_n", "min_n"):
            limit = self.intent.get("limit")
            limit_val = None
            if limit is not None:
                try:
                    limit_val = int(limit)
                except (ValueError, TypeError):
                    pass
            if not limit_val or limit_val <= 0:
                limit_val = 10  # 兜底默认值

            order_dir = "DESC" if agg_func == "max_n" else "ASC"
            if normal_where:
                sql = (
                    f'SELECT * FROM {self.table} '
                    f'WHERE {normal_where} '
                    f'ORDER BY "{field}" {order_dir} '
                    f'LIMIT {limit_val}'
                )
                return sql, normal_params
            else:
                sql = (
                    f'SELECT * FROM {self.table} '
                    f'ORDER BY "{field}" {order_dir} '
                    f'LIMIT {limit_val}'
                )
                return sql, ()

        # variance：SQLite 无原生支持，用总体方差公式计算
        # VAR = AVG(x²) - AVG(x)²
        if agg_func == "variance":
            agg_expr = f'(AVG("{field}"*"{field}") - AVG("{field}")*AVG("{field}"))'
            alias = f'"{field}_{agg_func}"'
            if normal_where:
                sql = f'SELECT {agg_expr} AS {alias} FROM {self.table} WHERE {normal_where}'
                return sql, normal_params
            else:
                sql = f'SELECT {agg_expr} AS {alias} FROM {self.table}'
                return sql, ()

        # avg / sum / count：返回聚合值本身
        if sql_agg:
            alias = f'"{field}_{agg_func}"'
            if normal_where:
                sql = f'SELECT {sql_agg}("{field}") AS {alias} FROM {self.table} WHERE {normal_where}'
                return sql, normal_params
            else:
                sql = f'SELECT {sql_agg}("{field}") AS {alias} FROM {self.table}'
                return sql, ()

        # 兜底：当成 max 处理
        return self._build_aggregate_sql([{**agg, "agg_func": "max"}], normal_where, normal_params)
