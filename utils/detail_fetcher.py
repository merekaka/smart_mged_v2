"""
根据 data_id 列表反查完整材料记录（entity_table 基础信息 + value_table 关联属性值）。
以宽表（扁平字典）形式返回，方便 ResultStore 建内存表和前端展示。
"""

from typing import List, Dict, Any

import pymysql

from utils.db_conf import get_mysql_conf


def fetch_details(data_ids: List[int]) -> List[Dict[str, Any]]:
    """
    根据 data_id 列表查询完整记录。

    返回宽表格式（每个 data_id 一个字典，属性作为键直接展开）：
    [
        {
            "data_id": 274651,
            "title": "3D微观组织数据",
            "data_producers": "...",
            "data_organizations": "...",
            "density": "1210.968",
            "grain_size": "18.8197",
            ...
        }
    ]

    注意：value 全部为字符串（保留原始值），由 ResultStore._infer_type 做类型推断。
    """
    if not data_ids:
        return []

    # 去重并保持原始顺序
    seen = set()
    ordered_ids = []
    for did in data_ids:
        if did not in seen:
            seen.add(did)
            ordered_ids.append(did)

    db_conf = get_mysql_conf()
    conn = pymysql.connect(**db_conf)
    try:
        placeholders = ", ".join(["%s"] * len(ordered_ids))

        # 1) 查询 entity_table（排除 object/operate/result 三个内部位图字段）
        entity_sql = (
            f"SELECT data_id, title, data_producers, data_organizations "
            f"FROM smart_mged.entity_table "
            f"WHERE data_id IN ({placeholders}) "
            f"ORDER BY data_id"
        )
        with conn.cursor() as cursor:
            cursor.execute(entity_sql, ordered_ids)
            entity_rows = cursor.fetchall()

        # 构建结果骨架
        records: Dict[int, Dict[str, Any]] = {}
        for row in entity_rows:
            did = row["data_id"]
            records[did] = {
                "data_id": did,
                "title": row["title"] or "",
                "data_producers": row["data_producers"] or "",
                "data_organizations": row["data_organizations"] or "",
            }

        # 2) 查询 value_table 关联属性值
        value_sql = (
            f"SELECT data_id, property_name, value "
            f"FROM smart_mged.value_table "
            f"WHERE data_id IN ({placeholders}) "
            f"ORDER BY data_id, property_id"
        )
        with conn.cursor() as cursor:
            cursor.execute(value_sql, ordered_ids)
            value_rows = cursor.fetchall()

        for row in value_rows:
            did = row["data_id"]
            if did in records:
                prop = row["property_name"]
                val = row["value"]
                if prop and val is not None:
                    records[did][prop] = val

        # 按原始 data_ids 顺序组装结果
        result = []
        for did in ordered_ids:
            if did in records:
                result.append(records[did])

        return result

    finally:
        conn.close()
