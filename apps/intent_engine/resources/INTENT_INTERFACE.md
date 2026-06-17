# Intent 接口说明

本文档描述意图理解引擎（`apps.intent_engine`）对外输出的 `Intent` 接口格式，供下游 SQL 生成模块消费。

---

## 一、获取 Intent

### 方式 1：Python 直接调用

```python
from apps.intent_engine import parse_intent

intent = parse_intent("材料泊松比小于4.0的样本有哪些？")
intent_dict = intent.to_dict()
```

### 方式 2：HTTP API

```http
POST /api/intent/parse
Content-Type: application/json

{"query": "材料泊松比小于4.0的样本有哪些？"}
```

响应中的 `data.parsed_intent` 即为 `intent_dict`。

---

## 二、Intent 字典结构

```json
{
    "intent_type": "search",
    "groups": [
        {
            "logic_op": "and",
            "conditions": [
                {
                    "field": "poisson_ratio",
                    "operator": "<",
                    "value": 4.0,
                    "unit": null,
                    "agg_func": null
                }
            ],
            "datasets": []
        }
    ],
    "group_logic_op": "and",
    "target_properties": [],
    "sort_by": null,
    "explanation": "材料泊松比小于4.0的样本有哪些？",
    "query_mode": "simple"
}
```

---

## 三、核心字段说明

### `groups`（查询条件组数组）

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `logic_op` | `str` | 组内条件逻辑关系：`and` / `or` / `not` |
| `conditions` | `List[dict]` | 查询条件列表，每个条件针对一个字段 |
| `datasets` | `List[str]` | 该组对应的数据集名称（如 `"钛合金数据"`） |

- **简单查询**：`groups` 中只有 1 个元素
- **复杂查询（跨数据集）**：`groups` 中有 2 个及以上元素

### `conditions`（条件项）

| 字段 | 类型 | 说明 |
|------|------|------|
| `field` | `str` | 属性字段名，如 `poisson_ratio`、`tensile_strength` |
| `operator` | `str` | 比较运算符：`=`、`>`、`<`、`>=`、`<=` |
| `value` | `str / int / float` | 比较值 |
| `unit` | `str / null` | 单位，如 `"MPa"`、`"g/cm3"` |
| `agg_func` | `str / null` | 聚合函数：`max`、`min`、`avg`、`variance`、`sum`、`count`；为 `null` 时表示普通条件查询 |

### 其他字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `intent_type` | `str` | `search`（检索）或 `compare`（对比） |
| `group_logic_op` | `str` | 多组之间的逻辑关系：`and` / `or` / `not` |
| `target_properties` | `List[str]` | 用户明确想查看的属性字段名列表 |
| `sort_by` | `dict / null` | 排序规则，如 `{"field": "tensile_strength", "order": "desc"}` |
| `explanation` | `str` | 查询意图的文字说明 |
| `query_mode` | `str` | `simple`（单组）或 `complex`（多组跨数据集） |

---

## 四、遍历示例

```python
intent_dict = intent.to_dict()

for group in intent_dict["groups"]:
    logic_op = group["logic_op"]           # "and"
    conditions = group["conditions"]       # [{"field": "poisson_ratio", "operator": "<", "value": 4.0, ...}]
    datasets = group["datasets"]           # ["钛合金数据"]

    for cond in conditions:
        field = cond["field"]              # "poisson_ratio"
        operator = cond["operator"]        # "<"
        value = cond["value"]              # 4.0
        agg_func = cond["agg_func"]        # null
```

---

## 五、生成 SQL 的要点

1. **`datasets`** → 对应 `result` 表的 `title` 字段，用于 `WHERE title IN (...)`
2. **`conditions`** → 每个条件对应 `result` 表的 `property_name` + `value_text`
   - `property_name = field`
   - `value_text` 是字符串存储的数值，提取数字部分后与 `value` 比较
3. **`target_properties`** → 限制返回的 `property_name` 范围
4. **`sort_by`** → SQL 的 `ORDER BY` 子句
6. **多 `group`** → 每个 `group` 独立生成 SQL 查询，最终按 `group_logic_op` 对 `data_id` 做交集/并集
