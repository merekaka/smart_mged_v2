"""
折线图：趋势分析操作
分析两个数值型字段之间的关系，用于折线图展示。
"""
import logging
from typing import List, Dict, Any, Optional

from .base import extract_numeric

logger = logging.getLogger(__name__)


def trend_records(
    wide_records: List[Dict[str, Any]],
    x_field: str,
    y_field: str,
    top_k: Optional[int] = None,
) -> Dict[str, Any]:
    """
    分析两个数值型字段的趋势关系（用于折线图）。

    按 x_field 排序，返回 (x, y) 数据点列表。
    如果 x_field 为空，则使用数据索引作为 x 轴。

    :param wide_records: 宽表记录列表
    :param x_field: x轴字段（如 temperature）
    :param y_field: y轴字段（如 tensile_strength）
    :param top_k: 只返回前N条（按y值排序）
    :return: {"points": [{"x": ..., "y": ..., "data_id": ..., "title": ...}], "x_field": ..., "y_field": ...}
    """
    if not wide_records:
        return {"points": [], "x_field": x_field, "y_field": y_field}

    points = []
    for rec in wide_records:
        x_val = rec.get(x_field)
        y_val = rec.get(y_field)

        x_num = extract_numeric(x_val)
        y_num = extract_numeric(y_val)

        if y_num is None:
            continue

        points.append({
            "x": x_num if x_num is not None else len(points),
            "x_raw": x_val,
            "y": y_num,
            "y_raw": y_val,
            "data_id": rec.get("data_id"),
            "title": rec.get("title", ""),
        })

    if not points:
        return {"points": [], "x_field": x_field, "y_field": y_field}

    # 按 x 排序
    points.sort(key=lambda p: p["x"])

    # 如果指定了 top_k，按 y 值取前N
    if top_k is not None and top_k > 0:
        points = sorted(points, key=lambda p: p["y"], reverse=True)[:top_k]
        points.sort(key=lambda p: p["x"])

    return {
        "points": points,
        "x_field": x_field,
        "y_field": y_field,
        "count": len(points),
    }
