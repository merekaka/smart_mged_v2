"""
意图解析器 - 结构化查询版
支持百炼/DeepSeek 等 OpenAI 兼容 API
"""
import json
import logging
import os
import re
import time
from typing import Optional, List
import requests
from django.conf import settings

from .models import Intent, IntentType, Condition, Operator, LogicOp, SubQuery, QueryGroup

logger = logging.getLogger(__name__)


def _load_lines(filename: str, fallback: Optional[List[str]] = None) -> List[str]:
    """从 resources 目录加载文本文件，返回非空且非注释的行列表"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(current_dir, "resources", filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    except Exception as e:
        logger.warning(f"加载 {filename} 失败: {e}")
        return fallback or []


VALID_PROPERTY_NAMES = _load_lines("property_names.txt", [
    "tensile_strength", "yield_strength", "elastic_modulus",
    "melting_point", "thermal_conductivity", "crystal_structure",
    "grain_size", "density", "hardness"
])
VALID_DATASET_NAMES = _load_lines("entity_dataset_names.txt")

# ---------------------------------------------------------------------------
# 动态属性白名单（从数据库 property_table 加载）
# ---------------------------------------------------------------------------
PROPERTY_DYNAMIC_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "resources", "property_names_dynamic.txt"
)
PROPERTY_REFRESH_INTERVAL = 300  # 默认 5 分钟（可被 settings.INTENT_PROPERTY_REFRESH_INTERVAL 覆盖）
PROPERTY_DESC_LIMIT = None       # 默认不限制向 Prompt 注入的属性数量（设为整数则限制前 N 条）


def _ensure_property_file_fresh():
    """
    检查 property_names_dynamic.txt 是否存在及是否过期，需要时从数据库重新生成。
    刷新间隔可通过 Django settings.INTENT_PROPERTY_REFRESH_INTERVAL 配置（单位：秒）。
    """
    interval = getattr(settings, 'INTENT_PROPERTY_REFRESH_INTERVAL', PROPERTY_REFRESH_INTERVAL)
    need_refresh = False
    if not os.path.exists(PROPERTY_DYNAMIC_FILE):
        need_refresh = True
    else:
        mtime = os.path.getmtime(PROPERTY_DYNAMIC_FILE)
        if time.time() - mtime > interval:
            need_refresh = True

    if not need_refresh:
        return

    try:
        from django.db import connections
        with connections['default'].cursor() as cursor:
            cursor.execute(
                "SELECT property_name, property_description "
                "FROM property_table "
                "ORDER BY property_name"
            )
            rows = cursor.fetchall()

        lines = ["# property_name: property_description\n"]
        for name, desc in rows:
            desc = desc.replace('\n', ' ').replace('\r', '') if desc else ''
            lines.append(f"{name}: {desc}\n")

        with open(PROPERTY_DYNAMIC_FILE, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        logger.info(f"已刷新 {len(rows)} 条属性到 property_names_dynamic.txt")
    except Exception as e:
        logger.warning(f"刷新属性文件失败: {e}")


class IntentParser:
    """
    意图解析器 - 调用 LLM API 解析自然语言
    默认适配阿里云百炼平台（OpenAI 兼容模式）
    """
    
    SYSTEM_PROMPT_TEMPLATE = """你是材料科学领域的查询助手。请分析用户查询，提取关键信息并输出标准JSON。

【重要】datasets 字段只能使用以下列表中的有效数据集名称。必须严格依据用户原文，只有当用户的问题中明确包含以下完整数据集名称时，才将其放入 datasets 数组。不得根据材料类型或属性进行推断。如果用户没有明确提到任何数据集，或提到的名称不在以下列表中，datasets 必须为空数组 []。其中“钴基高温合金成分与相组成”是一个数据集名称，而非“钴基高温合金”数据集加上“成分与相组成”属性的组合，因此只有当用户查询中完整出现“钴基高温合金成分与相组成”这个名称时，才将其加入 datasets。
        不得编造列表外的名称：
{valid_datasets}

【重要】关于 field 字段的填写规范
查询条件中的属性字段（field）必须严格使用下方列表中的英文属性名，严禁使用数据集名称或其他非属性字段作为 field 值。
属性名映射规则说明：
1、每个属性名后的中文描述仅用于辅助你将用户的自然语言查询映射到正确的英文属性名
2、冒号前的内容为英文属性名（field 值必须使用此部分）
3、冒号后、第一个逗号前的中文为该英文属性名的中文直译
4、在匹配属性名称时，应当选择与该中文直译尽可能相似的属性名，但最终 field 值必须使用对应的英文属性名
{valid_properties}

【重要】对于用户查询中类似于在A和B之间、从A到B、A到B范围内等表达范围的语句，必须将其解析为同一 field 的多个条件（如 A >= value1 AND A <= value2），而且必须为闭区间

【补充】1、“应变”属性名实际对应的是strain；
        2、“试验单位”属性名实际对应的是testing_institution；
        3、有些类似于“20℃-steady flow”的字符串类型属性，虽然包含了数字和单位，但它们的 field 仍然是一个纯字符串类型的属性（如 loading_condition），value 则是用户查询中出现的完整字符串（如 "20℃-steady flow"），而不是单纯的数字或单位。但是含百分比符号“%”的值还是需要正常识别为数值型的（如 "10%" 应该解析为 value=10, unit="%"），除非该字符串是某个属性的完整值（如 "20%-steady flow"），这时就作为一个整体字符串处理。
        4、“样品名称”应该为“material_name”，因为用户查询中更常用“材料”或“样品”来指代这个属性，但在数据表中它的字段名是 material_name。
        5、“序号”应该被映射到“sample_code”;
        6、“试验日期”应该被映射到“test_time”；
        7、“p型泽贝克系数”应该被映射到“seebeck_coefficient_p_type”，n型泽贝克系数应该被映射到“seebeck_coefficient_n_type”，而不是统称为“seebeck_coefficient”。
        8、“比热容”、“比热”映射到“specific_heat_capacity”，“粘度”应该映射到“viscosity”。
        9、“试验温度”应该被映射为“temperature”
        10、“测试条件”应该被映射为“test_condition”
输出JSON格式:
{{
    "intent_type": "search|compare",
    "groups": [
        {{
            "logic_op": "and|or|not",
            "conditions": [
                {{"field": "字段名", "operator": "运算符", "value": 值, "unit": "单位", "agg_func": "聚合函数或null"}}
            ],
            "datasets": ["数据集名称1", "数据集名称2"]
        }}
    ],
    "group_logic_op": "and|or|not",
    "target_properties": ["用户明确想查看的属性字段名"],
    "limit": null,
    "follow_up_scope": "current",  // "current"=基于当前结果, "original"=基于原始结果
    "explanation": "查询说明"
}}

groups 说明:
- 简单查询: groups 中只有 1 个元素
- 复杂查询: groups 中有多个元素

【重要】每个 group 只对应一个唯一的 field。如果查询涉及多个不同 field 的条件，必须为每个 field 创建独立的 group，并通过 group_logic_op 控制它们之间的关系。
- 同一 field 的多个条件（如 "抗拉强度大于100且小于200"）：放在同一个 group 的 conditions 数组中
- 不同 field 的条件（如 "抗拉强度大于500且屈服强度大于400"）：必须拆分成多个 groups，每个 group 只有一个 field
- 跨数据集查询（如 "泊松比小于4.0和加载条件小于27.6"）：不同 field 且不同数据集，自然拆分为多个 groups

conditions 说明（条件约束数组）:
- conditions 是一个数组，每个元素代表一条属性约束条件。
- **重要区分**：
  - 普通/范围查询：有 operator + value，属于数值/文本约束
  - 聚合查询：operator=null, value=null，但有 agg_func + field，属于聚合约束，**必须放入 conditions，不能空数组**
  - 对比查询（如"钛合金和铝合金的熔点对比"）：没有任何属性约束，conditions 必须为空数组 []
- 单条件示例: "抗拉强度大于500MPa" → conditions 中只有 1 个元素
- 同一 field 多条件示例: "抗拉强度大于100且小于200" → conditions 中有 2 个元素，都是同一 field（tensile_strength），由 logic_op 控制关系
- 每个 condition 对象包含以下字段:
    - field      : str   属性字段名（必须从上述有效属性名列表中选择，英文）
    - operator   : str   运算符，仅允许: =, >, <, >=, <=, null
    - value      : int|float|str  比较值。数值型属性传数字；文本型属性传字符串；聚合查询传 null
    - unit       : str|null  单位，如 "MPa", "g/cm3"。无单位或不确定时设为 null
    - agg_func   : str|null  聚合函数。普通查询设为 null；聚合查询设为 "max"/"min"/"max_n"/"min_n"/"avg"/"sum"/"count"/"variance"
- 聚合查询的条件: 当 agg_func 不为 null 时，operator 和 value 直接设为 null，但**该 condition 必须存在于 conditions 数组中**

【重要】如果用户查询中包含"在此基础上""进一步""从这些数据"等递进语义，follow_up_scope 设为 "current"；
        如果包含"从最初""从原始结果""重新"等重置语义，设为 "original"。默认 "current"。

【重要】value 字段必须严格使用用户查询原文中出现的值，禁止改写、推断或生成用户原文中不存在的文本。例如用户输入"内部"时，value 必须为"内部"，绝对不允许输出"内层"等其他表述。数值型value直接提取原文数字即可。有些value值中间可能包含空格，如"20℃-steady flow"，必须完整保留空格和原文格式，不得改写为"20℃-steadyflow"或"20℃ steady flow"等其他形式。

运算符仅允许: =, >, <, >=, <=, null（当 operator 为 null 时，value 也必须为 null，表示该条件仅表达对字段的聚合理解，具体聚合类型由 agg_func 指定）

agg_func 说明（可选）:
- null: 普通条件查询（默认）
- max: 求最大值（返回单条记录，使用等值匹配）
- min: 求最小值（返回单条记录，使用等值匹配）
- max_n: 从大到小排序（配合 limit 使用，返回前 N 条）
- min_n: 从小到大排序（配合 limit 使用，返回前 N 条）
- avg: 求平均值
- variance: 求方差
- sum: 求和
- count: 计数

【重要】当用户查询包含"最大""最小"等聚合意图时，必须将该字段作为一条 condition 放入 conditions 列表，并设置对应的 agg_func。
- 如果只查"最大的""最小的"（无数量）：agg_func 用 "max" 或 "min"
- 如果查"最大的N条""前N个""最小的N条"（有数量）：agg_func 用 "max_n" 或 "min_n"，同时根级 limit 设为 N

例如：
- "弹性模量最小的" → agg_func: "min", limit: null
- "抗拉强度最大的5条" → agg_func: "max_n", limit: 5
- "弹性模量最小的3条" → agg_func: "min_n", limit: 3
- "按密度从高到低排序，取前10条" → agg_func: "max_n", limit: 10

当用户没有指定数量时，limit 设为 null。

当 agg_func 不为 null 时，表示对该字段做聚合运算，operator和value 必须设为null，如果结果不为null也强制改为null。

logic_op 说明:
- and: 所有条件同时满足（默认）
- or: 任一条件满足
- not: 排除这些条件

intent_type 说明:
- search: 查找/检索某类材料
- compare: 对比两种或多种材料

示例1输入: "查找抗拉强度大于500MPa的钛合金"
示例1输出（简单查询，groups 中只有 1 个元素）:
{{
    "intent_type": "search",
    "groups": [
        {{
            "logic_op": "and",
            "conditions": [{{"field": "tensile_strength", "operator": ">", "value": 500, "unit": "MPa", "agg_func": null}}],
            "datasets": ["钛合金数据"]
        }}
    ],
    "group_logic_op": "and",
    "target_properties": [],
    "explanation": "查找高强度钛合金材料"
}}


示例2输入: "查找泊松比小于4.0的材料样本和加载条件小于27.6的样本"
示例2输出（跨数据集查询，groups 中有 2 个元素）:
{{
    "intent_type": "search",
    "groups": [
        {{
            "logic_op": "and",
            "conditions": [{{"field": "poisson_ratio", "operator": "<", "value": 4.0, "agg_func": null}}],
            "datasets": ["特殊钢-物理性能-泊松比"]
        }},
        {{
            "logic_op": "and",
            "conditions": [{{"field": "loading_condition", "operator": "<", "value": 27.6, "agg_func": null}}],
            "datasets": ["高温合金-力学性能-加载条件"]
        }}
    ],
    "group_logic_op": "and",
    "target_properties": [],
    "limit": null,
    "explanation": "查找泊松比小于4.0的材料样本和加载条件小于27.6的样本"
}}

    示例3输入: "查询抗拉强度最大的材料"
    示例3输出（聚合查询）:
    {{
        "intent_type": "search",
        "groups": [
            {{
                "logic_op": "and",
                "conditions": [{{"field": "tensile_strength", "operator": null, "value": null, "unit": null, "agg_func": "max"}}],
                "datasets": ["材料数据"]
            }}
        ],
        "group_logic_op": "and",
        "target_properties": [],
        "limit": null,
        "explanation": "查询抗拉强度最大的材料"
    }}

    示例4输入: "查找密度小于5的材料中弹性模量最小的"
    示例4输出（普通条件 + 聚合条件混合查询，不同 field 拆分为不同 groups）:
    {{
        "intent_type": "search",
        "groups": [
            {{
                "logic_op": "and",
                "conditions": [
                    {{"field": "density", "operator": "<", "value": 5, "unit": "g/cm3", "agg_func": null}}
                ],
                "datasets": ["材料数据"]
            }},
            {{
                "logic_op": "and",
                "conditions": [
                    {{"field": "elastic_modulus", "operator": null, "value": null, "unit": null, "agg_func": "min"}}
                ],
                "datasets": ["材料数据"]
            }}
        ],
        "group_logic_op": "and",
        "target_properties": [],
        "limit": null,
        "explanation": "查找密度小于5的材料中弹性模量最小的"
    }}

    示例5输入: "计算结果.已腐蚀量(um)在0.1和8.2之间的样本有哪些?"
    示例5输出（同一 field 的范围查询，两个条件放在同一 group 的 conditions 中）:
    {{
        "intent_type": "search",
        "groups": [
            {{
                "logic_op": "and",
                "conditions": [
                    {{"field": "accumulated_corrosion_depth", "operator": ">", "value": 0.1, "unit": "um", "agg_func": null}},
                    {{"field": "accumulated_corrosion_depth", "operator": "<", "value": 8.2, "unit": "um", "agg_func": null}}
                ],
                "datasets": []
            }}
        ],
        "group_logic_op": "and",
        "target_properties": [],
        "limit": null,
        "explanation": "计算结果.已腐蚀量(um)在0.1和8.2之间的样本有哪些?"
    }}"""

    def __init__(self):
        # 根据 INTENT_MODE 切换本地 Ollama 或云端 API 配置
        self.mode = getattr(settings, 'INTENT_MODE', 'local')
        
        if self.mode == 'cloud':
            self.api_key = getattr(settings, 'INTENT_CLOUD_API_KEY', '')
            self.api_base = getattr(settings, 'INTENT_CLOUD_API_BASE', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
            self.model = getattr(settings, 'INTENT_CLOUD_MODEL', 'qwen3-32b')
        else:
            # 默认本地 Ollama，兼容旧的 DEEPSEEK_* 变量
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
        
        # 1) 确保属性文件最新（从数据库刷新）
        _ensure_property_file_fresh()

        # 2) 加载带描述的动态属性列表
        dynamic_properties = []
        try:
            with open(PROPERTY_DYNAMIC_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    dynamic_properties.append(line)
        except Exception:
            # 若动态文件读取失败，fallback 到静态列表
            dynamic_properties = VALID_PROPERTY_NAMES.copy()

        # 3) 可选：限制注入 Prompt 的属性数量（默认不限制）
        desc_limit = getattr(settings, 'INTENT_PROPERTY_DESC_LIMIT', PROPERTY_DESC_LIMIT)
        if desc_limit is not None:
            properties_display = dynamic_properties[:desc_limit]
            if len(dynamic_properties) > desc_limit:
                properties_display.append("... (更多属性)")
        else:
            properties_display = dynamic_properties.copy()

        valid_properties_str = "\n".join([f"- {name}" for name in properties_display])
        valid_datasets_str = "\n".join([f"- {name}" for name in VALID_DATASET_NAMES])
        self.system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(
            valid_properties=valid_properties_str,
            valid_datasets=valid_datasets_str
        )
    
    def parse(self, query: str) -> Optional[Intent]:
        """解析用户查询为意图对象"""
        if not query or not query.strip():
            logger.warning("IntentParser.parse received empty query")
            return None
        
        logger.info(f"IntentParser starting parse, query={query[:120]!r}, mode={self.mode}, model={self.model}")
        
        try:
            response = self._call_llm(query)
            if not response:
                logger.warning("LLM response empty, falling back to simple_parse")
                return self._simple_parse(query)
            
            parsed = self._parse_json(response)
            if not parsed:
                logger.warning("JSON parse failed for LLM response, falling back to simple_parse")
                return self._simple_parse(query)
            
            intent = self._build_intent(parsed, query)
            logger.info(f"Intent built: type={intent.intent_type.value}, groups={len(intent.groups)}, "
                        f"target_properties={intent.target_properties}, explanation={intent.explanation[:60]!r}")
            return intent
            
        except Exception as e:
            logger.error(f"IntentParser.parse failed: {e}", exc_info=True)
            return self._simple_parse(query)
    
    def _call_llm(self, query: str) -> Optional[str]:
        """调用 LLM API（OpenAI 兼容格式，适配百炼/DeepSeek 等）"""
        if not self.api_key:
            logger.warning("IntentParser._call_llm skipped: no API key configured")
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
            "response_format": {"type": "json_object"}
        }
        
        # Qwen3 系列默认开启思考模式，会导致输出包含 <think>...</think> 标签，
        # 干扰 JSON 解析。这里对 qwen3 模型默认关闭思考模式。
        # 百炼兼容接口要求 enable_thinking 作为顶层参数传入。
        if self.model and "qwen3" in self.model.lower():
            payload["enable_thinking"] = False
        
        logger.info(f"Calling LLM API: url={self.api_base}, model={self.model}")
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            logger.info(f"LLM API response received, prompt_tokens={usage.get('prompt_tokens')}, "
                        f"completion_tokens={usage.get('completion_tokens')}, content_length={len(content)}")
            return content
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            return None
    
    def _parse_json(self, text: str) -> Optional[dict]:
        """解析JSON响应"""
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
    def _safe_enum(enum_cls, value: str, default):
        """安全解析枚举值，失败时返回默认值"""
        try:
            return enum_cls(value)
        except ValueError:
            return default
    
    def _make_conditions(self, raw_list: list) -> list:
        """将原始条件列表转换为 [Condition, ...] 列表。
        
        同一 field 可以出现多次（如 >100 和 <200），不同 field 的条件将在 _build_intent 中拆分到不同 groups。
        支持 operator 为 null（聚合查询场景）。
        """
        parsed = []
        for c in raw_list:
            try:
                op_str = c.get("operator", "=")
                # 处理 operator 为 null / "null" / None 的情况（聚合查询）
                if op_str is None or (isinstance(op_str, str) and op_str.lower() == "null"):
                    operator = None
                else:
                    operator = self._safe_enum(Operator, op_str, Operator.EQ)
                
                field = c.get("field", "")
                # 跳过无意义的 field
                if not field:
                    continue
                
                # 聚合查询时 value 也可能为 null
                value = c.get("value")
                
                parsed.append(Condition(
                    field=field,
                    operator=operator,
                    value=value,
                    unit=c.get("unit"),
                    agg_func=c.get("agg_func")
                ))
            except Exception:
                continue
        return parsed
    
    def _build_intent(self, parsed: dict, original_query: str) -> Intent:
        """
        构建意图对象 Intent

        将 LLM 返回的 JSON 字典（groups 格式）转换为 Intent 数据类。
        LLM 直接输出 groups 数组，每个 group 包含 logic_op、conditions、datasets。

        示例输出:
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
        """
        # 公共字段解析
        intent_type = self._safe_enum(IntentType, parsed.get("intent_type", "search"), IntentType.SEARCH)
        group_logic_op = self._safe_enum(LogicOp, parsed.get("group_logic_op", "and"), LogicOp.AND)

        target_properties = []
        for tp in parsed.get("target_properties", []):
            mapped = tp
            if mapped:
                target_properties.append(mapped)

        limit = parsed.get("limit")
        if limit is not None:
            try:
                limit = int(limit)
                if limit <= 0:
                    limit = None
            except (ValueError, TypeError):
                limit = None

        # ========== 解析 groups（新版统一格式）==========
        # 关键规则：每个 group 只对应一个唯一的 field。
        # 如果 LLM 返回的某个 group 包含多个不同 field 的 conditions，
        # 必须按 field 拆分成多个独立的 QueryGroup。
        groups = []
        raw_groups = parsed.get("groups", [])
        logger.debug(f"_build_intent: raw_groups count={len(raw_groups)}")
        
        if raw_groups:
            for g in raw_groups:
                g_logic_op = g.get("logic_op", "and")
                conditions = self._make_conditions(g.get("conditions", []))
                # datasets 严格基于原始查询中的精确子串匹配，不使用 LLM 推断
                llm_datasets = g.get("datasets", [])
                datasets = [ds for ds in llm_datasets if ds in VALID_DATASET_NAMES and ds in original_query] if llm_datasets else []
                
                logger.debug(f"  group: logic_op={g_logic_op}, conditions={len(conditions)}, datasets={datasets}")
                
                if not conditions:
                    # 无条件的 group（如对比查询）直接保留
                    groups.append(QueryGroup(logic_op=g_logic_op, conditions=[], datasets=datasets))
                else:
                    # 按 field 拆分成多个 group
                    field_groups = {}
                    for cond in conditions:
                        field_groups.setdefault(cond.field, []).append(cond)
                    
                    for field, conds in field_groups.items():
                        groups.append(QueryGroup(logic_op=g_logic_op, conditions=conds, datasets=datasets))
        
        # fallback：如果 LLM 没返回 groups，从原始查询中提取 datasets 创建默认 group
        if not groups:
            datasets = self._extract_datasets(original_query)
            logger.warning("_build_intent: no groups from LLM, fallback to dataset extraction")
            groups.append(QueryGroup(logic_op="and", conditions=[], datasets=datasets))

        # 提取 follow_up_scope（筛选类 follow-up 的数据源范围）
        follow_up_scope = str(parsed.get("follow_up_scope", "current")).lower()
        if follow_up_scope not in {"current", "original"}:
            follow_up_scope = "current"

        intent = Intent(
            intent_type=intent_type,
            groups=groups,
            group_logic_op=group_logic_op,
            target_properties=target_properties,
            explanation=parsed.get("explanation", original_query),
            limit=limit,
            query_mode="complex" if len(groups) > 1 else "simple",
            follow_up_scope=follow_up_scope,
        )
        logger.info(f"_build_intent finished: mode={intent.query_mode}, groups={len(intent.groups)}, "
                    f"conditions_total={sum(len(g.conditions) for g in intent.groups)}, datasets_total={sum(len(g.datasets) for g in intent.groups)}")
        return intent
    
    def _extract_datasets(self, query: str) -> List[str]:
        """从用户查询中提取已存在的数据集名称（仅精确子串匹配）"""
        if not query or not VALID_DATASET_NAMES:
            return []
        
        matched = []
        
        for name in VALID_DATASET_NAMES:
            # 精确子串匹配：数据集名称必须完整出现在用户查询中
            if name in query:
                matched.append(name)
        
        # 去重并按长度降序排序
        matched = sorted(dict.fromkeys(matched), key=len, reverse=True)
        
        # 过滤掉被更长匹配包含的子串（例如保留"特殊钢-硬度试验"而非"特殊钢-硬度"）
        return [name for name in matched if not any(name != other and name in other for other in matched)]
    
    def _simple_parse(self, query: str) -> Intent:
        """简单解析（LLM失败时的回退）"""
        datasets = self._extract_datasets(query)
        return Intent(
            intent_type=IntentType.SEARCH,
            groups=[QueryGroup(logic_op="and", conditions=[], datasets=datasets)],
            group_logic_op=LogicOp.AND,
            explanation=query,
            query_mode="simple",
        )
