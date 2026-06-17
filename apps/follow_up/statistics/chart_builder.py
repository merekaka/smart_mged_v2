"""
统计结果 → 前端图表数据格式转换器
生成 ECharts / Chart.js 可直接消费的 JSON 结构。
"""
from typing import Dict, Any


def build_chart_data(analysis_op: str, analysis_result: Dict[str, Any], field: str) -> Dict[str, Any]:
    """
    根据分析结果生成统一的 chart_data 结构。

    chart_type 取值: pie | bar | histogram | table
    """
    if analysis_op == "sort":
        return _build_sort_chart(analysis_result, field)
    elif analysis_op == "proportion":
        return _build_proportion_chart(analysis_result, field)
    elif analysis_op == "distribution":
        return _build_distribution_chart(analysis_result, field)
    elif analysis_op == "summary":
        return _build_summary_chart(analysis_result, field)
    else:
        return {"chart_type": "table", "title": "分析结果", "data": {"columns": [], "rows": []}}


def _build_sort_chart(analysis_result: Dict[str, Any], field: str) -> Dict[str, Any]:
    rankings = analysis_result.get("rankings", [])
    order = analysis_result.get("order", "asc")
    order_text = "降序" if order == "desc" else "升序"

    return {
        "chart_type": "table",
        "title": f"按{field}{order_text}排序",
        "data": {
            "columns": [
                {"field": "rank", "header": "排名"},
                {"field": "title", "header": "材料名称"},
                {"field": "value", "header": field},
            ],
            "rows": rankings,
        }
    }


def _build_proportion_chart(analysis_result: Dict[str, Any], field: str) -> Dict[str, Any]:
    proportions = analysis_result.get("proportions", [])

    return {
        "chart_type": "pie",
        "title": f"{field}占比分布",
        "data": {
            "labels": [p["category"] for p in proportions],
            "values": [p["count"] for p in proportions],
            "details": [
                {"name": p["category"], "value": p["count"], "percentage": p["percentage"]}
                for p in proportions
            ],
        }
    }


def _build_distribution_chart(analysis_result: Dict[str, Any], field: str) -> Dict[str, Any]:
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


def _build_summary_chart(analysis_result: Dict[str, Any], field: str) -> Dict[str, Any]:
    summaries = analysis_result.get("summaries", {})
    # 如果没有指定 field，取 summaries 中的第一个字段
    target_field = field if field and field in summaries else (list(summaries.keys())[0] if summaries else field)
    stats = summaries.get(target_field, {})

    rows = []
    metric_names = {
        "count": "样本数",
        "mean": "均值",
        "std": "标准差",
        "min": "最小值",
        "max": "最大值",
        "median": "中位数",
    }
    for key, label in metric_names.items():
        val = stats.get(key)
        if val is not None:
            rows.append({"metric": label, "value": val})

    return {
        "chart_type": "table",
        "title": f"{target_field}描述统计",
        "data": {
            "columns": [
                {"field": "metric", "header": "统计指标"},
                {"field": "value", "header": "数值"},
            ],
            "rows": rows,
        }
    }
