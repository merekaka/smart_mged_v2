"""
统计分析基础工具函数
"""
import re
from typing import Any, Optional


def extract_numeric(value: Any) -> Optional[float]:
    """
    从字符串中提取数值。
    支持 "500 MPa" → 500.0, "12.5%" → 12.5
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    # 尝试直接转 float
    try:
        return float(text)
    except ValueError:
        pass

    # 提取第一个数字（支持负数、小数）
    match = re.search(r'[-+]?\d*\.?\d+', text)
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass

    return None


def is_numeric(value: Any) -> bool:
    """判断值是否可以解析为数值。"""
    return extract_numeric(value) is not None


def is_numeric_field(wide_records: list, field: str, threshold: float = 0.7) -> bool:
    """
    判断一个字段是否为数值型字段。
    如果该字段可解析为数值的记录比例 >= threshold，则认为是数值型。
    """
    if not wide_records:
        return False

    values = [r.get(field) for r in wide_records if r.get(field) is not None]
    if not values:
        return False

    numeric_count = sum(1 for v in values if is_numeric(v))
    return numeric_count / len(values) >= threshold
