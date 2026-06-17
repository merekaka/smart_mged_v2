"""
统计分析结果 → 规则化回答文本生成器
"""
from typing import Dict, Any, List


def format_answer(analysis_op: str, analysis_result: Dict[str, Any], total: int) -> str:
    """根据分析类型和结果生成规则化回答文本。"""
    if analysis_op == "sort":
        return _format_sort(analysis_result, total)
    elif analysis_op == "proportion":
        return _format_proportion(analysis_result, total)
    elif analysis_op == "distribution":
        return _format_distribution(analysis_result, total)
    elif analysis_op == "trend":
        return _format_trend(analysis_result, total)
    elif analysis_op == "summary":
        return _format_summary(analysis_result, total)
    else:
        return f"统计分析完成，共 {total} 条数据。"


def _format_sort(analysis_result: Dict[str, Any], total: int) -> str:
    field = analysis_result.get("field", "")
    order = analysis_result.get("order", "asc")
    rankings = analysis_result.get("rankings", [])

    order_text = "从高到低" if order == "desc" else "从低到高"
    if not rankings:
        return f"按{field}{order_text}排序，当前结果中没有可用于排序的数据。"

    lines = [f"按{field}{order_text}排序，共 {total} 条数据。"]

    top = rankings[:5]
    items = []
    for r in top:
        title = r.get("title") or f"ID:{r.get('data_id', '?')}"
        val = r.get("value", "")
        items.append(f"{title}（{val}）")

    prefix = "排名前列的是：" if order == "desc" else "排名前列的是："
    lines.append(prefix + "、".join(items))

    if len(rankings) > 5:
        lines.append(f"……以及另外 {len(rankings) - 5} 条数据。")

    return "\n".join(lines)


def _format_proportion(analysis_result: Dict[str, Any], total: int) -> str:
    field = analysis_result.get("field", "")
    proportions = analysis_result.get("proportions", [])
    is_numeric_warning = analysis_result.get("is_numeric_warning", False)
    empty_count = analysis_result.get("empty_count", 0)

    if not proportions:
        return f"对{field}进行占比统计，当前结果中没有可用数据。"

    lines = [f"在共 {total} 条数据中，{field}的占比分布如下："]

    if is_numeric_warning:
        lines.append("【提示】该字段为数值型，饼图展示可能不够直观，建议使用柱状图查看分布。")

    # 展示前 5 类
    top = proportions[:5]
    for p in top:
        lines.append(f"- {p['category']}：{p['count']}条（{p['percentage']}%）")

    if len(proportions) > 5:
        others = proportions[5:]
        other_count = sum(o["count"] for o in others)
        other_pct = sum(o["percentage"] for o in others)
        lines.append(f"- 其他：{other_count}条（{round(other_pct, 2)}%）")

    if empty_count > 0:
        lines.append(f"\n其中未填写{field}的数据有 {empty_count} 条。")

    return "\n".join(lines)


def _format_distribution(analysis_result: Dict[str, Any], total: int) -> str:
    field = analysis_result.get("field", "")
    bins = analysis_result.get("bins", [])
    stats = analysis_result.get("statistics", {})

    if not bins:
        return f"对{field}进行分布统计，当前结果中没有可用数值数据。"

    lines = [f"{field}的分布情况（共 {total} 条）："]

    max_bin = max(bins, key=lambda b: b["count"])
    lines.append(
        f"主要集中在 {max_bin['min']} ~ {max_bin['max']} 区间，"
        f"共 {max_bin['count']} 条（{max_bin['percentage']}%）。"
    )

    if stats:
        min_v = stats.get("min")
        max_v = stats.get("max")
        mean_v = stats.get("mean")
        parts = []
        if min_v is not None:
            parts.append(f"最小值 {min_v}")
        if max_v is not None:
            parts.append(f"最大值 {max_v}")
        if mean_v is not None:
            parts.append(f"平均值 {mean_v}")
        if parts:
            lines.append("整体统计：" + "，".join(parts) + "。")

    return "\n".join(lines)


def _format_trend(analysis_result: Dict[str, Any], total: int) -> str:
    x_field = analysis_result.get("x_field", "")
    y_field = analysis_result.get("y_field", "")
    points = analysis_result.get("points", [])
    count = analysis_result.get("count", 0)

    if not points:
        return f"趋势分析完成，但没有找到有效的数据点。"

    lines = [f"{y_field}随{x_field}变化趋势分析（共 {count} 个有效数据点）："]

    # 简单描述趋势
    if len(points) >= 2:
        first_y = points[0]["y"]
        last_y = points[-1]["y"]
        if last_y > first_y:
            lines.append(f"整体呈上升趋势（从 {first_y} 到 {last_y}）。")
        elif last_y < first_y:
            lines.append(f"整体呈下降趋势（从 {first_y} 到 {last_y}）。")
        else:
            lines.append(f"整体保持平稳（约 {first_y}）。")

    max_point = max(points, key=lambda p: p["y"])
    min_point = min(points, key=lambda p: p["y"])
    lines.append(f"最大值：{max_point['y']}（{max_point.get('title', '')}）")
    lines.append(f"最小值：{min_point['y']}（{min_point.get('title', '')}）")

    return "\n".join(lines)


def _format_summary(analysis_result: Dict[str, Any], total: int) -> str:
    summaries = analysis_result.get("summaries", {})
    if not summaries:
        return "描述统计分析完成，但没有提取到有效数值数据。"

    lines = []
    for field, stats in summaries.items():
        count = stats.get("count", 0)
        if count == 0:
            lines.append(f"{field}：无有效数值数据。")
            continue

        mean = stats.get("mean")
        std = stats.get("std")
        min_v = stats.get("min")
        max_v = stats.get("max")
        median = stats.get("median")

        parts = [f"{field}的统计特征（样本数 {count}）"]
        if mean is not None:
            parts.append(f"平均值 {mean}")
        if median is not None:
            parts.append(f"中位数 {median}")
        if std is not None:
            parts.append(f"标准差 {std}")
        if min_v is not None and max_v is not None:
            parts.append(f"范围 {min_v} ~ {max_v}")

        lines.append("，".join(parts) + "。")

    return "\n".join(lines)
