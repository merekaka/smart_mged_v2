"""
意图理解引擎 - 数据模型
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Union, Any
from enum import Enum


class IntentType(Enum):
    SEARCH = "search"
    COMPARE = "compare"


class Operator(Enum):
    EQ = "="
    GT = ">"
    LT = "<"
    GTE = ">="
    LTE = "<="
    CONTAINS = "contains"
    NEQ = "!="
    NOT = "" # 用于聚合条件，表示不使用具体的比较操作符


class AggregationType(Enum):
    NONE = "none"


class LogicOp(Enum):
    AND = "and"
    OR = "or"
    NOT = "not"


@dataclass
class Condition:
    """
    查询条件（内部模型）

    示例:
        Condition(field="tensile_strength", operator=Operator.GT, value=500, unit="MPa")
        # 表示: tensile_strength > 500 MPa

    聚合运算示例:
        Condition(field="tensile_strength", operator=Operator.EQ, value=0, agg_func="max")
        # 表示: 查询 tensile_strength 的最大值
    """
    field: str                      # 英文字段名，如 "tensile_strength"
    operator: Optional[Operator]    # 操作符枚举: =, >, <, >=, <=, contains, !=；聚合查询时为 null
    value: Optional[Union[str, int, float]]  # 比较值；聚合查询时为 null
    unit: Optional[str] = None      # 单位，如 "MPa", "g/cm3"（可选）
    agg_func: Optional[str] = None  # 聚合运算: max, min, avg, variance, sum, count

    def to_dict(self):
        return {
            "field": self.field,
            "operator": self.operator.value if isinstance(self.operator, Enum) else None,
            "value": self.value,
            "unit": self.unit,
            "agg_func": self.agg_func
        }


@dataclass
class SubQuery:
    """
    子查询：一组独立的查询条件 + 明确归属的数据集
    
    用于表达跨数据集查询中的单个意图，例如：
        "查找泊松比小于4.0的材料样本和加载条件小于27.6的样本"
    其中 "泊松比小于4.0" 和 "加载条件小于27.6" 分别属于不同数据集，
    各自构成一个 SubQuery。
    
    字段说明:
        conditions        : 属性约束条件列表
        datasets          : 该子查询对应的数据集名称列表
        target_properties : 用户明确想查看的属性字段
        explanation       : 该子查询的文字说明
        logic_op          : 子查询内部多条件间的逻辑关系
    """
    conditions: List[Condition] = field(default_factory=list)
    datasets: List[str] = field(default_factory=list)
    target_properties: List[str] = field(default_factory=list)
    explanation: str = ""
    logic_op: LogicOp = LogicOp.AND

    def to_dict(self):
        return {
            "conditions": [c.to_dict() for c in self.conditions],
            "datasets": self.datasets,
            "target_properties": self.target_properties,
            "explanation": self.explanation,
            "logic_op": self.logic_op.value if isinstance(self.logic_op, Enum) else self.logic_op,
        }


@dataclass
class QueryGroup:
    """
    查询条件组：一组条件 + 对应的数据集 + 组内逻辑关系。

    示例（简单查询只有一组）:
        QueryGroup(
            logic_op="and",
            conditions=[Condition(field="tensile_strength", operator=Operator.GT, value=500, unit="MPa")],
            datasets=["钛合金数据"]
        )

    示例（跨数据集查询有两组）:
        QueryGroup(logic_op="and", conditions=[Condition(field="poisson_ratio", operator=Operator.LT, value=4.0)], datasets=["特殊钢-物理性能-泊松比"])
        QueryGroup(logic_op="and", conditions=[Condition(field="loading_condition", operator=Operator.LT, value=27.6)], datasets=["高温合金-力学性能-加载条件"])
    """
    logic_op: str = "and"
    conditions: List[Condition] = field(default_factory=list)
    datasets: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "logic_op": self.logic_op,
            "conditions": [c.to_dict() for c in self.conditions],
            "datasets": self.datasets,
        }


@dataclass
class Intent:
    """
    解析后的用户意图（中间层数据结构）

    由 IntentParser.parse() 生成，包含从自然语言中提取的所有关键信息。
    作为意图理解引擎的统一输出，供下游模块直接使用。

    字段说明:
        intent_type       : 意图类型，SEARCH(检索) 或 COMPARE(对比)
        groups            : 查询条件组列表，每个组包含 logic_op、conditions、datasets
        group_logic_op    : 多组之间的逻辑关系，AND(默认) / OR / NOT
        target_properties : 用户明确想查看的属性字段，如 ["melting_point"]
        explanation       : 查询意图的文字说明
        limit             : 返回结果数量限制，如 5、10；为 null 表示不限制
        query_mode        : 查询模式，"simple"(简单查询) 或 "complex"(复杂/跨数据集查询)

    简单查询示例:
        Intent(
            intent_type=IntentType.SEARCH,
            query_mode="simple",
            groups=[
                QueryGroup(
                    logic_op="and",
                    conditions=[Condition(field="tensile_strength", operator=Operator.GT, value=500, unit="MPa")],
                    datasets=["钛合金数据"]
                )
            ]
        )

    跨数据集查询示例:
        Intent(
            intent_type=IntentType.SEARCH,
            query_mode="complex",
            groups=[
                QueryGroup(logic_op="and", conditions=[Condition(field="poisson_ratio", operator=Operator.LT, value=4.0)], datasets=["特殊钢-物理性能-泊松比"]),
                QueryGroup(logic_op="and", conditions=[Condition(field="loading_condition", operator=Operator.LT, value=27.6)], datasets=["高温合金-力学性能-加载条件"]),
            ],
            group_logic_op=LogicOp.AND
        )
    """
    intent_type: IntentType = IntentType.SEARCH
    groups: List[QueryGroup] = field(default_factory=list)
    group_logic_op: LogicOp = LogicOp.AND
    target_properties: List[str] = field(default_factory=list)
    explanation: str = ""
    limit: Optional[int] = None
    query_mode: str = "simple"
    follow_up_scope: str = "current"  # "current"=基于上一轮结果, "original"=基于首轮缓存

    def to_dict(self):
        return {
            "intent_type": self.intent_type.value if isinstance(self.intent_type, Enum) else self.intent_type,
            "groups": [g.to_dict() for g in self.groups],
            "group_logic_op": self.group_logic_op.value if isinstance(self.group_logic_op, Enum) else self.group_logic_op,
            "target_properties": self.target_properties,
            "explanation": self.explanation,
            "limit": self.limit,
            "query_mode": self.query_mode,
            "follow_up_scope": self.follow_up_scope,
        }
