"""
饼图：占比统计操作
统计某字段不同值的占比分布，包含空值统计。
"""
import logging
from collections import Counter
from typing import List, Dict, Any

from .base import is_numeric_field

logger = logging.getLogger(__name__)


def proportion_records(
    wide_records: List[Dict[str, Any]],
    field: str,
    min_percentage: float = 2.0,
) -> Dict[str, Any]:
    """
    统计某字段的占比分布（用于饼图）。

    特点：
    - 自动检测数值型字段并给出警告（数值型不适合饼图）
    - 空值（None/空字符串）单独统计为"未填写"
    - 占比低于 min_percentage 的条目合并为"其他"

    :param wide_records: 宽表记录列表
    :param field: 要统计的字段名
    :param min_percentage: 小占比合并阈值（%）
    :return: {"proportions": [...], "total_count": N, "field": field, "is_numeric_warning": bool}
    """
    if not wide_records:
        return {"proportions": [], "total_count": 0, "field": field, "is_numeric_warning": False}

    total = len(wide_records)

    # 检测是否为数值型字段
    is_numeric = is_numeric_field(wide_records, field)
    if is_numeric:
        logger.warning(f"proportion_records: field '{field}' is numeric, pie chart may not be suitable")

    # 分类统计（含空值）
    values = []
    empty_count = 0
    for rec in wide_records:
        val = rec.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            empty_count += 1
        else:
            values.append(str(val).strip())

    counter = Counter(values)
    proportions = []

    # 先处理非空值
    others_count = 0
    for category, count in counter.most_common():
        percentage = round(count / total * 100, 2) if total > 0 else 0.0
        if percentage < min_percentage:
            others_count += count
        else:
            proportions.append({
                "category": category,
                "count": count,
                "percentage": percentage,
            })

    # 合并小占比
    if others_count > 0:
        others_percentage = round(others_count / total * 100, 2) if total > 0 else 0.0
        proportions.append({
            "category": "其他",
            "count": others_count,
            "percentage": others_percentage,
        })

    # 最后插入空值（如果有）
    if empty_count > 0:
        empty_percentage = round(empty_count / total * 100, 2) if total > 0 else 0.0
        proportions.append({
            "category": "未填写",
            "count": empty_count,
            "percentage": empty_percentage,
        })

    return {
        "proportions": proportions,
        "total_count": total,
        "field": field,
        "is_numeric_warning": is_numeric,
        "empty_count": empty_count,
    }
