import hashlib
import json
from django.db import models


class QueryCache(models.Model):
    """
    结构化查询结果缓存表（存储在 SQLite 中）
    """
    query_hash = models.CharField(max_length=64, unique=True, db_index=True, help_text="structured_query 的 SHA256")
    structured_query = models.JSONField(help_text="原始结构化查询条件")
    results = models.JSONField(help_text="MySQL 查询结果列表")
    total = models.IntegerField(default=0, help_text="结果总数")
    sql_info = models.JSONField(default=dict, blank=True, help_text="SQL 生成信息（sql, sql_params, sql_rendered, aggregation_sql 等）")
    raw_answer = models.JSONField(default=dict, blank=True, help_text="intent_sql_executor 返回的原始 answer（matched_data_ids, aggregations 等）")
    hit_count = models.IntegerField(default=0, help_text="命中次数")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'query_cache'
        db_table = 'query_cache'
        indexes = [
            models.Index(fields=['updated_at']),
        ]

    def __str__(self):
        return f"Cache[{self.query_hash[:8]}] hits={self.hit_count}"

    @classmethod
    def make_hash(cls, structured_query: dict) -> str:
        """对 structured_query 做稳定哈希，保证相同查询条件生成相同 hash"""
        canonical = json.dumps(structured_query, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
