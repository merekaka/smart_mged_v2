"""
core/answer_generator.py
------------------------
DeepSeek-based generative answer helper.
Extracted from the original app.py.
"""
import logging
import json
import re

import requests
from django.conf import settings

from core.data_utils import build_citations, build_context_block

logger = logging.getLogger(__name__)


def _strip_json_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def extract_query_conditions(question: str, temperature: float = 0.0, max_tokens: int = 512) -> list:
    """Call DeepSeek to extract structured conditions from natural language query."""
    api_key = settings.DEEPSEEK_API_KEY
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 配置")

    sys_prompt = (
        "你是条件提取器。请从用户查询中提取可用于数据库筛选的条件。\n"
        "只输出 JSON，不要输出解释。\n"
        "输出格式必须是："
        "{\"conditions\": [{\"field\": \"字段名\", \"operate\": \"运算符\", \"value\": \"值\"}]}\n"
        "operate 仅允许：>, >=, <, <=, =, !=, between, in, like。\n"
        "没有可提取条件时返回 {\"conditions\": []}。"
    )
    user_prompt = f"用户查询：{question}"

    url = f"{settings.DEEPSEEK_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    content = _strip_json_fence(content)

    try:
        parsed = json.loads(content) if content else {"conditions": []}
    except Exception:
        logger.warning("条件提取 JSON 解析失败，返回空条件")
        return []

    conditions = parsed.get("conditions", [])
    if not isinstance(conditions, list):
        return []

    normalized = []
    for item in conditions:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field", "")).strip()
        operate = str(item.get("operate", "")).strip()
        value = item.get("value", "")
        if not field or not operate:
            continue
        normalized.append({
            "field": field,
            "operate": operate,
            "value": str(value).strip(),
        })
    return normalized


def generate_answer(question: str, citations: list, temperature: float = 0.3, max_tokens: int = 512) -> str:
    """Call DeepSeek to produce an in-line-cited answer."""
    api_key = settings.DEEPSEEK_API_KEY
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 配置")

    context_block = build_context_block(citations)
    sys_prompt = (
        "你是一个严谨的技术助理。请结合提供的资料块，\n"
        "直接、简洁地回答用户问题。\n"
        "严格在回答中使用 [n] 的编号来标注引用，n 对应资料块【n】。\n"
        "若资料不足以得出结论，请明确说明不确定，并给出可能的方向。\n"
        "回答语言保持与用户问题一致（若无法判断，使用中文）。"
    )
    user_prompt = (
        f"用户问题: {question}\n\n"
        f"资料块 (按相关性排序):\n{context_block}\n\n"
        "请在不超过 300 字内回答，并在使用到的信息末尾标注 [n] 引用，可出现多个引用。"
    )

    url = f"{settings.DEEPSEEK_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return answer.strip()


def extractive_fallback(citations: list) -> str:
    """Simple extractive fallback when generative answer fails."""
    parts = []
    for c in citations:
        abstract = c.get("abstract") or ""
        first_sent = re.split(r"[。！？;；]\s*", abstract.strip())[0] if abstract else ""
        if first_sent:
            parts.append(f"{first_sent} [{c['index']}]")
    return " ".join(parts)
