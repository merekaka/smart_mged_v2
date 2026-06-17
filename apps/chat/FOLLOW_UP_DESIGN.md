# Chat 模块 Follow-up 查询设计方案（V2 — 多轮递进版）

## 一、需求澄清与核心变化

用户明确 follow-up 需要支持：
1. **进一步查询**：在已有结果上添加更多条件
2. **多轮递进**：每一轮的新结果成为下一轮的输入，而非始终基于首轮初步结果
3. **生成图表**：对任意一轮结果生成图表（先分析可行性）
4. **缓存每一轮结果**

**关键变化**：上一版方案中，所有 follow-up 都在"首轮初步结果"上执行 SQL；本版改为**在"上一轮得到的新结果"上执行**，形成真正的递进式多轮对话。

---

## 二、总体架构

```
首轮查询（全库）
    │
    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  IntentParser│────▶│ 后端数据库   │────▶│  QueryCache │  ← 初步结果 R0
│  + 全库查询  │     │  (MySQL等)   │     │  （持久缓存） │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                                │
         ┌──────────────────────────────────────┘
         │
         ▼
   Conversation 创建
   ├─ UserMsg: "查找钛合金"
   └─ AssistantMsg: meta={results: R0, total: 100}

第 1 轮 Follow-up
    │
    ▼
┌──────────────────────────────────────────────┐
│ 1. 取上一轮结果：last_assistant_msg.meta.results │  ← R0（100条）
│ 2. IntentParser.parse("密度小于5的")            │
│ 3. ResultStore(R0) + SQL Builder + 执行         │
│ 4. 得到新结果 R1（20条）                        │
│ 5. 创建 UserMsg + AssistantMsg                 │
│    AssistantMsg.meta = {results: R1, total: 20} │
└──────────────────────────────────────────────┘

第 2 轮 Follow-up
    │
    ▼
┌──────────────────────────────────────────────┐
│ 1. 取上一轮结果：last_assistant_msg.meta.results │  ← R1（20条）
│ 2. IntentParser.parse("其中弹性模量最大的")     │
│ 3. ResultStore(R1) + SQL Builder + 执行         │
│ 4. 得到新结果 R2（1条）                         │
│ 5. 创建 UserMsg + AssistantMsg                 │
│    AssistantMsg.meta = {results: R2, total: 1}  │
└──────────────────────────────────────────────┘
```

**核心设计**：每轮 Assistant 消息的 `meta` 字段成为"结果快照"，下一轮自动读取最近一条 Assistant 消息的 `meta.results` 作为输入数据集。

---

## 三、数据流与状态管理

### 3.1 结果集的获取优先级（`get_current_results`）

当需要执行新一轮 follow-up 时，按以下优先级获取"当前有效结果集"：

```python
def get_current_results(conversation) -> List[Dict]:
    """
    1. 优先：最近一条 Assistant 消息的 meta.results（多轮递进）
    2. 次选：Conversation 关联的 QueryCache.results（首轮缓存）
    3. 兜底：structured_query 反查缓存
    4. 最终：空列表
    """
    # 优先级 1：最近一轮 follow-up / intent_query 的 assistant 消息
    last_assistant = conversation.messages.filter(
        role=ChatMessage.Role.ASSISTANT,
        message_type__in=[ChatMessage.Type.INTENT_QUERY, ChatMessage.Type.FOLLOW_UP]
    ).order_by('-created_at').first()
    
    if last_assistant and last_assistant.meta.get('results'):
        return last_assistant.meta['results']
    
    # 优先级 2：首轮 query_cache
    if conversation.query_cache_entry:
        return conversation.query_cache_entry.results
    
    # 优先级 3：用 structured_query 反查
    if conversation.structured_query:
        cached = get_cached_results(conversation.structured_query)
        if cached:
            return cached['results']
    
    # 优先级 4：空
    return []
```

### 3.2 无需改模型

现有模型已足够支持：

- `ChatMessage.meta` 是 `JSONField(default=dict)`，可直接存储每轮的 `results` / `total` / `sql` / `intent`
- `Conversation.query_cache_entry` 继续承担"首轮结果持久缓存"职责

**结论：不需要新增模型，不需要 Django 迁移。**

---

## 四、新增/修改文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `chat/result_store.py` | 新增 | 内存 SQLite 临时表，将 JSON 结果集动态映射为可 SQL 查询的表 |
| `chat/sql_builder.py` | 新增 | Intent → SQL 转换器（支持过滤、聚合、多条件 AND/OR/NOT） |
| `chat/follow_up_engine.py` | 新增 | Follow-up 查询编排引擎（整合"取上一轮结果→意图解析→SQL生成→执行→格式化"） |
| `chat/services.py` | 修改 | 新增 `get_current_results()`；扩展 `add_follow_up_message` 支持传入 meta；替换占位回答逻辑 |
| `chat/views.py` | 修改 | `MessageCreateView.post()` 接入真实 follow-up 查询 |

---

## 五、详细设计

### 5.1 ResultStore —— 结果暂存层

将任意 JSON 列表（初步结果或某轮结果）加载到内存 SQLite：

```python
import sqlite3
from typing import List, Dict

class ResultStore:
    TABLE_NAME = "round_results"

    def __init__(self, results: List[Dict]):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        if results:
            self._create_table(results)
            self._insert_data(results)

    def _create_table(self, results: List[Dict]):
        """动态建表：扫描所有 key，推断类型 INTEGER / REAL / TEXT"""
        schema = {}
        for row in results:
            for k, v in row.items():
                if k not in schema:
                    schema[k] = self._infer_type(v)
        cols = [f'"{k}" {t}' for k, t in schema.items()]
        sql = f"CREATE TABLE {self.TABLE_NAME} ({', '.join(cols)})"
        self.conn.execute(sql)

    def _infer_type(self, v) -> str:
        if isinstance(v, bool): return "INTEGER"
        if isinstance(v, int): return "INTEGER"
        if isinstance(v, float): return "REAL"
        return "TEXT"

    def _insert_data(self, results: List[Dict]):
        if not results: return
        keys = list(results[0].keys())
        placeholders = ", ".join(["?"] * len(keys))
        sql = f'INSERT INTO {self.TABLE_NAME} ("{"\", \"".join(keys)}") VALUES ({placeholders})'
        for row in results:
            self.conn.execute(sql, [row.get(k) for k in keys])
        self.conn.commit()

    def query(self, sql: str, params=()) -> List[Dict]:
        cursor = self.conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def close(self):
        self.conn.close()
```

### 5.2 IntentSQLBuilder —— 意图转 SQL

输入为 `Intent.to_dict()`，输出为 `(sql, params)`。

**条件格式说明**：
`Intent.conditions1` 的格式为 `[logic_op_str, Condition, Condition, ...]`，其中 `Condition` 是 dict：
```json
{"field": "density", "operator": "<", "value": 5, "unit": "g/cm3", "agg_func": null}
```

**转换规则**：

| 场景 | Intent 条件示例 | 生成 SQL |
|------|----------------|---------|
| 单条件过滤 | `{"field":"density", "operator":"<", "value":5}` | `SELECT * FROM round_results WHERE "density" < 5` |
| 多条件 AND | 两个 Condition + logic_op "and" | `WHERE "a" > 1 AND "b" < 2` |
| 多条件 OR | 两个 Condition + logic_op "or" | `WHERE "a" > 1 OR "b" < 2` |
| 聚合 MAX | `{"field":"elastic_modulus", "operator":"=", "value":0, "agg_func":"max"}` | `SELECT * FROM round_results WHERE "elastic_modulus" = (SELECT MAX("elastic_modulus") FROM round_results)` |
| 聚合 AVG | `{"field":"hardness", "agg_func":"avg"}` | `SELECT AVG("hardness") FROM round_results` |
| 混合：过滤 + 聚合 | 一个普通条件 + 一个 max 条件 | 先 WHERE 过滤，再在子集中求 MAX |

**聚合查询返回策略（用户需确认）**：
- **策略 A**：只返回聚合值 → `SELECT MAX(field) FROM ...`
- **策略 B（推荐）**：返回使聚合成立的完整记录 → `SELECT * FROM ... WHERE field = (SELECT MAX(field) FROM ...)`

> 建议采用 **策略 B**，因为用户问"弹性模量最大的材料"时，期望看到的是材料完整信息，而非单纯一个数值。

### 5.3 FollowUpQueryEngine —— 查询编排引擎

```python
class FollowUpQueryEngine:
    def __init__(self):
        self.parser = IntentParser()

    def query(self, user_text: str, current_results: List[Dict]) -> Dict:
        """
        完整流程：
        1. 意图解析
        2. 加载当前结果集到内存 SQLite
        3. 生成 SQL
        4. 执行
        5. 格式化回答
        """
        if not current_results:
            return {"error": "当前没有可查询的结果集", "results": [], "total": 0}

        # 1. 意图解析
        intent = self.parser.parse(user_text)
        if not intent:
            return {"error": "意图解析失败", "results": [], "total": 0}
        
        intent_dict = intent.to_dict()

        # 2. 加载结果
        store = ResultStore(current_results)
        try:
            # 3. 生成 SQL
            builder = IntentSQLBuilder(intent_dict)
            sql, params = builder.build()

            # 4. 执行
            rows = store.query(sql, params)

            # 5. 格式化
            answer = self._format_answer(rows, intent_dict)

            return {
                "answer": answer,
                "sql": sql,
                "params": params,
                "results": rows,
                "total": len(rows),
                "intent": intent_dict,
            }
        finally:
            store.close()

    def _format_answer(self, rows: List[Dict], intent: Dict) -> str:
        total = len(rows)
        if total == 0:
            return "在当前结果中未找到符合条件的数据。"
        
        # 简单格式化：说明数量和前几条标题
        titles = [r.get("title", r.get("id", "未命名")) for r in rows[:3]]
        title_str = "、".join(titles)
        suffix = f"等共 {total} 条结果" if total > 3 else f"共 {total} 条结果"
        return f"在当前结果中筛选出：{title_str}{suffix}。"
```

### 5.4 与现有代码衔接

**`chat/services.py` 修改**：

```python
def process_follow_up(conversation_id: int, user_text: str) -> Dict:
    """
    处理一轮 follow-up 查询，返回结果并创建消息记录。
    """
    conv = Conversation.objects.select_related("query_cache_entry").get(pk=conversation_id)
    
    # 获取当前有效结果集（上一轮结果 或 首轮缓存）
    current_results = get_current_results(conv)
    
    # 执行查询
    engine = FollowUpQueryEngine()
    result = engine.query(user_text, current_results)
    
    # 创建消息（meta 中缓存本轮结果，供下一轮使用）
    assistant_meta = {
        "results": result.get("results", []),
        "total": result.get("total", 0),
        "sql": result.get("sql"),
        "intent": result.get("intent"),
    }
    
    msg_result = add_follow_up_message(
        conversation_id=conversation_id,
        user_content=user_text,
        assistant_content=result.get("answer", ""),
        assistant_meta=assistant_meta,
    )
    
    return {
        "user_message_id": msg_result["user_message_id"],
        "assistant_message_id": msg_result["assistant_message_id"],
        "answer": result.get("answer"),
        **{k: v for k, v in result.items() if k != "answer"},
    }
```

**`chat/views.py` 修改**：

`MessageCreateView.post()` 中替换占位逻辑：
```python
# 旧：返回占位回答
# assistant_content = self._generate_placeholder_answer(...)

# 新：执行真实 follow-up 查询
from .services import process_follow_up
result = process_follow_up(int(conversation_id), user_content)

return JsonResponse({
    "success": True,
    "data": {
        "user_message_id": result["user_message_id"],
        "assistant_message_id": result["assistant_message_id"],
        "answer": result["answer"],
        "sql": result.get("sql"),
        "total": result.get("total", 0),
        "results": result.get("results", []),
    },
})
```

---

## 六、接口定义

### 6.1 创建对话（首轮）—— 保持不变

`POST /api/chat/conversations`
```json
{ "query": "查找抗拉强度大于500MPa的钛合金" }
```

### 6.2 Follow-up 查询（多轮递进）—— 升级

`POST /api/chat/conversations/<id>/messages`
```json
{ "content": "密度小于5的" }
```

**响应示例**：
```json
{
  "success": true,
  "data": {
    "user_message_id": 3,
    "assistant_message_id": 4,
    "answer": "在当前结果中筛选出：Ti-6Al-4V、纯钛等共 5 条结果。",
    "sql": "SELECT * FROM round_results WHERE \"density\" < ?",
    "params": [5],
    "total": 5,
    "results": [
      {"id": "mock_001", "title": "Ti-6Al-4V", "density": 4.43, ...},
      {"id": "mock_002", "title": "纯钛", "density": 4.51, ...}
    ],
    "intent": {
      "intent_type": "search",
      "conditions1": ["and", {"field": "density", "operator": "<", "value": 5, "agg_func": null}],
      ...
    }
  }
}
```

**关键：每一轮返回的 `results` 会成为下一轮的输入。**

---

## 七、图表生成可行性分析

### 7.1 可行性结论：**完全可行，前端即可实现，后端无需改动**

理由：
- 每一轮的结果都是标准 JSON 数组 `List[Dict]`
- 数组中的每个字典就是一条数据记录，字段名即 key
- 前端拿到后即可用 ECharts/Chart.js/Plotly 等库直接渲染

### 7.2 可支持的图表类型

| 图表类型 | 所需数据 | 实现方式 | 可行性 |
|---------|---------|---------|--------|
| **柱状图** | 分类字段 + 数值字段 | X 轴：材料名，Y 轴：属性值 | ✅ 高 |
| **折线图** | 有序分类 + 数值字段 | 按某字段排序后绘制 | ✅ 高 |
| **散点图** | 两个数值字段 | X/Y 轴各一个属性，观察相关性 | ✅ 高 |
| **饼图/环形图** | 分类型字段 | 统计各分类占比（如晶体结构分布） | ✅ 高 |
| **箱线图** | 数值字段 | 展示数据分布（最小值、Q1、中位数、Q3、最大值） | ✅ 中（需前端计算统计量） |
| **热力图** | 多属性矩阵 | 多材料 × 多属性的数值矩阵 | ✅ 中 |
| **雷达图** | 单条记录的多维属性 | 展示某材料的综合性能画像 | ✅ 高 |

### 7.3 前端实现建议

```javascript
// 示例：用户选择"柱状图"，前端用 ECharts 渲染当前轮次 results
const chartData = currentResults.map(r => ({
    name: r.title || r.id,
    value: r.tensile_strength  // 用户选择的数值字段
}));

// ECharts option
option = {
    xAxis: { type: 'category', data: chartData.map(d => d.name) },
    yAxis: { type: 'value', name: '抗拉强度 (MPa)' },
    series: [{ type: 'bar', data: chartData.map(d => d.value) }]
};
```

**无需后端参与的原因**：图表是纯数据可视化，数据已在 `results` 中。前端只需：
1. 让用户选择图表类型（下拉菜单）
2. 让用户选择映射字段（X轴、Y轴、分类等）
3. 调用 ECharts API 渲染

> 若后续需要后端做复杂统计（如回归分析、聚类），再扩展接口即可。当前阶段前端自治足够。

---

## 八、待确认问题（精简版）

1. **聚合查询返回策略**：
   - **B（推荐）**：返回使聚合成立的**完整记录**（如"TC4 的弹性模量最大，为 120 GPa"）
   - 是否认可？

2. **字段名一致性**：
   - Intent 的 `field`（如 `tensile_strength`）与 results 中 JSON 的 key 是否同名？
   - 如果不同（如 results 里是 `"抗拉强度"` 或 `"Tensile Strength"`），需要增加 `RESULT_FIELD_MAPPING`。

3. **回答文本生成**：
   - 当前方案中回答文本是后端生成的简单描述（如"共找到 5 条结果"）
   - 是否需要接入 LLM 生成更自然的回答？还是保持规则化文本？
   - **建议 V1 用规则化文本，V2 接入 LLM。**

---

## 九、实现工作量评估

| 模块 | 预计代码量 | 复杂度 |
|------|-----------|--------|
| `result_store.py` | ~80 行 | 低 |
| `sql_builder.py` | ~150 行 | 中（需处理聚合、多条件、字段安全） |
| `follow_up_engine.py` | ~100 行 | 中 |
| `services.py` 改造 | ~60 行 | 低 |
| `views.py` 改造 | ~30 行 | 低 |
| **合计** | **~420 行** | **中低** |

**关键优势**：无需改模型、无需迁移、不依赖外部库（纯 sqlite3 标准库）。
