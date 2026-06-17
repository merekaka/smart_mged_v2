"""
柱状图：数值字段的区间分布统计
"""
import logging
import math
from typing import List, Dict, Any, Optional

from .base import extract_numeric

logger = logging.getLogger(__name__)


def distribution_records(
    wide_records: List[Dict[str, Any]],
    field: str,
    bins: Optional[int] = None,
) -> Dict[str, Any]:
    """
    数值字段的区间分布统计（用于柱状图）。

    自动推断分箱数量（Sturges' formula）。
    """
    if not wide_records:
        return {"bins": [], "statistics": {}, "field": field}

    nums = []
    for rec in wide_records:
        val = rec.get(field)
        num = extract_numeric(val)
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
    bins = min(bins, n)

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
