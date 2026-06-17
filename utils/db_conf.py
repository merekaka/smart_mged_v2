"""
统一的数据库配置获取入口，消除多处重复定义和硬编码密码。

所有需要直接连接 MySQL 的模块都应从此处导入 get_mysql_conf()，
而不是各自定义 _get_db_conf() / get_db_conf()。
"""

import os
from typing import Dict, Any

from pymysql.cursors import DictCursor


def get_mysql_conf() -> Dict[str, Any]:
    """
    获取 MySQL 连接配置。

    优先级：
        1. Django settings.DATABASES['default']（如果 Django 已初始化）
        2. 环境变量（MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE）

    注意：默认密码为空字符串，强制要求通过环境变量或 Django settings 配置，
    避免硬编码密码带来的安全隐患。
    """
    try:
        from django.conf import settings
        db = settings.DATABASES["default"]
        return {
            "host": db.get("HOST") or "127.0.0.1",
            "port": int(db.get("PORT") or "3306"),
            "user": db.get("USER") or "root",
            "password": db.get("PASSWORD") or "",
            "database": db.get("NAME") or "smart_mged",
            "charset": db.get("OPTIONS", {}).get("charset", "utf8mb4"),
            "cursorclass": DictCursor,
        }
    except Exception:
        return {
            "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
            "port": int(os.getenv("MYSQL_PORT", "3306")),
            "user": os.getenv("MYSQL_USER", "root"),
            "password": os.getenv("MYSQL_PASSWORD", ""),
            "database": os.getenv("MYSQL_DATABASE", "smart_mged"),
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
        }
