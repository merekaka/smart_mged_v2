"""
意图理解引擎 - Python 直接调用接口

其他模块可通过导入本模块，直接调用意图解析功能，
无需经过 HTTP 请求。

使用示例:
    from apps.intent_engine.api import parse_intent
    intent = parse_intent("查找抗拉强度大于500MPa的钛合金")
    print(intent.to_dict())
"""
import logging
from typing import Optional

from .models import Intent

logger = logging.getLogger(__name__)

# 延迟初始化全局实例（避免模块导入时立即读取 Django settings）
_parser = None


def _get_parser():
    """惰性获取 IntentParser 实例"""
    global _parser
    if _parser is None:
        from .parser import IntentParser
        _parser = IntentParser()
        logger.info("IntentParser initialized (lazy load)")
    return _parser


def parse_intent(query: str) -> Optional[Intent]:
    """
    将自然语言查询解析为 Intent 对象。

    Intent 对象结构:
        - intent_type      : IntentType.SEARCH / IntentType.COMPARE
        - groups           : List[QueryGroup]  查询条件组列表
          每个 QueryGroup 包含:
            - logic_op   : str  组内逻辑关系 "and"/"or"/"not"
            - conditions : List[Condition]  属性约束条件列表
            - datasets   : List[str]  该组对应的数据集名称列表
        - group_logic_op   : LogicOp.AND / OR / NOT  多组之间的逻辑关系
        - target_properties: List[str]  目标属性字段
        - explanation      : str  查询说明
        - sort_by          : Optional[Dict]  排序规则
        - query_mode       : str  "simple" / "complex"

    Args:
        query: 用户输入的自然语言查询，例如 "查找抗拉强度大于500MPa的钛合金"

    Returns:
        Intent 对象；解析失败返回 None
    """
    if not query or not query.strip():
        logger.warning("parse_intent called with empty query")
        return None
    logger.info(f"Parsing intent for query: {query[:80]!r}")
    intent = _get_parser().parse(query)
    if intent:
        logger.info(f"Intent parsed successfully: type={intent.intent_type.value}, mode={intent.query_mode}, groups={len(intent.groups)}")
    else:
        logger.warning(f"Intent parsing returned None for query: {query[:80]!r}")
    return intent
