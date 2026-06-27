"""
Django settings for graduate_project.

Material/Law retrieval system using FAISS + Inverted Index + Neo4j + ElasticSearch.
[修改说明：知识图谱功能已注释]
"""
import os
import warnings
from pathlib import Path

# ---------------------------------------------------------------------------
# 加载 .env 文件（本地开发环境）
# ---------------------------------------------------------------------------
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Base directories
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # graduate_project/

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-change-me-in-production')

DEBUG = os.getenv('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')

# ---------------------------------------------------------------------------
# Installed apps
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    # third-party
    'corsheaders',
    # project apps
    'apps.search',
    # [已注释 - 知识图谱功能]
    # 'apps.knowledge_graph',
    'apps.terminology',
    'apps.chat',
    'apps.follow_up',
    'apps.datasets',
    # 新增：查询缓存（独立出来供多模块复用）
    'apps.query_cache',
    # 新增：意图理解引擎
    'apps.intent_engine',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ---------------------------------------------------------------------------
# Database (MySQL)
# ---------------------------------------------------------------------------
MYSQL_HOST = os.environ.get('MYSQL_HOST', '127.0.0.1')
MYSQL_PORT = int(os.environ.get('MYSQL_PORT', '3306'))
MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', 'CHANGE_ME_IN_PRODUCTION')
MYSQL_DATABASE = os.environ.get('MYSQL_DATABASE', 'smart_mged')

# 安全警告：如果检测到使用默认密码，提醒用户在生产环境中修改
if MYSQL_PASSWORD == 'CHANGE_ME_IN_PRODUCTION':
    warnings.warn(
        "正在使用默认数据库密码，请在生产环境中通过环境变量 MYSQL_PASSWORD 设置安全密码",
        RuntimeWarning,
        stacklevel=2,
    )

DATABASES = {
    'default': {
        'ENGINE': os.environ.get('MYSQL_ENGINE', 'django.db.backends.mysql'),
        'NAME': MYSQL_DATABASE,
        'USER': MYSQL_USER,
        'PASSWORD': MYSQL_PASSWORD,
        'HOST': MYSQL_HOST,
        'PORT': MYSQL_PORT,
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    },
    'cache_sqlite': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'cache_data' / 'query_cache.db',
    }
}

DATABASE_ROUTERS = ['config.db_router.CacheRouter']

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# Whitenoise 静态文件配置
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ---------------------------------------------------------------------------
# Static & Media
# ---------------------------------------------------------------------------
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# CORS (django-cors-headers)
# ---------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = True

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s - %(levelname)s - %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}

# ---------------------------------------------------------------------------
# Application-specific settings
# ---------------------------------------------------------------------------

# Paths (relative to BASE_DIR)
DATA_DIR = BASE_DIR / 'data'
TFIDF_RESULTS_DIR = BASE_DIR / 'tfidf_results'
VECTOR_DATABASE_DIR = BASE_DIR / 'vector_database'
LLM_DIR = BASE_DIR / 'llm'
SZL_DIR = BASE_DIR / 'szl'

# SQLite 缓存目录
CACHE_DATA_DIR = BASE_DIR / 'cache_data'

# ========================================================================
# 意图理解引擎 - LLM 调用配置
# ========================================================================
# 切换开关: "local" 使用本地 Ollama; "cloud" 使用云端 API (百炼/DeepSeek 等)
# 实验室环境建议通过环境变量 INTENT_MODE=cloud 启用百炼 API
INTENT_MODE = os.getenv('INTENT_MODE', 'cloud')

# 本地 Ollama 配置
INTENT_LOCAL_API_BASE = os.getenv('INTENT_LOCAL_API_BASE', 'http://localhost:11434/v1')
INTENT_LOCAL_MODEL = os.getenv('INTENT_LOCAL_MODEL', 'qwen3:1.7b')
INTENT_LOCAL_API_KEY = os.getenv('INTENT_LOCAL_API_KEY', 'ollama')  # Ollama 不验证 key

# 云端 API 配置（阿里云百炼平台）
# 子账号需在百炼控制台创建 API-Key，并确保拥有 AliyunBailianFullAccess 权限
INTENT_CLOUD_API_BASE = os.getenv('INTENT_CLOUD_API_BASE', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
INTENT_CLOUD_MODEL = os.getenv('INTENT_CLOUD_MODEL', 'qwen3-32b')
INTENT_CLOUD_API_KEY = os.getenv('INTENT_CLOUD_API_KEY', 'CHANGE_ME_IN_PRODUCTION')

# 向后兼容旧的 DEEPSEEK_* 变量
DEEPSEEK_API_BASE = INTENT_LOCAL_API_BASE
DEEPSEEK_MODEL = INTENT_LOCAL_MODEL
DEEPSEEK_API_KEY = INTENT_LOCAL_API_KEY

# [知识图谱 Neo4j 配置]
NEO4J_URL = os.getenv('NEO4J_URL', 'bolt://localhost:7687')
NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', 'CHANGE_ME_IN_PRODUCTION')

# 知识图谱问答 (KGQA) LLM 配置
KGQA_LLM_API_BASE = os.getenv('KGQA_LLM_API_BASE', INTENT_CLOUD_API_BASE)
KGQA_LLM_API_KEY = os.getenv('KGQA_LLM_API_KEY', INTENT_CLOUD_API_KEY)
KGQA_LLM_MODEL = os.getenv('KGQA_LLM_MODEL', 'qwen-max')

# Embedding models
MODEL_CONFIGS = {
    "m3e-base": {
        "path": str(LLM_DIR / "m3e-base"),
        "max_seq_length": 300,
        "trust_remote_code": False,
    },
    "m3e-large": {
        "path": str(LLM_DIR / "m3e-large"),
        "max_seq_length": 300,
        "trust_remote_code": False,
    },
    "UniME-Phi3.5-V-4.2B": {
        "path": str(LLM_DIR / "UniME-Phi3.5-V-4.2B"),
        "max_seq_length": 512,
        "trust_remote_code": True,
    },
    # 添加 bge-m3
    "bge-m3": {
        "path": str(LLM_DIR / "bge-m3"),
        "max_seq_length": 8192,
        "trust_remote_code": True,
    },
}
