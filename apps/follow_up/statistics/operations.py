"""
统计分析操作集合（纯 Python 实现，无 pandas 依赖）
对宽表记录（List[Dict]）执行各种统计分析。
"""
import logging
import math
import re
from collections import Counter
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def _extract_numeric(value: Any) -> Optional[float]:
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


def _is_numeric(value: Any) -> bool:
    return _extract_numeric(value) is not None


# ---------------------------------------------------------------------------
# 排序
# ---------------------------------------------------------------------------

def sort_records(
    wide_records: List[Dict[str, Any]],
    field: str,
    order: str = "asc",
    top_k: Optional[int] = None,
) -> Dict[str, Any]:
    """
    按字段排序。
    数值型自动提取数字比较，非数值型按字符串比较。
    """
    if not wide_records:
        return {"sorted_records": [], "rankings": [], "field": field, "order": order}

    def sort_key(rec):
        val = rec.get(field)
        num = _extract_numeric(val)
        if num is not None:
            return (0, num)
        return (1, str(val) if val is not None else "")

    reverse = order.lower() == "desc"
    sorted_recs = sorted(wide_records, key=sort_key, reverse=reverse)

    if top_k is not None and top_k > 0:
        sorted_recs = sorted_recs[:top_k]

    rankings = []
    for i, rec in enumerate(sorted_recs, 1):
        rankings.append({
            "rank": i,
            "data_id": rec.get("data_id"),
            "title": rec.get("title", ""),
            "value": rec.get(field),
        })

    return {
        "sorted_records": sorted_recs,
        "rankings": rankings,
        "field": field,
        "order": order,
    }


# ---------------------------------------------------------------------------
# 占比统计
# ---------------------------------------------------------------------------

def proportion_records(
    wide_records: List[Dict[str, Any]],
    field: str,
    min_percentage: float = 2.0,
) -> Dict[str, Any]:
    """
    统计某字段的占比分布。
    适用于饼图/柱状图数据生成。

    当类别过多时，占比低于 min_percentage 的条目会被合并为"其他"，
    避免饼图标签和图例过于繁杂。
    """
    if not wide_records:
        return {"proportions": [], "total_count": 0, "field": field}

    values = []
    for rec in wide_records:
        val = rec.get(field)
        if val is not None and str(val).strip():
            values.append(str(val).strip())
        else:
            values.append("(空值)")

    total = len(values)
    counter = Counter(values)

    proportions = []
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

    # 将小占比合并为"其他"
    if others_count > 0:
        others_percentage = round(others_count / total * 100, 2) if total > 0 else 0.0
        proportions.append({
            "category": "其他",
            "count": others_count,
            "percentage": others_percentage,
        })

    return {
        "proportions": proportions,
        "total_count": total,
        "field": field,
    }


# ---------------------------------------------------------------------------
# 分布统计（直方图）
# ---------------------------------------------------------------------------

def distribution_records(
    wide_records: List[Dict[str, Any]],
    field: str,
    bins: Optional[int] = None,
) -> Dict[str, Any]:
    """
    数值字段的区间分布统计。
    自动推断分箱数量（Sturges' formula）。
    """
    if not wide_records:
        return {"bins": [], "statistics": {}, "field": field}

    nums = []
    for rec in wide_records:
        val = rec.get(field)
        num = _extract_numeric(val)
        if num is not None:
            nums.append(num)

    if not nums:
        return {"bins": [], "statistics": {}, "field": field}

    nums.sort()
    n = len(nums)
    min_val = nums[0]
    max_val = nums[-1]
    mean = sum(nums) / n
    median = nums[n // 2] if n % 2 == 1 else (nums[n // 2 - 1] + nums[n // 2]) / 2

    # 自动分箱
    if bins is None or bins <= 0:
        if n >= 2:
            bins = max(int(1 + 3.322 * math.log10(n)), 3)
        else:
            bins = 3
    bins = min(bins, n)  # 分箱数不超过样本数

    if max_val > min_val:
        bin_width = (max_val - min_val) / bins
    else:
        bin_width = 1.0

    bin_counts = [0] * bins
    for num in nums:
        idx = min(int((num - min_val) / bin_width), bins - 1)
        bin_counts[idx] += 1

    bin_results = []
    for i in range(bins):
        lo = min_val + i * bin_width
        hi = min_val + (i + 1) * bin_width if i < bins - 1 else max_val
        count = bin_counts[i]
        bin_results.append({
            "min": round(lo, 4),
            "max": round(hi, 4),
            "count": count,
            "percentage": round(count / n * 100, 2) if n > 0 else 0.0,
        })

    return {
        "bins": bin_results,
        "statistics": {
            "min": min_val,
            "max": max_val,
            "mean": round(mean, 4),
            "median": round(median, 4),
            "count": n,
        },
        "field": field,
    }


# ---------------------------------------------------------------------------
# 描述统计
# ---------------------------------------------------------------------------

def summary_records(
    wide_records: List[Dict[str, Any]],
    fields: List[str],
) -> Dict[str, Any]:
    """
    对指定字段做描述统计。
    """
    summaries = {}

    target_fields = fields if fields else list(wide_records[0].keys()) if wide_records else []
    # 排除 data_id, title 等非属性列
    target_fields = [f for f in target_fields if f not in ("data_id", "title")]

    for field in target_fields:
        nums = []
        for rec in wide_records:
            val = rec.get(field)
            num = _extract_numeric(val)
            if num is not None:
                nums.append(num)

        if not nums:
            summaries[field] = {
                "count": 0, "mean": None, "std": None,
                "min": None, "max": None, "median": None,
            }
            continue

        nums.sort()
        n = len(nums)
        mean = sum(nums) / n
        median = nums[n // 2] if n % 2 == 1 else (nums[n // 2 - 1] + nums[n // 2]) / 2
        min_val = nums[0]
        max_val = nums[-1]
        variance = sum((x - mean) ** 2 for x in nums) / n if n > 0 else 0
        std = math.sqrt(variance)

        summaries[field] = {
            "count": n,
            "mean": round(mean, 4),
            "std": round(std, 4),
            "min": min_val,
            "max": max_val,
            "median": round(median, 4),
        }

    return {"summaries": summaries}
