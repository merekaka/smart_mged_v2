"""
排序 + 描述统计操作
"""
import logging
import math
from typing import List, Dict, Any, Optional

from .base import extract_numeric

logger = logging.getLogger(__name__)


def sort_records(
    wide_records: List[Dict[str, Any]],
    field: str,
    order: str = "asc",
    top_k: Optional[int] = None,
) -> Dict[str, Any]:
    """按字段排序。数值型自动提取数字比较，非数值型按字符串比较。"""
    if not wide_records:
        return {"sorted_records": [], "rankings": [], "field": field, "order": order}

    def sort_key(rec):
        val = rec.get(field)
        num = extract_numeric(val)
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


def summary_records(
    wide_records: List[Dict[str, Any]],
    fields: List[str],
) -> Dict[str, Any]:
    """对指定字段做描述统计。"""
    summaries = {}

    target_fields = fields if fields else list(wide_records[0].keys()) if wide_records else []
    target_fields = [f for f in target_fields if f not in ("data_id", "title")]

    for field in target_fields:
        nums = []
        for rec in wide_records:
            val = rec.get(field)
            num = extract_numeric(val)
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
