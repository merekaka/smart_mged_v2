"""
饼图数据构建器
"""
from typing import Dict, Any


def build_pie_chart(analysis_result: Dict[str, Any], field: str) -> Dict[str, Any]:
    """
    构建饼图 chart_data。

    数据结构：
    {
        "chart_type": "pie",
        "title": "xxx占比分布",
        "data": {
            "labels": ["类别1", "类别2", "未填写"],
            "values": [10, 5, 2],
            "details": [
                {"name": "类别1", "value": 10, "percentage": 55.56},
                ...
            ]
        }
    }
    """
    proportions = analysis_result.get("proportions", [])
    is_numeric_warning = analysis_result.get("is_numeric_warning", False)

    title = f"{field}占比分布"
    if is_numeric_warning:
        title += "（该字段为数值型，饼图展示可能不够直观）"

    return {
        "chart_type": "pie",
        "title": title,
        "data": {
            "labels": [p["category"] for p in proportions],
            "values": [p["count"] for p in proportions],
            "details": [
                {"name": p["category"], "value": p["count"], "percentage": p["percentage"]}
                for p in proportions
            ],
        }
    }
