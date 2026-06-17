#!/usr/bin/env python
"""
数据库结构探查脚本
连接 MySQL，读取 entity_table / value_table / property_table 的结构和样本数据，
用于分析根据 data_id 查询关联数据的最佳方案。

用法:
    .venv\Scripts\python.exe tools/inspect_db.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql
from pymysql.cursors import DictCursor

from utils.db_conf import get_mysql_conf


def get_db_conf():
    """从统一入口获取数据库配置（兼容旧接口，供工具脚本使用）。"""
    conf = get_mysql_conf()
    # 工具脚本需要 DictCursor，确保包含
    conf["cursorclass"] = DictCursor
    return conf


def inspect_table(conn, table_name: str, sample_limit: int = 5):
    """获取表结构和样本数据。"""
    print(f"\n{'='*70}")
    print(f"表名: {table_name}")
    print(f"{'='*70}")

    # 1. 表结构
    with conn.cursor() as cursor:
        cursor.execute(f"DESCRIBE smart_mged.{table_name}")
        schema = cursor.fetchall()

    print(f"\n[字段结构] ({len(schema)} 个字段)")
    print(f"{'字段名':<30} {'类型':<25} {'可空':<8} {'键':<10} {'默认值'}")
    print("-" * 90)
    for col in schema:
        # DESCRIBE 返回: Field, Type, Null, Key, Default, Extra
        print(f"{col['Field']:<30} {col['Type']:<25} {col['Null']:<8} {col['Key']:<10} {col['Default']}")

    # 2. 样本数据
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT * FROM smart_mged.{table_name} LIMIT {sample_limit}")
        rows = cursor.fetchall()

    print(f"\n[样本数据] (前 {sample_limit} 条)")
    if rows:
        headers = list(rows[0].keys())
        print(f"{' | '.join(headers)}")
        print("-" * 90)
        for row in rows:
            vals = [str(row.get(h, 'NULL'))[:40] for h in headers]
            print(f"{' | '.join(vals)}")
    else:
        print("(无数据)")

    # 3. 总行数
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) AS total FROM smart_mged.{table_name}")
        total = cursor.fetchone()["total"]
    print(f"\n[总行数] {total}")

    return schema, rows


def inspect_relationships(conn):
    """分析 data_id 的关联关系。"""
    print(f"\n{'='*70}")
    print("关联关系分析")
    print(f"{'='*70}")

    # 1. entity_table 中的 title（数据集名称）分布
    print("\n[entity_table.title 分布] (前 20 个数据集)")
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT title, COUNT(*) AS cnt
            FROM smart_mged.entity_table
            GROUP BY title
            ORDER BY cnt DESC
            LIMIT 20
        """)
        for row in cursor.fetchall():
            print(f"  {row['title']:<50} {row['cnt']} 条")

    # 2. property_table 中的属性分布
    print("\n[property_table.property_name 分布] (全部属性)")
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT property_id, property_name
            FROM smart_mged.property_table
            ORDER BY property_id
        """)
        props = cursor.fetchall()
        for row in props:
            print(f"  ID={row['property_id']:<4} {row['property_name']}")

    # 3. 随机找一个 data_id，展示其完整的 value_table 关联数据
    print("\n[随机实体完整关联数据示例]")
    with conn.cursor() as cursor:
        cursor.execute("SELECT data_id, title FROM smart_mged.entity_table LIMIT 1")
        entity = cursor.fetchone()

    if entity:
        data_id = entity["data_id"]
        print(f"  data_id={data_id}, title={entity['title']}")
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT v.property_id, p.property_name, v.value
                FROM smart_mged.value_table v
                JOIN smart_mged.property_table p ON v.property_id = p.property_id
                WHERE v.data_id = %s
                ORDER BY v.property_id
            """, (data_id,))
            values = cursor.fetchall()
            for v in values:
                print(f"    {v['property_name']:<30} = {v['value']}")


def main():
    db_conf = get_db_conf()
    print(f"连接数据库: {db_conf['user']}@{db_conf['host']}:{db_conf['port']}/{db_conf['database']}")

    try:
        conn = pymysql.connect(**db_conf)
    except Exception as e:
        print(f"[错误] 数据库连接失败: {e}")
        sys.exit(1)

    try:
        inspect_table(conn, "entity_table", sample_limit=5)
        inspect_table(conn, "value_table", sample_limit=5)
        inspect_table(conn, "property_table", sample_limit=20)
        inspect_relationships(conn)
    finally:
        conn.close()

    print("\n探查完成。")


if __name__ == "__main__":
    main()
