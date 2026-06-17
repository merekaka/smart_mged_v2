"""
数据库工具函数：封装底层数据库操作细节，供业务层调用。
"""

from typing import List


def reset_sqlite_sequence(db_alias: str, table_names: List[str]):
    """
    重置 SQLite 表的自增序列，使新记录的 id 从 1 开始。

    封装了对 sqlite_sequence 内部表的操作，避免业务代码直接依赖 SQLite 底层细节。

    :param db_alias: Django 数据库别名（如 'cache_sqlite'）
    :param table_names: 需要重置序列的表名列表
    """
    from django.db import connections

    conn = connections[db_alias]
    with conn.cursor() as cursor:
        # 先检查 sqlite_sequence 表是否存在
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence';"
        )
        if not cursor.fetchone():
            return

        # 批量删除指定表的序列记录
        for table_name in table_names:
            cursor.execute(
                "DELETE FROM sqlite_sequence WHERE name = %s",
                [table_name]
            )
