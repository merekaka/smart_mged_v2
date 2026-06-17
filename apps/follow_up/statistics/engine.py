"""
统计分析引擎主入口
接收统计意图 + 宽表数据，分发到对应操作，并组装最终结果。
"""
import logging
from typing import List, Dict, Any

from apps.follow_up.statistics.ops import (
    sort_records,
    proportion_records,
    distribution_records,
    trend_records,
    summary_records,
)
from apps.follow_up.statistics.formatter import format_answer
from apps.follow_up.statistics.charts import build_chart_data

logger = logging.getLogger(__name__)


class StatisticalEngine:
    """
    统计分析引擎。

    使用方式:
        engine = StatisticalEngine()
        result = engine.analyze(stat_intent, wide_records)
    """

    def analyze(
        self,
        stat_intent: Dict[str, Any],
        wide_records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        执行统计分析。

        :param stat_intent: 统计意图字典（由 StatisticalIntentParser 输出）
        :param wide_records: 宽表记录列表
        :return: 包含 answer / analysis_result / chart_data / results / total 的字典
        """
        op = stat_intent.get("analysis_op", "sort")
        field = stat_intent.get("field", "")
        config = stat_intent.get("config") or {}

        logger.info(f"StatisticalEngine.analyze: op={op}, field={field}, records={len(wide_records)}")

        try:
            analysis_result = self._execute_operation(op, field, config, wide_records)
            chart_data = build_chart_data(op, analysis_result, field)
            answer = format_answer(op, analysis_result, len(wide_records))

            return {
                "answer": answer,
                "analysis_result": analysis_result,
                "chart_data": chart_data,
                "results": wide_records,
                "total": len(wide_records),
                "intent": stat_intent,
            }

        except Exception as e:
            logger.error(f"StatisticalEngine.analyze failed: {e}", exc_info=True)
            return {
                "error": f"统计分析执行失败: {str(e)}",
                "answer": f"统计分析出错：{str(e)}",
                "analysis_result": {},
                "chart_data": {},
                "results": wide_records,
                "total": len(wide_records),
                "intent": stat_intent,
            }

    def _execute_operation(
        self,
        op: str,
        field: str,
        config: Dict[str, Any],
        wide_records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """按 operation 类型分发执行。"""
        if op == "sort":
            order = config.get("order", "asc")
            top_k = config.get("top_k")
            return sort_records(wide_records, field, order=order, top_k=top_k)

        elif op == "proportion":
            return proportion_records(wide_records, field)

        elif op == "distribution":
            bins = config.get("bins")
            return distribution_records(wide_records, field, bins=bins)

        elif op == "trend":
            x_field = config.get("x_field", "")
            y_field = field or config.get("y_field", "")
            top_k = config.get("top_k")
            return trend_records(wide_records, x_field=x_field, y_field=y_field, top_k=top_k)

        elif op == "summary":
            fields = config.get("fields")
            if fields is None:
                fields = [field] if field else []
            return summary_records(wide_records, fields)

        else:
            logger.warning(f"StatisticalEngine: unknown op={op}, fallback to sort")
            return sort_records(wide_records, field, order="asc")
