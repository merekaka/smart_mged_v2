# 材料数据集问答式智能检索系统 - 部署文档

> **GitHub 仓库**: https://github.com/merekaka/smart_mged_v2.git

## 1. 系统说明

本系统是基于 Django 的材料数据集问答式智能检索系统，提供专业知识问答、数据筛选、术语解释等功能。

**架构说明**：前端和后端合并在同一个 Django 项目中，前端页面由 Django 模板引擎渲染（HTML + CSS + JS），无需独立部署前端服务。部署一次即可同时运行前后端。

**工作原理**：浏览器访问页面 → Django 后端处理请求 → 调用阿里云百炼 LLM API 进行意图解析 → 查询 MySQL/SQLite 数据库 → 返回结果渲染到前端页面

部署后，系统开放 `http://<服务器IP>:5500`，其他系统可通过链接或按钮跳转访问。

| 组件 | 状态 | 说明 |
|------|------|------|
| 前端页面 | 需要部署 | Django 模板渲染，随后端一同部署 |
| Django 后端 | 需要部署 | 本仓库代码，需部署到服务器 |
| MySQL 数据库 | 需要部署 | 主数据库，存储业务数据 |
| SQLite 数据库 | 需要部署 | 缓存数据库，存储对话记录、查询缓存 |
| LLM API（阿里云百炼） | 已提供 | 无需自行部署，配置 API-Key 即可使用 |

## 2. 部署资源需求

| 项目 | 要求 |
|------|------|
| 操作系统 | Linux（Ubuntu 22.04）/ Windows Server（仅测试/演示） |
| Python | 3.10+（需安装 `python3.10-venv`、`python3.10-dev`、`python3-pip`） |
| MySQL | 9.6+ |
| 端口 | 5500（默认，可自定义） |
| 硬盘 | 约 2 GB，建议预留 100 GB+ |
| 内存 | 最低 8 GB，推荐 16 GB+ |
| CPU | 最低 4 核，推荐 8 核+ |
| 显卡 | 不需要（使用云端 LLM API） |
| 网络 | 需能访问阿里云百炼 API |

> **虚拟机建议**：仅部署本系统 → **8 vCPU / 16 GB / 100 GB 磁盘**；同机部署 MySQL + 本系统 → **8 vCPU / 16 GB / 200 GB 磁盘**

## 3. 部署步骤

### 3.1 上传文件并创建虚拟环境

将项目代码上传至服务器目标目录（如 `/opt/smart-mged`），解压后执行：

```bash
cd /opt/smart-mged
python3.10 -m venv .venv
source .venv/bin/activate                  # Linux
# .venv\Scripts\activate                   # Windows
pip install --upgrade pip
pip install -r requirements.txt

# 安装 MySQL 连接驱动（Linux 需额外安装系统依赖）
# Ubuntu/Debian：sudo apt install python3-dev default-libmysqlclient-dev build-essential
pip install mysqlclient
```

> ⚠️ Windows 上创建的 `.venv` 不能在 Linux 使用，需重新创建。

> 💡 **后续所有操作（数据库初始化、静态文件收集、启动服务等）均需在虚拟环境 `(.venv)` 激活状态下执行。** 若新开终端或重启服务器，请先执行：
> ```bash
> cd /opt/smart-mged
> source .venv/bin/activate   # Linux
> ```

### 3.2 配置环境变量（生产环境必须）

> ⚠️ **重要：代码中已移除所有真实的默认密码与 API-Key，改为占位符 `CHANGE_ME_IN_PRODUCTION`。部署后必须通过环境变量注入真实值，否则系统无法正常运行。**

`config/settings.py` 已集成 `python-dotenv`，启动时自动加载项目根目录的 `.env` 文件。因此推荐使用 `.env` 文件管理配置，无需手动 export。

**必须覆盖：**

| 变量名 | 默认值（占位符） | 操作 |
|--------|-----------------|------|
| `DJANGO_SECRET_KEY` | `django-insecure-change-me-in-production` | 生成随机密钥 |
| `DJANGO_DEBUG` | `True` | 设为 `False` |
| `ALLOWED_HOSTS` | `*` | 改为服务器 IP/域名 |
| `MYSQL_PASSWORD` | `CHANGE_ME_IN_PRODUCTION` | 改为 MySQL 密码 |
| `INTENT_CLOUD_API_KEY` | `CHANGE_ME_IN_PRODUCTION` | 改为百炼 API-Key |

**可选覆盖：** `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER`、`MYSQL_DATABASE`、`INTENT_MODE`、`INTENT_CLOUD_MODEL`

**设置方式（任选其一）：**

```bash
# 方式1（推荐）：使用 .env 文件
# 在项目根目录创建 .env 文件（已加入 .gitignore，不会提交到仓库）：
# .env
DJANGO_SECRET_KEY=<随机密钥>
DJANGO_DEBUG=False
ALLOWED_HOSTS=<服务器IP>,localhost
MYSQL_PASSWORD=<MySQL密码>
INTENT_CLOUD_API_KEY=<百炼 API-Key>

# 注意：.env 文件必须保存为 UTF-8 编码，否则 python-dotenv 读取会报错

# 方式2：启动前临时设置（测试用）
export DJANGO_SECRET_KEY="<随机密钥>"
export DJANGO_DEBUG="False"
export ALLOWED_HOSTS="<服务器IP>,localhost"
export MYSQL_PASSWORD="<MySQL密码>"
export INTENT_CLOUD_API_KEY="<百炼 API-Key>"

**生成密钥：**
```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

**获取百炼 API-Key：** [阿里云百炼控制台](https://bailian.console.aliyun.com/) → API-Key 管理

### 3.3 数据库初始化

**创建 MySQL 数据库：**
```bash
sudo mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS smart_mged CHARACTER SET utf8mb4;"
```

**导入业务数据和摘要：**
```bash
# 安装依赖
pip install mysql-connector-python

# 确保存在 smart_mged.sql 建表脚本后执行导入
# 若尚无该 SQL 文件，请联系项目管理员获取
python tools/run_execute_sql.py
```

> ⚠️ 主数据库表结构通过 SQL 脚本初始化，**请勿**运行 `python manage.py migrate --database=default`，以免覆盖数据。

**缓存数据库迁移：**
```bash
python manage.py migrate --database=cache_sqlite
```

### 3.4 收集静态文件

```bash
python manage.py collectstatic --noinput
```

### 3.5 启动服务

> 💡 启动前确保项目根目录存在 `.env` 文件（含 MySQL 密码、百炼 API-Key 等配置），`settings.py` 启动时会自动加载，无需手动 export 环境变量。

**Linux（Gunicorn）：**
```bash
pip install gunicorn
gunicorn config.wsgi:application -w 4 -b 0.0.0.0:5500 --timeout 120
```

**Windows（Waitress）：**
```powershell
pip install waitress
.venv\Scripts\python.exe -m waitress --listen=0.0.0.0:5500 --threads=4 config.wsgi:application
```

**Nginx 反向代理（Linux）：**

```nginx
server {
    listen 80;
    server_name <IP或域名>;
    client_max_body_size 20M;

    location /static/ {
        alias /opt/smart-mged/staticfiles/;
    }

    location / {
        proxy_pass http://127.0.0.1:5500;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        
        
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/smart-mged /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx
```

### 3.6 后台运行

创建 `/etc/systemd/system/smart-mged.service`：

**方式 A（推荐）：配合 .env 文件使用**
优点：环境变量集中管理，更新配置只需修改 `.env`，无需编辑 service 文件。

```ini
[Unit]
Description=Smart MGED Service
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/smart-mged
ExecStart=/opt/smart-mged/.venv/bin/gunicorn config.wsgi:application -w 4 -b 0.0.0.0:5500 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

> ⚠️ 使用此方式时，需确保 `/opt/smart-mged/.env` 文件存在且包含所有必要配置，且 `settings.py` 中已集成 `load_dotenv()`（已默认集成）。

**方式 B：在 service 文件中直接注入环境变量**
适用于不想创建 `.env` 文件的场景。创建 service 文件：

```ini
[Unit]
Description=Smart MGED Service
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/smart-mged
Environment="DJANGO_SECRET_KEY=<密钥>"
Environment="DJANGO_DEBUG=False"
Environment="ALLOWED_HOSTS=<IP或域名>"
Environment="MYSQL_PASSWORD=<密码>"
Environment="INTENT_CLOUD_API_KEY=<API-Key>"
ExecStart=/opt/smart-mged/.venv/bin/gunicorn config.wsgi:application -w 4 -b 0.0.0.0:5500 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

**注册并启动服务：**
```bash
sudo systemctl daemon-reload && sudo systemctl start smart-mged && sudo systemctl enable smart-mged
```

## 4. 验证部署

浏览器访问 `http://<服务器IP>:<端口>/`

| 测试项 | 操作 | 预期结果 |
|--------|------|---------|
| 页面加载 | 打开首页地址 | 显示智能检索系统首页，对话界面正常 |
| 意图解析 | 输入"查找所有屈服强度大于500MPa的数据" | 系统正确解析意图并返回筛选结果 |
| 多轮对话 | 先问"查找钛合金数据"，再问"其中强度最高的" | 系统保持上下文，正确理解后续问题 |

**外部系统集成（按钮跳转）：**

```html
<!-- 直接跳转 -->
<a href="http://<服务器IP>:<端口>/" target="_blank">
    <button>打开智能检索系统</button>
</a>

<!-- iframe 嵌入 -->
<iframe src="http://<服务器IP>:<端口>/" width="100%" height="800px"></iframe>
```

## 5. 长期运行

本系统部署后推荐保持持续运行，适合实验室环境下的不定期演示和日常使用。

### 5.1 资源消耗

系统在空闲状态下资源占用较少，长期运行不会对服务器造成显著负担：

| 项目 | 空闲时消耗 | 说明 |
|------|-----------|------|
| 内存 | 约 1.5 - 2 GB | 含 Django（4 个 worker）+ MySQL + 系统基础进程 |
| CPU | ≈ 0% | 仅等待 HTTP 请求，不占用 CPU |
| 磁盘 | 基本不变 | 对话缓存数据量很小，不会显著增长 |
| 网络 | 仅心跳连接 | 空闲时不调用百炼 API，不产生流量 |

> 相比让服务器空转，运行本系统增加的额外开销很小，可忽略不计。

### 5.2 日常管理

部署完成后（3.6 节），通过 systemd 进行管理：

```bash
# 查看运行状态
sudo systemctl status smart-mged

# 停止服务
sudo systemctl stop smart-mged

# 启动服务
sudo systemctl start smart-mged

# 重启服务（更新代码后）
sudo systemctl restart smart-mged

# 查看实时日志
sudo journalctl -u smart-mged -f

# 查看最近 100 条日志
sudo journalctl -u smart-mged -n 100
```

### 5.3 演示说明

- 只需在浏览器中访问 `http://<服务器 IP>:5500/` 即可使用，零等待。
- 系统调用的是云端百炼 API，本地无需 GPU，演示时即使连续问答也不会产生本地性能压力。
- 如果服务器关机后重新开机，服务会自动启动（已配置 `enable`）。

### 5.4 维护提醒

- 定期检查 `sudo journalctl -u smart-mged -n 50` 确认运行正常。
- 定期备份数据库（参见第 7 节）。
- 如发现响应变慢，可重启服务释放内存：`sudo systemctl restart smart-mged`。

## 6. 常见问题

| 问题 | 原因 | 排查 |
|------|------|------|
| 502 Bad Gateway | 后端未启动 | `systemctl status smart-mged` |
| 静态文件 404 | 未 collectstatic | `python manage.py collectstatic --noinput` |
| 意图超时 | API Key 无效 | 检查 `INTENT_CLOUD_API_KEY` 是否已正确配置 |
| MySQL 连不上 | 密码/权限错误 | `mysql -u smart_mged_user -p -e "USE smart_mged;"` |
| 对话功能异常 | 缓存数据库未迁移 | `python manage.py migrate --database=cache_sqlite` |
| `.env` 读取报错 `UnicodeDecodeError` | 文件编码不是 UTF-8 | 将 `.env` 重新保存为 UTF-8 编码（Windows 记事本另存为时可选择） |
| 启动后密码/API-Key 未生效 | `.env` 不存或格式错误 | 检查项目根目录是否存在 `.env`，以及 `=` 两边不要加空格 |

## 7. 安全加固（生产必做）

1. 修改所有默认密码（Django SECRET_KEY、MySQL）
2. `DJANGO_DEBUG = False`
3. `ALLOWED_HOSTS` 限制为实际域名/IP
4. 配置 HTTPS（Let's Encrypt）
5. 防火墙只开放 80/443，不直接暴露 5500 端口
6. 定期备份：MySQL（`mysqldump`）、SQLite（`cp query_cache.db`）

## 附录

### 环境变量完整清单

| 变量名 | 说明 | 默认值 | 生产必填 |
|--------|------|--------|---------|
| `DJANGO_SECRET_KEY` | Django 密钥 | `django-insecure-change-me-in-production` | **是** |
| `DJANGO_DEBUG` | 调试模式 | `True` | **是** |
| `ALLOWED_HOSTS` | 允许的主机 | `*` | **是** |
| `MYSQL_HOST` | MySQL 主机 | `127.0.0.1` | 否 |
| `MYSQL_PORT` | MySQL 端口 | `3306` | 否 |
| `MYSQL_USER` | MySQL 用户 | `root` | 否 |
| `MYSQL_PASSWORD` | MySQL 密码 | `CHANGE_ME_IN_PRODUCTION` | **是** |
| `MYSQL_DATABASE` | MySQL 数据库 | `smart_mged` | 否 |
| `INTENT_MODE` | LLM 模式 | `cloud` | 否 |
| `INTENT_CLOUD_API_KEY` | 百炼 API-Key | `CHANGE_ME_IN_PRODUCTION` | **是** |
| `INTENT_CLOUD_MODEL` | 意图解析模型 | `qwen3-32b` | 否 |

### API 路由

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 首页（对话页面） |
| `/api/intent/parse` | POST | 意图解析（自然语言 → 结构化查询条件） |
| `/api/intent/query_with_cache` | POST | 意图解析 + SQLite 缓存查询 |
| `/api/intent/health` | GET | 意图引擎健康检查 |
| `/api/chat/conversations` | GET/POST | 对话列表 / 创建新对话 |
| `/api/chat/conversations/<id>` | GET/DELETE | 对话详情 / 删除对话 |
| `/api/chat/conversations/empty` | POST | 创建空对话轮次 |
| `/api/chat/conversations/<id>/init` | POST | 对空对话执行首轮意图理解 |
| `/api/chat/conversations/<id>/messages` | POST | 在对话中继续问答 |
| `/api/chat/data_detail/<id>` | GET | 单条数据详情（弹窗用） |
| `/api/datasets/filter` | POST | 数据集筛选 |
| `/api/datasets/advanced` | POST | 数据集高级筛选 |
| `/api/datasets/full_rows` | GET | 获取数据集全量行数据 |
| `/api/terminology/term_explanation` | GET | 术语解释 |
