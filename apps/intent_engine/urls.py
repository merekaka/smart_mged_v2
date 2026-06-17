"""
意图理解引擎 - URL路由
只提供意图解析接口，将自然语言转换为结构化查询条件
"""
from django.urls import path

from .views import IntentParseView, HealthView, IntentQueryWithCacheView

urlpatterns = [
    path('parse', IntentParseView.as_view(), name='intent-parse'),               # 仅意图理解
    path('query_with_cache', IntentQueryWithCacheView.as_view(), name='intent-query-with-cache'),  # 意图理解 + SQLite 缓存
    path('health', HealthView.as_view(), name='intent-health'),                  # 健康检查
]
