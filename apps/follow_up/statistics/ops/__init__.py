"""
统计分析操作集合
提供排序、占比、分布、趋势等数据分析能力。
"""
from .proportion import proportion_records
from .distribution import distribution_records
from .trend import trend_records
from .sort_summary import sort_records, summary_records

__all__ = [
    "proportion_records",
    "distribution_records",
    "trend_records",
    "sort_records",
    "summary_records",
]
