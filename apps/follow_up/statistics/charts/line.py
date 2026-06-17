"""
折线图数据构建器
"""
from typing import Dict, Any


def build_line_chart(analysis_result: Dict[str, Any], field: str) -> Dict[str, Any]:
    """
    构建折线图 chart_data。

    数据结构：
    {
        "chart_type": "line",
        "title": "xxx随xxx变化趋势",
        "data": {
            "x_axis": ["10", "20", "30"],
            "series": [
                {"name": "y字段", "data": [100, 200, 150]}
            ],
            "x_field": "temperature",
            "y_field": "tensile_strength"
        }
    }
    """
    points = analysis_result.get("points", [])
    x_field = analysis_result.get("x_field", "")
    y_field = analysis_result.get("y_field", "")

    # 使用原始值作为 x 轴标签，更直观
    x_labels = [str(p.get("x_raw", p["x"])) for p in points]
    y_values = [p["y"] for p in points]

    title = f"{y_field}随{x_field}变化趋势" if x_field else f"{y_field}变化趋势"

    return {
        "chart_type": "line",
        "title": title,
        "data": {
            "x_axis": x_labels,
            "series": [
                {"name": y_field, "data": y_values}
            ],
            "x_field": x_field,
            "y_field": y_field,
        }
    }
