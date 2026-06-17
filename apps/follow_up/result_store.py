"""
结果暂存层：将 JSON 结果列表加载到 SQLite 表，支持 SQL 查询。

支持两种模式：
1. :memory: 模式 —— 内存临时表（适用于单元测试或简单场景）
2. 外部连接模式 —— 使用外部 sqlite3 连接

新增 long_to_wide 静态方法：将 Django ORM 读取的长表数据转置为宽表格式，
供 IntentSQLBuilder 和 ResultStore 使用。
"""
import logging
import sqlite3
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ResultStore:
    """
    将初步结果或某轮 follow-up 结果（JSON 列表）动态映射为 SQLite 表。

    支持 :memory: 或外部 sqlite3 连接。
    列名和类型通过扫描 JSON 数据动态推断。
    """

    def __init__(
        self,
        results: Optional[List[Dict[str, Any]]] = None,
        conn: Optional[sqlite3.Connection] = None,
        table_name: str = "round_results",
    ):
        """
        :param results:  要加载的 JSON 数据；为 None 时表示复用已有表
        :param conn:     外部 sqlite3 连接；为 None 时使用 :memory:
        :param table_name: 表名
        """
        self.table_name = table_name
        self.owns_connection = conn is None

        if self.owns_connection:
            self.conn = sqlite3.connect(":memory:")
            logger.info(f"ResultStore initialized (:memory:): table={table_name}")
        else:
            self.conn = conn
            logger.info(f"ResultStore initialized (external conn): table={table_name}")

        if results is not None and len(results) > 0:
            self._create_table(results)
            self._insert_data(results)
        elif results is not None and len(results) == 0:
            logger.info("ResultStore initialized with empty results")

    def _create_table(self, results: List[Dict[str, Any]]):
        """动态建表：扫描所有 key 推断类型（INTEGER / REAL / TEXT）。"""
        schema: Dict[str, str] = {}
        for row in results:
            for key, value in row.items():
                if key not in schema:
                    schema[key] = self._infer_type(value)

        if not schema:
            return

        cols = [f'"{key}" {dtype}' for key, dtype in schema.items()]
        sql = f"CREATE TABLE IF NOT EXISTS {self.table_name} ({', '.join(cols)})"
        logger.info(f"ResultStore._create_table: table={self.table_name}, columns={len(schema)}")
        self.conn.execute(sql)

    @staticmethod
    def _infer_type(value: Any) -> str:
        if isinstance(value, bool):
            return "INTEGER"
        if isinstance(value, int):
            return "INTEGER"
        if isinstance(value, float):
            return "REAL"
        if isinstance(value, str):
            try:
                int(value)
                return "INTEGER"
            except ValueError:
                try:
                    float(value)
                    return "REAL"
                except ValueError:
                    pass
        return "TEXT"

    def _insert_data(self, results: List[Dict[str, Any]]):
        if not results:
            return

        keys = list(results[0].keys())
        placeholders = ", ".join(["?"] * len(keys))
        col_names = '", "'.join(keys)
        sql = f'INSERT INTO {self.table_name} ("{col_names}") VALUES ({placeholders})'

        for row in results:
            values = [row.get(k) for k in keys]
            self.conn.execute(sql, values)

        self.conn.commit()
        logger.info(f"ResultStore._insert_data: table={self.table_name}, inserted={len(results)}")

    def query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """执行 SQL 并返回字典列表。"""
        # 临时设置 row_factory，避免污染外部共享连接（如 Django 的 cache_sqlite）
        original_row_factory = self.conn.row_factory
        self.conn.row_factory = sqlite3.Row
        try:
            cursor = self.conn.execute(sql, params)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            logger.info(f"ResultStore.query: table={self.table_name}, returned={len(rows)}")
            return [dict(zip(columns, row)) for row in rows]
        finally:
            self.conn.row_factory = original_row_factory

    def close(self):
        if self.owns_connection and self.conn:
            self.conn.close()
            logger.info("ResultStore closed (:memory: connection)")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def long_to_wide(long_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        将长表数据转置为宽表格式。

        长表格式（来自 InitialResult / CurrentResult）：
            [
                {"data_id": 1, "title": "钛合金1", "property_name": "tensile_strength", "value_text": "500"},
                {"data_id": 1, "title": "钛合金1", "property_name": "material_name", "value_text": "Ti-6Al-4V"},
                ...
            ]

        宽表格式（供 ResultStore / IntentSQLBuilder 使用）：
            [
                {"data_id": 1, "title": "钛合金1", "tensile_strength": "500", "material_name": "Ti-6Al-4V"},
                ...
            ]
        """
        if not long_rows:
            return []

        grouped = {}
        for row in long_rows:
            data_id = row.get("data_id")
            if data_id is None:
                continue
            if data_id not in grouped:
                grouped[data_id] = {"data_id": data_id, "title": row.get("title", "")}
            prop = row.get("property_name")
            if prop:
                grouped[data_id][prop] = row.get("value_text")

        return list(grouped.values())
