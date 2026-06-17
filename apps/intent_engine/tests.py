"""
意图理解引擎测试文件 - 纯意图理解版
测试基础的意图解析和数据模型
"""
import json
import sys
import os
import unittest

# 添加项目路径以支持直接运行
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# 尝试设置 Django
try:
    import django
    django.setup()
except Exception as e:
    print(f"Django 设置警告: {e}")

# 使用绝对导入
try:
    from apps.intent_engine.models import (
        IntentType, Operator, LogicOp,
        Condition, Intent, QueryGroup
    )
    from apps.intent_engine.parser import IntentParser
except ImportError:
    from .models import (
        IntentType, Operator, LogicOp,
        Condition, Intent, QueryGroup
    )
    from .parser import IntentParser


class TestModels(unittest.TestCase):
    """测试数据模型"""

    def test_intent_type_enum(self):
        """测试意图类型枚举"""
        self.assertEqual(IntentType.SEARCH.value, "search")
        self.assertEqual(IntentType.COMPARE.value, "compare")

    def test_condition_to_dict(self):
        """测试条件对象序列化"""
        cond = Condition(
            field="tensile_strength",
            operator=Operator.GT,
            value=500,
            unit="MPa"
        )
        result = cond.to_dict()
        self.assertEqual(result["field"], "tensile_strength")
        self.assertEqual(result["operator"], ">")
        self.assertEqual(result["value"], 500)
        self.assertEqual(result["unit"], "MPa")
        self.assertIsNone(result["agg_func"])

    def test_intent_to_dict(self):
        """测试意图对象序列化"""
        intent = Intent(
            intent_type=IntentType.SEARCH,
            groups=[
                QueryGroup(
                    logic_op="and",
                    conditions=[Condition("tensile_strength", Operator.GT, 500, "MPa")],
                    datasets=["钛合金数据"]
                )
            ],
            explanation="查找高强度钛合金"
        )
        result = intent.to_dict()
        self.assertEqual(result["intent_type"], "search")
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(result["groups"][0]["logic_op"], "and")
        self.assertEqual(len(result["groups"][0]["conditions"]), 1)
        self.assertEqual(result["query_mode"], "simple")

    def test_intent_with_datasets_to_dict(self):
        """测试包含数据集的意图对象序列化"""
        intent = Intent(
            intent_type=IntentType.SEARCH,
            groups=[
                QueryGroup(logic_op="and", conditions=[], datasets=["钛合金数据"])
            ],
            explanation="查找钛合金数据"
        )
        result = intent.to_dict()
        self.assertEqual(result["groups"][0]["datasets"], ["钛合金数据"])
        self.assertEqual(result["query_mode"], "simple")

    def test_complex_intent_to_dict(self):
        """测试复杂/跨数据集意图对象序列化"""
        intent = Intent(
            intent_type=IntentType.SEARCH,
            query_mode="complex",
            group_logic_op=LogicOp.AND,
            explanation="查找泊松比小于4.0的材料样本和加载条件小于27.6的样本",
            groups=[
                QueryGroup(logic_op="and", conditions=[Condition("poisson_ratio", Operator.LT, 4.0)], datasets=["特殊钢-物理性能-泊松比"]),
                QueryGroup(logic_op="and", conditions=[Condition("hardness", Operator.LT, 27.6)], datasets=["特殊钢-硬度"]),
            ]
        )
        result = intent.to_dict()
        self.assertEqual(result["query_mode"], "complex")
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(len(result["groups"][0]["conditions"]), 1)
        self.assertEqual(len(result["groups"][1]["conditions"]), 1)
        self.assertEqual(result["groups"][0]["datasets"], ["特殊钢-物理性能-泊松比"])
        self.assertEqual(result["groups"][1]["datasets"], ["特殊钢-硬度"])


class TestIntentParserBuildIntent(unittest.TestCase):
    """测试意图构建方法"""

    def setUp(self):
        try:
            from apps.intent_engine.parser import IntentParser
        except ImportError:
            from .parser import IntentParser
        self.parser = IntentParser()

    def test_build_basic_intent(self):
        """测试构建基础意图"""
        parsed = {
            "groups": [
                {
                    "logic_op": "and",
                    "conditions": [
                        {"field": "tensile_strength", "operator": ">", "value": 500, "unit": "MPa"}
                    ],
                    "datasets": []
                }
            ],
            "explanation": "查找高强度钛合金"
        }
        intent = self.parser._build_intent(parsed, "查找抗拉强度大于500MPa的钛合金")

        self.assertEqual(intent.intent_type, IntentType.SEARCH)
        self.assertEqual(len(intent.groups), 1)
        self.assertEqual(intent.groups[0].logic_op, "and")
        self.assertEqual(len(intent.groups[0].conditions), 1)
        self.assertEqual(intent.groups[0].conditions[0].field, "tensile_strength")
        self.assertEqual(intent.groups[0].conditions[0].operator, Operator.GT)
        self.assertEqual(intent.query_mode, "simple")

    def test_build_with_chinese_field_mapping(self):
        """测试中文字段映射"""
        parsed = {
            "groups": [
                {
                    "logic_op": "and",
                    "conditions": [
                        {"field": "抗拉强度", "operator": ">", "value": 400, "unit": "MPa"}
                    ],
                    "datasets": []
                }
            ],
            "explanation": "查询钢的抗拉强度"
        }
        intent = self.parser._build_intent(parsed, "钢的抗拉强度大于400MPa")

        # 原 FIELD_MAPPING 已移除，字段保持原样透传
        self.assertEqual(len(intent.groups), 1)
        self.assertEqual(intent.groups[0].logic_op, "and")
        self.assertEqual(intent.groups[0].conditions[0].field, "抗拉强度")

    def test_build_empty_conditions(self):
        """测试构建空条件意图"""
        parsed = {
            "groups": [
                {
                    "logic_op": "and",
                    "conditions": [],
                    "datasets": []
                }
            ],
            "explanation": "查询铝合金"
        }
        intent = self.parser._build_intent(parsed, "铝合金")

        self.assertEqual(len(intent.groups), 1)
        self.assertEqual(len(intent.groups[0].conditions), 0)

    def test_build_intent_with_logic_op(self):
        """测试解析逻辑关系词"""
        parsed = {
            "groups": [
                {
                    "logic_op": "and",
                    "conditions": [],
                    "datasets": []
                }
            ],
            "group_logic_op": "or",
            "explanation": "查询钛合金或铝合金"
        }
        intent = self.parser._build_intent(parsed, "钛合金或铝合金")

        self.assertEqual(intent.group_logic_op, LogicOp.OR)

    def test_build_intent_default_logic_op(self):
        """测试默认逻辑关系为 and"""
        parsed = {
            "groups": [
                {
                    "logic_op": "and",
                    "conditions": [
                        {"field": "tensile_strength", "operator": ">", "value": 400}
                    ],
                    "datasets": []
                }
            ],
            "explanation": "查询高强度钢"
        }
        intent = self.parser._build_intent(parsed, "高强度钢")

        self.assertEqual(intent.group_logic_op, LogicOp.AND)

    def test_build_sub_queries(self):
        """测试解析跨数据集查询（groups 中有多个元素）"""
        parsed = {
            "intent_type": "search",
            "group_logic_op": "and",
            "explanation": "查找泊松比小于4.0的材料样本和加载条件小于27.6的样本",
            "groups": [
                {
                    "logic_op": "and",
                    "conditions": [{"field": "poisson_ratio", "operator": "<", "value": 4.0}],
                    "datasets": ["特殊钢-物理性能-泊松比"]
                },
                {
                    "logic_op": "and",
                    "conditions": [{"field": "hardness", "operator": "<", "value": 27.6}],
                    "datasets": ["特殊钢-硬度"]
                }
            ]
        }
        intent = self.parser._build_intent(parsed, "查找泊松比小于4.0的材料样本和加载条件小于27.6的样本")

        self.assertEqual(intent.query_mode, "complex")
        self.assertEqual(len(intent.groups), 2)
        self.assertEqual(intent.groups[0].logic_op, "and")
        self.assertEqual(intent.groups[0].conditions[0].field, "poisson_ratio")
        # datasets 必须精确出现在原始查询中，测试查询不含这些数据集名，故为空
        self.assertEqual(intent.groups[0].datasets, [])
        self.assertEqual(intent.groups[1].logic_op, "and")
        self.assertEqual(intent.groups[1].conditions[0].field, "hardness")
        self.assertEqual(intent.groups[1].datasets, [])

    def test_build_sub_queries_empty_fallback(self):
        """测试 groups 为空列表时回退到简单查询"""
        parsed = {
            "intent_type": "search",
            "groups": [],
            "explanation": "查找钛合金数据"
        }
        intent = self.parser._build_intent(parsed, "查找钛合金数据")

        self.assertEqual(intent.query_mode, "simple")
        self.assertEqual(len(intent.groups), 1)
        self.assertEqual(intent.groups[0].logic_op, "and")
        self.assertEqual(intent.groups[0].datasets, ["钛合金数据"])

    def test_extract_datasets_exact_match(self):
        """测试数据集精确子串匹配"""
        query = "查找特殊钢-硬度数据"
        datasets = self.parser._extract_datasets(query)
        self.assertIn("特殊钢-硬度", datasets)

    def test_extract_datasets_no_normalized_match(self):
        """测试不完全匹配时返回空（已移除归一化匹配）"""
        query = "查找特殊钢硬度数据"
        datasets = self.parser._extract_datasets(query)
        # 归一化匹配已移除，缺少连字符不再命中
        self.assertNotIn("特殊钢-硬度", datasets)

    def test_extract_datasets_longest_preference(self):
        """测试数据集匹配优先保留最长匹配"""
        query = "查找特殊钢-硬度试验数据"
        datasets = self.parser._extract_datasets(query)
        self.assertIn("特殊钢-硬度试验", datasets)
        self.assertNotIn("特殊钢-硬度", datasets)

    def test_extract_datasets_no_match(self):
        """测试未提及数据集时返回空列表"""
        query = "查找抗拉强度大于500的材料"
        datasets = self.parser._extract_datasets(query)
        self.assertEqual(datasets, [])


class TestAggFunc(unittest.TestCase):
    """测试聚合运算（agg_func）"""

    def test_condition_with_agg_func_to_dict(self):
        """测试带聚合函数的条件序列化"""
        cond = Condition(
            field="tensile_strength",
            operator=Operator.EQ,
            value=0,
            agg_func="max"
        )
        result = cond.to_dict()
        self.assertEqual(result["field"], "tensile_strength")
        self.assertEqual(result["operator"], "=")
        self.assertEqual(result["value"], 0)
        self.assertEqual(result["agg_func"], "max")

    def test_condition_without_agg_func_to_dict(self):
        """测试不带聚合函数的条件序列化"""
        cond = Condition(
            field="density",
            operator=Operator.LT,
            value=5,
            unit="g/cm3"
        )
        result = cond.to_dict()
        self.assertIsNone(result["agg_func"])

    def test_build_intent_with_agg_func(self):
        """测试解析器识别聚合函数"""
        parser = IntentParser()
        parsed = {
            "intent_type": "search",
            "groups": [
                {
                    "logic_op": "and",
                    "conditions": [
                        {"field": "yield_strength", "operator": "=", "value": 0, "agg_func": "variance"}
                    ],
                    "datasets": []
                }
            ],
            "explanation": "查询钛合金屈服强度的方差"
        }
        intent = parser._build_intent(parsed, "查询钛合金屈服强度的方差")

        self.assertEqual(intent.query_mode, "simple")
        self.assertEqual(len(intent.groups), 1)
        self.assertEqual(intent.groups[0].logic_op, "and")
        self.assertEqual(intent.groups[0].conditions[0].field, "yield_strength")
        self.assertEqual(intent.groups[0].conditions[0].agg_func, "variance")

    def test_build_group_with_agg_func(self):
        """测试多 group 解析聚合函数"""
        parser = IntentParser()
        parsed = {
            "intent_type": "search",
            "group_logic_op": "and",
            "groups": [
                {
                    "logic_op": "and",
                    "conditions": [{"field": "tensile_strength", "operator": "=", "value": 0, "agg_func": "max"}],
                    "datasets": []
                },
                {
                    "logic_op": "and",
                    "conditions": [{"field": "density", "operator": "=", "value": 0, "agg_func": "min"}],
                    "datasets": []
                }
            ]
        }
        intent = parser._build_intent(parsed, "查询最大抗拉强度和最小密度")

        self.assertEqual(intent.query_mode, "complex")
        self.assertEqual(len(intent.groups), 2)
        self.assertEqual(intent.groups[0].logic_op, "and")
        self.assertEqual(intent.groups[0].conditions[0].agg_func, "max")
        self.assertEqual(intent.groups[1].logic_op, "and")
        self.assertEqual(intent.groups[1].conditions[0].agg_func, "min")


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestModels))
    suite.addTests(loader.loadTestsFromTestCase(TestIntentParserBuildIntent))
    suite.addTests(loader.loadTestsFromTestCase(TestAggFunc))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    run_tests()
