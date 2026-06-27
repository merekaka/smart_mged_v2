# 材料数据集问答式智能检索系统

> neo4j 4.4.30 ； 
> elasticsearch 8.17.2 ； 
> python 3.10.11
> mysql 9.6.0；

## 数据详情弹窗（原始 JSON 展示）

点击对话界面结果表格中的 `data_id` 链接，会弹出数据详情弹窗。弹窗展示的是 **`data/` 目录下原始 JSON 文件中的未处理数据**（而非 MySQL 中处理后的数据）。

### 对应关系

- 前端 `data_id` = 原始数据中的 `_meta_id`
- `data/` 目录下 40 个 JSON 文件的文件名 = 前端中的 `title` 字段（数据集名称）

### 原始数据索引构建

首次使用或 `data/` 目录下数据有更新时，需要重新构建索引：

```bash
python tools/build_raw_data_index.py
```

索引文件默认保存至 `data/raw_data_index.json`，包含所有 `_meta_id` 到 `(文件路径, 数组索引)` 的映射。

### 弹窗展示内容

弹窗以 JSON 格式展示原始数据，包含：
- **元信息**：`_meta_id`、`_id`、`_tid`
- **原始数据**：完整的 `data` 字段（包括嵌套数组、对象结构等），以格式化 JSON 代码块展示

---

## 聚合查询展示说明

系统支持三种聚合查询的差异化展示：

| 查询类型 | 数据展示 | 平均值展示 |
|---------|---------|-----------|
| **max / min** | 展示最值对应的**单条**数据 | 不显示 |
| **avg** | 展示所有参与计算的**全部**数据 | 在"查询概览"下方显示"聚合结果"栏，展示平均值 |
| **普通查询** | 展示匹配的数据 | 不显示 |

---

## 项目结构

```
smart-mged/
├── manage.py                        ← Django 入口
├── requirements.txt                 ← 统一依赖（含 Django）
│
├── config/                          ← 项目配置
│   ├── settings.py                  ← 所有配置项（路径、数据库、LLM…）
│   ├── urls.py                      ← 顶层路由（汇聚各 app 路由）
│   ├── wsgi.py
│   └── asgi.py
│
├── core/                            ← 跨 app 共享业务层
│   ├── model_loader.py              ← get_model() / get_data() 单例
│   ├── inverted_index.py            ← InvertedIndex 类 + get_inverted_index()
│   ├── data_utils.py                ← get_processed_data / format_results / build_citations…
│   └── answer_generator.py          ← LLM 生成式回答 / 抽取式兜底
│
├── utils/                           ← 工具模块
│   ├── ac_terminology_matcher.py    ← 术语匹配器
│   ├── tag_config.py                ← 标签配置
│   └── prompt_template.py           ← 提示词模板
│
├── apps/                            ← Django 应用
│   ├── search/                      ← 检索功能
│   ├── knowledge_graph/             ← 知识图谱（已注释）
│   ├── terminology/                 ← 术语解释
│   ├── chat/                        ← 对话管理
│   ├── datasets/                    ← 数据集筛选
│   ├── query_cache/                 ← 查询缓存
│   ├── follow_up/                   ← 多轮问答
│   └── intent_engine/               ← 意图理解引擎
│
├── templates/                       ← Django 模板
│   └── frontend/
│       └── intent_chat.html         ← 意图理解对话页面
│
├── static/                          ← Django 静态文件
│   └── frontend/
│       ├── intent_chat.js
│       └── style.css
│
├── tools/                           ← 工具脚本
│   ├── build_raw_data_index.py      ← 构建原始数据索引
│   ├── build_graph_vocab_cache.py   ← 构建图谱词汇缓存
│   ├── build_inverted_index.py      ← 构建倒排索引
│   ├── create_faiss_index.py        ← 创建 FAISS 索引
│   ├── test_intent_engine.py        ← 意图引擎测试
│   └── test_intent_query.py         ← 意图查询测试
│
├── data/                            ← 原始数据
├── tfidf_results/                   ← TF-IDF 预计算结果
├── vector_database/                 ← FAISS 索引
├── llm/                             ← 本地模型权重
└── szl/                             ← SQL 查询执行模块
```

## API 路由

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/search/query` | POST | 向量搜索 |
| `/api/search/health` | GET | 检索服务健康检查 |
| `/api/search/models` | GET | 获取可用模型列表 |
| `/api/search/index_info` | GET | 索引信息 |
| `/api/search/query_keywords` | POST | 关键词查询 |
| `/api/graph/kgqa` | POST | 知识图谱问答 |
| `/api/graph/health` | GET | 图谱服务健康检查 |
| `/api/terminology/term_explanation` | GET | 术语解释 |
| `/api/chat/conversations` | GET/POST | 对话列表 / 创建对话 |
| `/api/chat/conversations/<id>` | GET/DELETE | 对话详情 / 删除对话 |
| `/api/chat/conversations/<id>/messages` | POST | 发送消息 |
| `/api/datasets/filter` | POST | 数据集筛选 |
| `/api/datasets/full_rows` | POST | 获取完整行数据 |
| `/api/datasets/advanced` | POST | 高级数据集查询 |
| `/api/intent/parse` | POST | 意图解析 |
| `/api/intent/query_with_cache` | POST | 意图解析 + 缓存查询 |
| `/api/intent/health` | GET | 意图引擎健康检查 |

## 启动方式

### 前置准备

确保已安装项目依赖（含 `python-dotenv`，用于自动加载 `.env` 配置）：

```bash
pip install -r requirements.txt
```

> `.env` 文件已在项目根目录创建完毕，其中包含了 MySQL 密码和百炼 API-Key 等配置。`settings.py` 启动时会自动读取，无需手动设置环境变量。

### 开发环境（本地调试）

```bash
# 方式1（推荐）：激活虚拟环境后使用 manage.py
# Windows (CMD / PowerShell)
.venv\Scripts\activate
python manage.py runserver 0.0.0.0:5500

# Windows (Git Bash / WSL / MSYS2)
source .venv/Scripts/activate
python manage.py runserver 0.0.0.0:5500

# Linux / macOS
source .venv/bin/activate
python manage.py runserver 0.0.0.0:5500
```

```bash
# 方式2：直接指定虚拟环境 Python 解释器（不激活环境，适用于脚本/自动化）
# Windows
.venv\Scripts\python.exe manage.py runserver 0.0.0.0:5500

# Linux / macOS
.venv/bin/python manage.py runserver 0.0.0.0:5500
```

> **推荐方式**：先激活虚拟环境，再运行 `python manage.py runserver`。`settings.py` 会自动加载项目根目录的 `.env` 文件，无需手动 export 环境变量。

### 访问意图理解对话界面

```
http://127.0.0.1:5500/
```

### 依赖服务启动

```bash
# 启动 Elasticsearch
cd C:\ES\elasticsearch-8.17.2\bin
.\elasticsearch.bat

# 启动 Neo4j（如需使用知识图谱功能）
neo4j console
```

## 测试

```bash
# 意图理解引擎测试
python tools/test_intent_engine.py
```

## 百炼平台账号

请联系项目管理员获取账号信息。

## API Key

通过环境变量 `INTENT_CLOUD_API_KEY` 配置，详见部署文档。系统不再在代码中硬编码 API-Key。

## 环境变量

| 变量名 | 说明 | 默认值 |
|---|---|---|
| `DJANGO_SECRET_KEY` | Django 密钥 | django-insecure-change-me-in-production |
| `DJANGO_DEBUG` | 调试模式 | True |
| `ALLOWED_HOSTS` | 允许的主机 | * |
| `MYSQL_HOST` | MySQL 主机 | 127.0.0.1 |
| `MYSQL_PORT` | MySQL 端口 | 3306 |
| `MYSQL_USER` | MySQL 用户 | root |
| `MYSQL_PASSWORD` | MySQL 密码 | CHANGE_ME_IN_PRODUCTION |
| `MYSQL_DATABASE` | MySQL 数据库 | smart_mged |
| `INTENT_MODE` | 意图模式 (cloud/local) | cloud |
| `INTENT_CLOUD_API_KEY` | 云端 LLM API Key | - |
| `INTENT_CLOUD_MODEL` | 云端模型 | qwen3-32b |
| `NEO4J_URL` | Neo4j 地址 | bolt://localhost:7687 |
| `NEO4J_USER` | Neo4j 用户 | neo4j |
| `NEO4J_PASSWORD` | Neo4j 密码 | CHANGE_ME_IN_PRODUCTION |

## 数据文件与索引

| 路径 | 说明 |
|---|---|
| `data/*.json` | 40 个原始数据集 JSON 文件 |
| `data/raw_data_index.json` | `_meta_id` 索引文件（由 `tools/build_raw_data_index.py` 生成）|

## 批处理测试命令

```powershell
$env:INTENT_CLOUD_MODEL="deepseek-v4-flash"
python szl/test/batch_intent_sql_eval.py `
    --sql-out szl/test/results_deepseek-v4-flash/generated_sql_from_intent.txt `
    --result-out szl/test/results_deepseek-v4-flash/query_results_and_recall.txt `
    --intent-out szl/test/results_deepseek-v4-flash/intent_dict_results.txt
```
