"""
柱状图数据构建器
"""
from typing import Dict, Any


def build_bar_chart(analysis_result: Dict[str, Any], field: str) -> Dict[str, Any]:
    """
    构建柱状图 chart_data。

    数据结构：
    {
        "chart_type": "bar",
        "title": "xxx分布",
        "data": {
            "categories": ["0~10", "10~20", "20~30"],
            "series": [
                {"name": "数量", "data": [5, 12, 8]}
            ],
            "statistics": {...}
        }
    }
    """
    bins = analysis_result.get("bins", [])
    stats = analysis_result.get("statistics", {})

    return {
        "chart_type": "bar",
        "title": f"{field}分布",
        "data": {
            "categories": [f'{b["min"]} ~ {b["max"]}' for b in bins],
            "series": [
                {"name": "数量", "data": [b["count"] for b in bins]}
            ],
            "statistics": stats,
        }
    }
