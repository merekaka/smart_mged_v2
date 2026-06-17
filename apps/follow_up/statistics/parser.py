"""
统计类意图解析器
独立于 apps/intent_engine，专门解析统计分析类查询。

输出结构：
{
    "analysis_op": "sort" | "proportion" | "distribution" | "summary",
    "field": str,              # 主操作字段
    "config": dict,            # 额外配置（如 order, top_k, bins, fields）
    "target_properties": list, # 用户想查看的属性（可选）
    "follow_up_scope": str,    # "current" | "original"
    "explanation": str,
}
"""
import json
import logging
import os
import re
from typing import Optional, Dict, Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _load_properties() -> list:
    """加载有效的属性名列表（从 intent_engine 的资源文件读取）。"""
    filepath = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "intent_engine", "resources", "property_names_dynamic.txt"
    )
    properties = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # 格式: property_name: description
                prop_name = line.split(":")[0].strip()
                if prop_name:
                    properties.append(prop_name)
    except Exception as e:
        logger.warning(f"StatisticalIntentParser: 加载属性文件失败: {e}")
        # fallback
        properties = [
            "tensile_strength", "yield_strength", "elastic_modulus",
            "density", "hardness", "melting_point", "grain_size",
            "material_name", "crystal_structure", "thermal_conductivity",
        ]
    return properties


class StatisticalIntentParser:
    """
    调用 LLM 解析统计类查询意图。
    复用与 intent_engine 相同的 API 配置，但使用独立的 prompt。
    """

    SYSTEM_PROMPT_TEMPLATE = """你是材料科学领域的统计分析助手。请分析用户的统计查询意图，输出标准JSON。

【重要】用户数据集中包含以下属性（冒号前为英文属性名，必须使用此名称）：
{valid_properties}

输出JSON格式:
{{
    "analysis_op": "sort|proportion|distribution|summary|trend",
    "field": "主操作字段的英文属性名",
    "config": {{
        "order": "asc|desc",       // sort 时使用，默认 asc
        "top_k": null,             // sort 时可选，只返回前N条
        "bins": null,              // distribution 时使用，默认自动推断
        "fields": []               // summary 时使用，多个字段的数组
    }},
    "target_properties": [],       // 用户明确想查看的属性（可选）
    "follow_up_scope": "current",  // "current"=基于当前结果, "original"=基于原始结果
    "explanation": "查询说明"
}}

analysis_op 说明:
- sort: 对某属性排序，返回排序表（如"按弹性模量排序"）
- proportion: 统计某属性的占比分布（如"画个元素含量的饼图"）
- distribution: 数值属性的区间分布统计（如"抗拉强度的分布情况"）
- summary: 描述统计，输出均值/标准差/最值/中位数等（如"描述一下密度的统计特征"）
- trend: 分析两个数值属性的趋势关系，返回折线图数据（如"温度对抗拉强度的影响"）

config 说明:
- sort: 必须提供 order（asc=升序/从小到大，desc=降序/从大到小）
- proportion: 不需要额外 config
- distribution: 可提供 bins（分箱数量），不提供则自动推断
- summary: 必须提供 fields（数组），如果用户说"所有数值属性"则设为空数组 []
- trend: 必须提供 x_field（x轴字段，如 temperature），y_field 由 field 指定

【重要】field 必须从上述属性列表中选择英文属性名。
【重要】如果用户查询中包含"在此基础上""进一步""从这些数据"等递进语义，follow_up_scope 设为 "current"；
        如果包含"从最初""从原始结果""重新"等重置语义，设为 "original"。默认 "current"。

示例1输入: "按弹性模量从高到低排序"
示例1输出:
{{
    "analysis_op": "sort",
    "field": "elastic_modulus",
    "config": {{"order": "desc", "top_k": null}},
    "target_properties": [],
    "follow_up_scope": "current",
    "explanation": "按弹性模量降序排列"
}}

示例2输入: "画个饼图看看各材料的元素含量占比"
示例2输出:
{{
    "analysis_op": "proportion",
    "field": "material_name",
    "config": {{}},
    "target_properties": [],
    "follow_up_scope": "current",
    "explanation": "统计各材料元素含量的占比分布"
}}

示例3输入: "抗拉强度主要分布在哪些区间"
示例3输出:
{{
    "analysis_op": "distribution",
    "field": "tensile_strength",
    "config": {{"bins": null}},
    "target_properties": [],
    "follow_up_scope": "current",
    "explanation": "抗拉强度的区间分布统计"
}}

示例4输入: "描述一下密度和硬度的统计特征"
示例4输出:
{{
    "analysis_op": "summary",
    "field": "",
    "config": {{"fields": ["density", "hardness"]}},
    "target_properties": [],
    "follow_up_scope": "current",
    "explanation": "密度和硬度的描述统计"
}}

示例5输入: "温度对抗拉强度的影响趋势"
示例5输出:
{{
    "analysis_op": "trend",
    "field": "tensile_strength",
    "config": {{"x_field": "temperature"}},
    "target_properties": [],
    "follow_up_scope": "current",
    "explanation": "分析温度对抗拉强度的影响趋势"
}}"""

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

        properties = _load_properties()
        prop_str = "\n".join([f"- {p}" for p in properties[:200]])  # 限制 prompt 长度
        self.system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(valid_properties=prop_str)

    def parse(self, user_text: str) -> Optional[Dict[str, Any]]:
        """解析统计类意图，返回结构化字典。"""
        if not user_text or not user_text.strip():
            return None

        logger.info(f"StatisticalIntentParser.parse: query={user_text[:120]!r}")

        try:
            response = self._call_llm(user_text)
            if not response:
                logger.warning("StatisticalIntentParser: LLM response empty")
                return self._fallback_parse(user_text)

            parsed = self._parse_json(response)
            if not parsed:
                return self._fallback_parse(user_text)

            # 校验和规范化
            result = self._normalize(parsed, user_text)
            logger.info(f"StatisticalIntentParser: op={result.get('analysis_op')}, field={result.get('field')}")
            return result

        except Exception as e:
            logger.error(f"StatisticalIntentParser.parse failed: {e}", exc_info=True)
            return self._fallback_parse(user_text)

    def _call_llm(self, query: str) -> Optional[str]:
        if not self.api_key:
            return None

        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"用户查询: {query}"}
            ],
            "temperature": 0.1,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
        }
        if self.model and "qwen3" in self.model.lower():
            payload["enable_thinking"] = False

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return content
        except Exception as e:
            logger.error(f"StatisticalIntentParser._call_llm failed: {e}")
            return None

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

    def _normalize(self, parsed: dict, original_query: str) -> dict:
        """规范化解析结果，确保字段存在且合法。"""
        op = parsed.get("analysis_op", "sort")
        if op not in {"sort", "proportion", "distribution", "summary", "trend"}:
            op = "sort"

        field = parsed.get("field", "")
        config = parsed.get("config") or {}
        if not isinstance(config, dict):
            config = {}

        scope = str(parsed.get("follow_up_scope", "current")).lower()
        if scope not in {"current", "original"}:
            scope = "current"

        return {
            "analysis_op": op,
            "field": field,
            "config": config,
            "target_properties": parsed.get("target_properties") or [],
            "follow_up_scope": scope,
            "explanation": parsed.get("explanation", original_query),
        }

    def _fallback_parse(self, user_text: str) -> dict:
        """LLM 失败时的回退解析：基于关键词推断。"""
        text = user_text.lower()

        if "排序" in text or "排名" in text or "排" in text:
            op = "sort"
            order = "desc" if any(w in text for w in ["从高到低", "从大到小", "降序"]) else "asc"
            return {
                "analysis_op": op,
                "field": "",
                "config": {"order": order},
                "target_properties": [],
                "follow_up_scope": "current",
                "explanation": user_text,
            }

        if "饼图" in text or "占比" in text or "比例" in text:
            return {
                "analysis_op": "proportion",
                "field": "",
                "config": {},
                "target_properties": [],
                "follow_up_scope": "current",
                "explanation": user_text,
            }

        if "分布" in text:
            return {
                "analysis_op": "distribution",
                "field": "",
                "config": {},
                "target_properties": [],
                "follow_up_scope": "current",
                "explanation": user_text,
            }

        if "趋势" in text or "影响" in text or "关系" in text:
            return {
                "analysis_op": "trend",
                "field": "",
                "config": {"x_field": ""},
                "target_properties": [],
                "follow_up_scope": "current",
                "explanation": user_text,
            }

        return {
            "analysis_op": "summary",
            "field": "",
            "config": {"fields": []},
            "target_properties": [],
            "follow_up_scope": "current",
            "explanation": user_text,
        }
