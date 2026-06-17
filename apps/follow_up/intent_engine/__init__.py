"""
意图理解引擎 (Intent Engine)
---------------------------
提供自然语言到意图对象的解析能力

其他模块可直接导入使用:
    from apps.follow_up.intent_engine import Intent, parse_intent
    intent = parse_intent("查找抗拉强度大于500MPa的钛合金")
"""

default_app_config = 'apps.follow_up.intent_engine.apps.IntentEngineConfig'

# 导出核心数据结构，方便下游模块直接导入
from .models import (
    Intent,
    Condition,
    Operator,
    LogicOp,
    IntentType,
)

# 导出直接调用 API
from .api import (
    parse_intent,
)
