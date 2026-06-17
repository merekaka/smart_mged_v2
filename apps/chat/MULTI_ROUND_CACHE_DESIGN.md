# 多轮对话缓存存储结构设计

> 本文档描述 Chat / Follow-up / QueryCache 模块在 SQLite 中的物理表结构设计。
> 
> **数据库文件**：`cache_data/query_cache.db`  
> **Django 数据库路由**：`config.db_router.CacheRouter` 将所有 `chat` 与 `query_cache` app 的模型定向到 `cache_sqlite`（即上述 SQLite 文件）。

---

## 一、表清单概览

| 序号 | 表名 | Django 模型 | 职责 |
|------|------|-------------|------|
| 1 | `query_cache` | `apps.query_cache.models.QueryCache` | 结构化查询结果持久缓存 |
| 2 | `chat_conversation` | `apps.chat.models.Conversation` | 对话轮次（生命周期单元） |
| 3 | `chat_message` | `apps.chat.models.ChatMessage` | 单条消息（含每轮结果快照） |
| 4 | `chat_initial_result` | `apps.chat.models.InitialResult` | 首轮查询结果（长表，只写一次） |
| 5 | `chat_current_result` | `apps.chat.models.CurrentResult` | 最近一轮结果（长表，覆盖更新） |

---

## 二、逐表字段详解

### 2.1 `query_cache` — 结构化查询结果缓存表

**对应模型**：`apps.query_cache.models.QueryCache`

| 字段名 | Django 字段类型 | SQLite 近似类型 | 约束 / 属性 | 说明 |
|--------|----------------|-----------------|-------------|------|
| `id` | `BigAutoField` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `query_hash` | `CharField(max_length=64)` | VARCHAR(64) | UNIQUE, INDEX, NOT NULL | `structured_query` 的 SHA256 哈希 |
| `structured_query` | `JSONField` | TEXT | NOT NULL | 意图解析后的结构化查询条件（JSON 文本） |
| `results` | `JSONField` | TEXT | NOT NULL | MySQL 查询返回的宽表结果列表（JSON 文本） |
| `total` | `IntegerField` | INTEGER | DEFAULT 0 | 结果总数 |
| `sql_info` | `JSONField` | TEXT | DEFAULT '{}' | SQL 生成信息：sql, sql_params, sql_rendered, aggregation_sql 等 |
| `raw_answer` | `JSONField` | TEXT | DEFAULT '{}' | `intent_sql_executor` 返回的原始 answer |
| `hit_count` | `IntegerField` | INTEGER | DEFAULT 0 | 缓存命中次数 |
| `created_at` | `DateTimeField(auto_now_add=True)` | DATETIME | NOT NULL | 创建时间 |
| `updated_at` | `DateTimeField(auto_now=True)` | DATETIME | NOT NULL | 更新时间（用于 TTL 过期判断） |

**索引**：
```sql
-- 主键（Django 默认）
CREATE INDEX "query_cache_query_hash_xxx_idx" ON "query_cache" ("query_hash");
-- Meta.indexes 中声明
CREATE INDEX "query_cache_updated_at_xxx_idx" ON "query_cache" ("updated_at");
```

**生命周期**：
- 创建：首轮意图查询且缓存未命中时，由 `set_cached_results()` 写入。
- 读取：后续相同 `structured_query` 直接命中，无需再查 MySQL。
- 淘汰：TTL 7 天，`get_cached_results()` 中通过 `updated_at` 检测过期并自动删除。

---

### 2.2 `chat_conversation` — 对话轮次表

**对应模型**：`apps.chat.models.Conversation`

| 字段名 | Django 字段类型 | SQLite 近似类型 | 约束 / 属性 | 说明 |
|--------|----------------|-----------------|-------------|------|
| `id` | `BigAutoField` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `title` | `CharField(max_length=200)` | VARCHAR(200) | NOT NULL | 自动取用户问题前 N 字做标题 |
| `query_hash` | `CharField(max_length=64)` | VARCHAR(64) | NULL, INDEX | 冗余存储 QueryCache 的 query_hash，便于缓存被清理后追溯 |
| `query_cache_entry_id` | `ForeignKey` | INTEGER | NULL, FK → `query_cache(id)` | 外键关联到 query_cache 表（`on_delete=models.SET_NULL`） |
| `structured_query` | `JSONField` | TEXT | DEFAULT '{}' | 意图解析后的结构化查询条件 |
| `created_at` | `DateTimeField(auto_now_add=True)` | DATETIME | NOT NULL | 创建时间 |
| `updated_at` | `DateTimeField(auto_now=True)` | DATETIME | NOT NULL | 最后更新时间（对话列表按此字段倒序） |

**Meta 配置**：
- `db_table = "chat_conversation"`
- `ordering = ["-updated_at"]`

**关联关系**：
- 一对多 → `chat_message`（`related_name="messages"`，级联删除）
- 一对多 → `chat_initial_result`（`related_name="initial_results"`，级联删除）
- 一对多 → `chat_current_result`（`related_name="current_results"`，级联删除）
- 多对一 → `query_cache`（`query_cache_entry_id`，`SET_NULL`）

---

### 2.3 `chat_message` — 消息表

**对应模型**：`apps.chat.models.ChatMessage`

| 字段名 | Django 字段类型 | SQLite 近似类型 | 约束 / 属性 | 说明 |
|--------|----------------|-----------------|-------------|------|
| `id` | `BigAutoField` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `conversation_id` | `ForeignKey` | INTEGER | NOT NULL, FK → `chat_conversation(id)` | 所属对话轮次（`on_delete=models.CASCADE`） |
| `role` | `CharField(max_length=20)` | VARCHAR(20) | NOT NULL | 角色枚举：`user` / `assistant` |
| `message_type` | `CharField(max_length=20)` | VARCHAR(20) | NOT NULL | 消息类型枚举：`intent_query` / `follow_up` / `search_record` |
| `content` | `TextField` | TEXT | NOT NULL | 消息文本内容 |
| `meta` | `JSONField` | TEXT | DEFAULT '{}' | **核心缓存字段**：每轮结果的 JSON 快照 |
| `created_at` | `DateTimeField(auto_now_add=True)` | DATETIME | NOT NULL | 创建时间（消息列表按此字段正序） |

**Meta 配置**：
- `db_table = "chat_message"`
- `ordering = ["created_at"]`

**`meta` 字段典型结构（Assistant 消息）**：
```json
{
  "results": [{"data_id": 1, "title": "Ti-6Al-4V", "density": 4.43}],
  "total": 5,
  "sql": "SELECT * FROM round_results WHERE \"density\" < ?",
  "params": [5],
  "intent": {"intent_type": "search", "conditions1": [...]},
  "classified_results": [...],
  "analysis_result": {...},
  "chart_data": {...},
  "is_statistical_analysis": false
}
```

**多轮递进机制**：
第 N 轮 follow-up 执行前，读取最近一条 `role='assistant'` 且 `message_type` 为 `intent_query` 或 `follow_up` 的记录的 `meta.results`，作为第 N+1 轮的输入数据集。

---

### 2.4 `chat_initial_result` — 首轮结果表（初表）

**对应模型**：`apps.chat.models.InitialResult`

| 字段名 | Django 字段类型 | SQLite 近似类型 | 约束 / 属性 | 说明 |
|--------|----------------|-----------------|-------------|------|
| `id` | `BigAutoField` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `conversation_id` | `ForeignKey` | INTEGER | NOT NULL, FK → `chat_conversation(id)` | 所属对话轮次（`on_delete=models.CASCADE`） |
| `data_id` | `BigIntegerField` | INTEGER | NOT NULL | 实体 ID；同一 `data_id` 的多行属于同一条数据 |
| `title` | `CharField(max_length=255)` | VARCHAR(255) | DEFAULT '' | 数据集 / 样品标题 |
| `property_name` | `CharField(max_length=255)` | VARCHAR(255) | NOT NULL | 属性英文名称（原始名，不加前缀） |
| `bitmap_role` | `CharField(max_length=64)` | VARCHAR(64) | DEFAULT '' | 属性类别枚举：`object` / `operate` / `result` |
| `value_text` | `TextField` | TEXT | NULL | 属性值（统一以字符串存储） |
| `created_at` | `DateTimeField(auto_now_add=True)` | DATETIME | NOT NULL | 创建时间 |

**Meta 配置**：
- `db_table = "chat_initial_result"`

**自定义索引**：
```sql
CREATE INDEX "chat_initial_result_conversation_id_data_id_xxx_idx"
    ON "chat_initial_result" ("conversation_id", "data_id");
CREATE INDEX "chat_initial_result_conversation_id_property_name_xxx_idx"
    ON "chat_initial_result" ("conversation_id", "property_name");
```

**特点**：
- 每个 `conversation_id` 只写入一次，**永不更新**。
- 长表格式：一条实体的一个属性占一行。
- 用途：① 构建 `property_name → bitmap_role` 映射；② 支持 `scope="original"` 的回溯查询。

---

### 2.5 `chat_current_result` — 当前结果表（当前表）

**对应模型**：`apps.chat.models.CurrentResult`

| 字段名 | Django 字段类型 | SQLite 近似类型 | 约束 / 属性 | 说明 |
|--------|----------------|-----------------|-------------|------|
| `id` | `BigAutoField` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `conversation_id` | `ForeignKey` | INTEGER | NOT NULL, FK → `chat_conversation(id)` | 所属对话轮次（`on_delete=models.CASCADE`） |
| `seq` | `PositiveIntegerField` | INTEGER UNSIGNED | DEFAULT 1 | 产生该结果的问答轮次序号 |
| `data_id` | `BigIntegerField` | INTEGER | NOT NULL | 实体 ID |
| `title` | `CharField(max_length=255)` | VARCHAR(255) | DEFAULT '' | 数据集 / 样品标题 |
| `property_name` | `CharField(max_length=255)` | VARCHAR(255) | NOT NULL | 属性英文名称（原始名，不加前缀） |
| `bitmap_role` | `CharField(max_length=64)` | VARCHAR(64) | DEFAULT '' | 属性类别枚举：`object` / `operate` / `result` |
| `value_text` | `TextField` | TEXT | NULL | 属性值（统一以字符串存储） |
| `created_at` | `DateTimeField(auto_now_add=True)` | DATETIME | NOT NULL | 创建时间 |

**Meta 配置**：
- `db_table = "chat_current_result"`

**自定义索引**：
```sql
CREATE INDEX "chat_current_result_conversation_id_data_id_xxx_idx"
    ON "chat_current_result" ("conversation_id", "data_id");
```

**特点**：
- 每次 follow-up 后**先删除该 `conversation_id` 的全部旧数据，再插入新数据**（覆盖更新）。
- `seq` 递增，用于追踪历史轮次。
- 仅保留最近一轮结果，是 follow-up SQL 执行前的主要数据来源。

---

## 三、表关系 E-R 图

```
┌─────────────────────┐         ┌─────────────────────┐
│    query_cache      │◄────────┤  chat_conversation  │
├─────────────────────┤  SET_NULL├─────────────────────┤
│ id (PK)             │         │ id (PK)             │
│ query_hash (UQ)     │         │ title               │
│ structured_query    │         │ query_hash           │
│ results             │         │ query_cache_entry_id │─FK──┐
│ total               │         │ structured_query    │     │
│ sql_info            │         │ created_at          │     │
│ raw_answer          │         │ updated_at          │     │
│ hit_count           │         └──────────┬──────────┘     │
│ created_at          │                    │                │
│ updated_at          │       ┌────────────┼────────────┐   │
└─────────────────────┘       │            │            │   │
                              ▼            ▼            ▼   │
                    ┌─────────────┐ ┌─────────────┐ ┌───────┴───┐
                    │ chat_message│ │chat_initial_│ │chat_current│
                    │             │ │   result    │ │  result    │
                    ├─────────────┤ ├─────────────┤ ├───────────┤
                    │ id (PK)     │ │ id (PK)     │ │ id (PK)   │
                    │conversation_│ │conversation_│ │conversation_│
                    │  id (FK)    │ │  id (FK)    │ │  id (FK)  │
                    │ role        │ │ data_id     │ │ seq       │
                    │message_type │ │ title       │ │ data_id   │
                    │ content     │ │property_name│ │ title     │
                    │ meta        │ │bitmap_role  │ │property_name│
                    │ created_at  │ │ value_text  │ │bitmap_role│
                    └─────────────┘ │ created_at  │ │ value_text│
                                    └─────────────┘ │ created_at│
                                                    └───────────┘
```

---

## 四、长表 ↔ 宽表格式说明

`chat_initial_result` 与 `chat_current_result` 采用**长表（long format）**存储，便于 ORM 存取和属性级检索。

**长表示例**：

| conversation_id | data_id | title | property_name | bitmap_role | value_text |
|-----------------|---------|-------|---------------|-------------|------------|
| 1 | 101 | 钛合金1 | tensile_strength | result | 500 |
| 1 | 101 | 钛合金1 | material_name | object | Ti-6Al-4V |
| 1 | 102 | 钛合金2 | tensile_strength | result | 600 |

执行 follow-up SQL 前，通过 `ResultStore.long_to_wide()` 转置为**宽表（wide format）**：

| data_id | title | tensile_strength | material_name |
|---------|-------|------------------|---------------|
| 101 | 钛合金1 | 500 | Ti-6Al-4V |
| 102 | 钛合金2 | 600 | NULL |

---

## 五、关键操作与 SQL 映射

| 业务操作 | 涉及的表 | 操作类型 |
|---------|---------|---------|
| 首轮查询命中缓存 | `query_cache` | SELECT |
| 首轮查询未命中，写入缓存 | `query_cache` | INSERT / UPDATE |
| 创建对话 | `chat_conversation`, `chat_message` | INSERT |
| 保存首轮结果 | `chat_initial_result`, `chat_current_result` | INSERT |
| 执行 follow-up | `chat_current_result`（读取） | SELECT |
| follow-up 后覆盖当前结果 | `chat_current_result` | DELETE + INSERT |
| 追加对话消息 | `chat_message` | INSERT |
| 删除单个对话 | 全部 `chat_*` 表 | CASCADE DELETE |
| 清空全部对话 | 全部 `chat_*` 表 | DELETE + 重置 `sqlite_sequence` |
| 缓存过期清理 | `query_cache` | DELETE（按 `updated_at`） |

---

## 六、存储配置

```python
# config/settings.py
DATABASES = {
    'default': { ... },  # MySQL
    'cache_sqlite': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'cache_data' / 'query_cache.db',
    }
}

DATABASE_ROUTERS = ['config.db_router.CacheRouter']
```

所有上述五张表均位于同一个 SQLite 文件 `cache_data/query_cache.db` 中，由 `CacheRouter` 统一路由。
