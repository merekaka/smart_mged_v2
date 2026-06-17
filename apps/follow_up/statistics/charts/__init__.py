"""
图表数据构建器
将统计结果转换为前端 ECharts 可消费的 chart_data 结构。
"""
from typing import Dict, Any

from .pie import build_pie_chart
from .bar import build_bar_chart
from .line import build_line_chart
from .table import build_table_chart

__all__ = [
    "build_pie_chart",
    "build_bar_chart",
    "build_line_chart",
    "build_table_chart",
    "build_chart_data",
]


def build_chart_data(analysis_op: str, analysis_result: Dict[str, Any], field: str) -> Dict[str, Any]:
    """
    根据分析结果生成统一的 chart_data 结构。
    """
    if analysis_op == "sort":
        return build_table_chart(analysis_result, field, title_prefix="按", title_suffix="排序")
    elif analysis_op == "proportion":
        return build_pie_chart(analysis_result, field)
    elif analysis_op == "distribution":
        return build_bar_chart(analysis_result, field)
    elif analysis_op == "trend":
        return build_line_chart(analysis_result, field)
    elif analysis_op == "summary":
        return build_table_chart(analysis_result, field, title_prefix="", title_suffix="描述统计")
    else:
        return build_table_chart({}, field, title_prefix="", title_suffix="分析结果")
