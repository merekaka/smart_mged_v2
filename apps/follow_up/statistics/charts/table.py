"""
表格数据构建器
"""
from typing import Dict, Any


def build_table_chart(
    analysis_result: Dict[str, Any],
    field: str,
    title_prefix: str = "",
    title_suffix: str = "",
) -> Dict[str, Any]:
    """
    构建表格 chart_data。

    支持排序结果和描述统计结果。
    """
    # 排序结果
    rankings = analysis_result.get("rankings", [])
    if rankings:
        order = analysis_result.get("order", "asc")
        order_text = "降序" if order == "desc" else "升序"
        return {
            "chart_type": "table",
            "title": f"{title_prefix}{field}{title_suffix}" if title_prefix else f"{field}{title_suffix}",
            "data": {
                "columns": [
                    {"field": "rank", "header": "排名"},
                    {"field": "title", "header": "材料名称"},
                    {"field": "value", "header": field},
                ],
                "rows": rankings,
            }
        }

    # 描述统计结果
    summaries = analysis_result.get("summaries", {})
    if summaries:
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

    # 兜底
    return {
        "chart_type": "table",
        "title": f"{field}分析结果",
        "data": {
            "columns": [],
            "rows": [],
        }
    }
