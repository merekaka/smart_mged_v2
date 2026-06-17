"""
Follow-up 意图分流器（LLM 结构化 JSON 版）

在调用具体 Parser 之前，先通过 LLM 判断用户意图属于：
- "filter"：进一步筛选 / 条件过滤 / 聚合查询（走 filter 子模块）
- "statistics"：统计分析 / 排序 / 画图 / 占比 / 分布（走 statistics 子模块）

LLM 返回结构化 JSON，本地解析后做硬路由，不再使用规则匹配。
"""
import json
import logging
import re
from typing import Dict, Any, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class LLMIntentClassifier:
    """
    基于 LLM 的意图分流器。

    调用 LLM API，要求返回固定格式的 JSON：
    {
        "action_type": "filter" | "statistics",
        "confidence": 0.0~1.0,
        "reasoning": "判断理由（中文）",
        "suggested_sub_type": "sort|proportion|distribution|summary|simple_filter|aggregate_filter|cross_filter"
    }

    当 LLM 调用失败或返回异常时，fallback 到保守策略：返回 "filter"。
    """

    SYSTEM_PROMPT = """你是材料科学领域对话系统的意图分流助手。你的任务只有一个：判断用户的 follow-up 查询属于哪一类意图。

【分类标准】
1. "filter"（筛选）：用户想进一步筛选、查找、过滤数据，或做聚合查询。
   - 包含条件比较：大于、小于、等于、在...之间、包含
   - 包含查询动作：查找、筛选、有哪些、符合条件的
   - 包含聚合查询：最大、最小、平均、总和、计数、方差
   - 示例："密度大于5的有哪些"、"弹性模量最大的材料"、"在此基础上进一步筛选"

2. "statistics"（统计分析）：用户想对已有数据进行统计操作、排序、画图、看分布。
   - 排序类：排序、排名、按...排、从大到小、从小到大
   - 图表类：饼图、柱状图、直方图、画图
   - 占比类：占比、比例、百分比、构成、组成
   - 分布类：分布、区间、集中在哪些范围
   - 描述统计：统计特征、描述一下、均值、中位数、标准差
   - 示例："按弹性模量排序"、"画个元素含量的饼图"、"抗拉强度的分布情况"

【重要区分原则】
- "最大""最小""平均"单独出现时属于 filter（聚合查询）
- "排序看看谁最大""按大小排一下"属于 statistics（排序分析）
- "统计一下..."如果后面跟的是条件筛选（如"统计一下密度大于5的有多少"）→ filter
- "统计一下...的分布/占比/特征" → statistics

【输出格式】
必须严格输出以下 JSON，不要任何额外解释：
{
    "action_type": "filter" 或 "statistics",
    "confidence": 0.0~1.0 的数字,
    "reasoning": "你的判断理由，用中文简要说明",
    "suggested_sub_type": "sort|proportion|distribution|summary|simple_filter|aggregate_filter|unknown"
}

suggested_sub_type 说明：
- sort：用户要求排序
- proportion：用户要求看占比/饼图
- distribution：用户要求看分布/直方图
- summary：用户要求描述统计/统计特征
- trend：用户要求分析趋势关系/折线图
- simple_filter：普通条件筛选
- aggregate_filter：聚合查询（最大/最小/平均等）
- unknown：不确定具体子类型"""

    def __init__(self):
        self.mode = getattr(settings, 'INTENT_MODE', 'local')
        if self.mode == 'cloud':
            self.api_key = getattr(settings, 'INTENT_CLOUD_API_KEY', '')
            self.api_base = getattr(settings, 'INTENT_CLOUD_API_BASE', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
            self.model = getattr(settings, 'INTENT_CLOUD_MODEL', 'qwen3-32b')
        else:
            self.api_key = (
                getattr(settings, 'INTENT_LOCAL_API_KEY', None)
                or getattr(settings, 'DEEPSEEK_API_KEY', 'ollama')
            )
            self.api_base = (
                getattr(settings, 'INTENT_LOCAL_API_BASE', None)
                or getattr(settings, 'DEEPSEEK_API_BASE', 'http://localhost:11434/v1')
            )
            self.model = (
                getattr(settings, 'INTENT_LOCAL_MODEL', None)
                or getattr(settings, 'DEEPSEEK_MODEL', 'qwen3:1.7b')
            )

    def classify(self, user_text: str) -> Dict[str, Any]:
        """
        调用 LLM 进行意图分流。

        返回字典：
        {
            "action_type": "filter" | "statistics",
            "confidence": float,
            "reasoning": str,
            "suggested_sub_type": str,
        }

        如果 LLM 调用失败，返回保守 fallback：{"action_type": "filter", ...}。
        """
        if not self.api_key:
            logger.warning("LLMIntentClassifier: no API key configured, fallback to filter")
            return self._fallback_result(user_text, reason="未配置 API Key")

        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": f"用户查询: {user_text}"}
            ],
            "temperature": 0.0,
            "max_tokens": 256,
            "response_format": {"type": "json_object"},
        }
        if self.model and "qwen3" in self.model.lower():
            payload["enable_thinking"] = False

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            resp.raise_for_status()
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            logger.info(f"LLMIntentClassifier: raw_response={content[:200]!r}")

            parsed = self._parse_json(content)
            if not parsed:
                logger.warning("LLMIntentClassifier: failed to parse JSON response")
                return self._fallback_result(user_text, reason="JSON 解析失败")

            result = self._normalize(parsed, user_text)
            logger.info(
                f"LLMIntentClassifier: action_type={result['action_type']}, "
                f"confidence={result['confidence']}, sub_type={result['suggested_sub_type']}, "
                f"reasoning={result['reasoning'][:60]!r}"
            )
            return result

        except Exception as e:
            logger.error(f"LLMIntentClassifier.classify failed: {e}")
            return self._fallback_result(user_text, reason=f"LLM 调用异常: {str(e)}")

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                match = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned)
                if match:
                    cleaned = match.group(1).strip()
            return json.loads(cleaned)
        except Exception:
            return None

    @staticmethod
    def _normalize(parsed: dict, original_query: str) -> dict:
        """规范化 LLM 输出，确保字段合法。"""
        action_type = str(parsed.get("action_type", "filter")).lower()
        if action_type not in {"filter", "statistics"}:
            action_type = "filter"

        confidence = parsed.get("confidence")
        try:
            confidence = float(confidence)
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.5

        sub_type = str(parsed.get("suggested_sub_type", "unknown")).lower()
        if sub_type not in {"sort", "proportion", "distribution", "summary", "trend",
                            "simple_filter", "aggregate_filter", "unknown"}:
            sub_type = "unknown"

        reasoning = str(parsed.get("reasoning", "")).strip()
        if not reasoning:
            reasoning = f"基于查询内容判断为 {action_type}"

        return {
            "action_type": action_type,
            "confidence": confidence,
            "reasoning": reasoning,
            "suggested_sub_type": sub_type,
            "original_query": original_query,
        }

    @staticmethod
    def _fallback_result(original_query: str, reason: str) -> dict:
        """保守 fallback：默认走 filter。"""
        return {
            "action_type": "filter",
            "confidence": 0.0,
            "reasoning": f"分流器 fallback（{reason}），保守选择 filter",
            "suggested_sub_type": "unknown",
            "original_query": original_query,
        }


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

class FollowUpClassifier:
    """
    Follow-up 意图分流器统一入口。

    当前实现：完全依赖 LLM 做结构化 JSON 分流，不再使用规则匹配。
    如果需要回退到规则匹配，可在此类中扩展。
    """

    def __init__(self):
        self._llm = LLMIntentClassifier()

    def classify(self, user_text: str) -> str:
        """
        判断用户意图是 "filter" 还是 "statistics"。
        只返回 action_type 字符串（filter 或 statistics）。
        """
        result = self._llm.classify(user_text)
        action_type = result.get("action_type", "filter")
        sub_type = result.get("suggested_sub_type", "unknown")

        # 硬规则修正：如果子类型明确是统计类，但 action_type 被错分为 filter，自动纠正
        if action_type == "filter" and sub_type in {"sort", "proportion", "distribution", "summary", "trend"}:
            logger.info(
                f"FollowUpClassifier: hard-rule correction, sub_type={sub_type} implies statistics, "
                f"overriding action_type from filter to statistics"
            )
            action_type = "statistics"

        logger.info(
            f"FollowUpClassifier: text={user_text[:80]!r}, "
            f"action={action_type}, conf={result.get('confidence')}, "
            f"sub={sub_type}"
        )
        return action_type

    def classify_with_meta(self, user_text: str) -> dict:
        """
        返回完整的分流结果（含 confidence、reasoning、sub_type）。
        供需要更细粒度判断的调用方使用。
        """
        return self._llm.classify(user_text)


def classify_follow_up_intent(user_text: str) -> str:
    """便捷函数：返回 action_type 字符串。"""
    classifier = FollowUpClassifier()
    return classifier.classify(user_text)
