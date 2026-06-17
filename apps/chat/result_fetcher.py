"""
从 MySQL value_table 读取材料事件详情，支持分类格式、宽表格式和长表格式。

MySQL result 来源表：
    value_table (data_id, property_id, property_name, value)
    entity_property_link (data_id, property_id, bitmap_role)
    entity_table (data_id, title)

输出三种格式：
    1. 分类格式（classified）：按 object / operate / result 分组，供前端卡片展示
    2. 宽表格式（wide）：每行一个 data_id，属性为列，供 ResultStore / follow-up 使用
    3. 长表格式（long）：每行一个属性值，供 SQLite 持久化存储
"""

import logging
from typing import List, Dict, Any

import pymysql

from utils.db_conf import get_mysql_conf

logger = logging.getLogger(__name__)


def fetch_result_long(data_ids: List[int]) -> List[Dict[str, Any]]:
    """
    从 MySQL 读取指定 data_id 的长表格式数据。

    返回：
        [
            {"data_id": 1, "title": "钛合金1", "bitmap_role": "result", "property_name": "tensile_strength", "value_text": "500"},
            ...
        ]
    """
    if not data_ids:
        return []
    logger.info(f"fetch_result_long: data_ids_count={len(data_ids)}")

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
        sql = (
            "SELECT vt.data_id, e.title, epl.bitmap_role, vt.property_name, vt.value as value_text "
            "FROM smart_mged.value_table vt "
            "JOIN smart_mged.entity_property_link epl ON vt.data_id = epl.data_id AND vt.property_id = epl.property_id "
            "JOIN smart_mged.entity_table e ON vt.data_id = e.data_id "
            "WHERE vt.data_id IN ({}) "
            "ORDER BY vt.data_id, epl.bitmap_role, vt.property_name"
        ).format(placeholders)

        with conn.cursor() as cursor:
            cursor.execute(sql, ordered_ids)
            rows = cursor.fetchall()

        logger.info(f"fetch_result_long: fetched {len(rows)} rows from MySQL")
        return rows

    except Exception as e:
        logger.error(f"fetch_result_long failed: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def fetch_result_details(data_ids: List[int]) -> List[Dict[str, Any]]:
    """
    从 MySQL 读取指定 data_id 的分类格式数据。

    返回：
        [
            {
                "data_id": 353152,
                "title": "低合金-屈服强度1",
                "object": {"material_name": "Q345D", "C": "0.12 %", ...},
                "operate": {"temperature": "25°C", ...},
                "result": {"lower_yield_strength": "370 MPa"}
            }
        ]
    """
    if not data_ids:
        return []
    logger.info(f"fetch_result_details: data_ids_count={len(data_ids)}")

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
        sql = (
            f"SELECT vt.data_id, e.title, e.data_producers, e.data_organizations, "
            f"       epl.bitmap_role, vt.property_name, vt.value "
            f"FROM smart_mged.value_table vt "
            f"JOIN smart_mged.entity_property_link epl "
            f"    ON vt.data_id = epl.data_id AND vt.property_id = epl.property_id "
            f"JOIN smart_mged.entity_table e ON vt.data_id = e.data_id "
            f"WHERE vt.data_id IN ({placeholders}) "
            f"ORDER BY vt.data_id, epl.bitmap_role, vt.property_name"
        )

        with conn.cursor() as cursor:
            cursor.execute(sql, ordered_ids)
            rows = cursor.fetchall()

        records: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            did = row["data_id"]
            if did not in records:
                records[did] = {
                    "data_id": did,
                    "title": row["title"] or "",
                    "dataset_source": row["title"] or "",
                    "object": {},
                    "operate": {},
                    "result": {},
                }

            role = row["bitmap_role"]
            prop = row["property_name"]
            val = row["value"]

            if role in ("object", "operate", "result") and prop:
                records[did][role][prop] = val

        result = [records[did] for did in ordered_ids if did in records]
        logger.info(f"fetch_result_details: fetched {len(result)} records from MySQL")
        return result

    except Exception as e:
        logger.error(f"fetch_result_details failed: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def to_wide_format(classified_records: List[Dict[str, Any]], use_prefix: bool = False) -> List[Dict[str, Any]]:
    """
    将分类格式转换为宽表格式，供 ResultStore / follow-up 使用。

    :param use_prefix: 是否给列名加前缀（object_ / operate_ / result_）。
                      旧行为默认 True（兼容前端缓存）。
                      新设计中使用 False（属性名不加前缀）。
    """
    wide_records = []
    for rec in classified_records:
        wide: Dict[str, Any] = {
            "data_id": rec["data_id"],
            "title": rec["title"],
        }
        for role in ("object", "operate", "result"):
            for prop, val in rec.get(role, {}).items():
                col_name = f"{role}_{prop}" if use_prefix else prop
                wide[col_name] = val
        wide_records.append(wide)
    return wide_records


def fetch_result_classified_and_wide(
    data_ids: List[int],
    use_prefix: bool = False,
) -> Dict[str, Any]:
    """
    一次性返回分类格式、宽表格式和总数。

    返回：
        {
            "classified": [...],
            "wide": [...],
            "total": int,
        }
    """
    logger.info(f"fetch_result_classified_and_wide: data_ids_count={len(data_ids)}")
    classified = fetch_result_details(data_ids)
    wide = to_wide_format(classified, use_prefix=use_prefix)
    logger.info(f"fetch_result_classified_and_wide: classified={len(classified)}, wide={len(wide)}")
    return {
        "classified": classified,
        "wide": wide,
        "total": len(classified),
    }


def to_classified_format(wide_records: List[Dict[str, Any]], role_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    将宽表记录转换回分类格式（供前端卡片展示）。

    根据列名前缀 object_ / operate_ / result_ 还原分组。
    如果列名无前缀（新设计），优先用 role_map 确定分组，否则默认放入 object。

    :param role_map: property_name → bitmap_role 的映射表（object/operate/result）
    """
    classified = []
    for rec in wide_records:
        obj: Dict[str, Any] = {}
        op: Dict[str, Any] = {}
        res: Dict[str, Any] = {}
        for k, v in rec.items():
            if k in ("data_id", "title"):
                continue
            # 跳过空值，保持与初表展示逻辑一致
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            if k.startswith("object_"):
                obj[k[7:]] = v
            elif k.startswith("operate_"):
                op[k[8:]] = v
            elif k.startswith("result_"):
                res[k[7:]] = v
            else:
                # 无前缀的列：优先用 role_map 确定分组，否则默认 object
                role = role_map.get(k, "object") if role_map else "object"
                if role == "operate":
                    op[k] = v
                elif role == "result":
                    res[k] = v
                else:
                    obj[k] = v
        classified.append({
            "data_id": rec.get("data_id"),
            "title": rec.get("title", ""),
            "object": obj,
            "operate": op,
            "result": res,
        })
    return classified


def wide_to_long(wide_records: List[Dict[str, Any]], role_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    将宽表记录转回长表格式，供 SQLite 持久化存储。

    :param role_map: property_name → bitmap_role 的映射表。
                     若提供，优先用它回填 bitmap_role；
                     否则尝试从列名前辍解析，无前辍时设为空字符串。
    """
    long_rows = []
    for rec in wide_records:
        data_id = rec.get("data_id")
        title = rec.get("title", "")
        for key, val in rec.items():
            if key in ("data_id", "title"):
                continue
            # 跳过空值，保持与初表（MySQL 长表）行为一致
            if val is None or (isinstance(val, str) and not val.strip()):
                continue
            # 先尝试从前缀解析
            bitmap_role = ""
            property_name = key
            if key.startswith("object_"):
                bitmap_role = "object"
                property_name = key[7:]
            elif key.startswith("operate_"):
                bitmap_role = "operate"
                property_name = key[8:]
            elif key.startswith("result_"):
                bitmap_role = "result"
                property_name = key[7:]

            # 用 role_map 回填（覆盖前缀推断结果）
            if role_map and property_name in role_map:
                bitmap_role = role_map[property_name]

            long_rows.append({
                "data_id": data_id,
                "title": title,
                "property_name": property_name,
                "bitmap_role": bitmap_role,
                "value_text": val,
            })
    return long_rows

