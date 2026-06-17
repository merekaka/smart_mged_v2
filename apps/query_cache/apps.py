from django.apps import AppConfig


class QueryCacheConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.query_cache'
    verbose_name = '查询缓存'
