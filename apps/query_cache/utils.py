import logging
from typing import Optional, Dict, Any, List

from django.utils import timezone
from datetime import timedelta

from apps.query_cache.models import QueryCache

logger = logging.getLogger(__name__)

# 缓存有效期，默认 7 天
CACHE_TTL_HOURS = 7 * 24


def get_cached_results(query_key: dict) -> Optional[Dict[str, Any]]:
    """
    根据 query_key（通常为 intent.to_dict()）查缓存。
    命中则更新 hit_count 并返回结果；未命中返回 None。
    """
    query_hash = QueryCache.make_hash(query_key)

    try:
        cache_entry = QueryCache.objects.get(query_hash=query_hash)
    except QueryCache.DoesNotExist:
        return None

    # TTL 检查：过期则删除
    expire_at = cache_entry.updated_at + timedelta(hours=CACHE_TTL_HOURS)
    if timezone.now() > expire_at:
        cache_entry.delete()
        logger.info(f"Cache expired for hash {query_hash[:8]}, deleted.")
        return None

    # 命中
    cache_entry.hit_count += 1
    cache_entry.save(update_fields=['hit_count'])

    logger.info(f"Cache hit for hash {query_hash[:8]}, total_hits={cache_entry.hit_count}")
    return {
        "from_cache": True,
        "structured_query": cache_entry.structured_query,
        "results": cache_entry.results,
        "total": cache_entry.total,
        "sql_info": cache_entry.sql_info,
        "raw_answer": cache_entry.raw_answer,
    }


def set_cached_results(
    query_key: dict,
    results: List[Dict],
    total: int = None,
    sql_info: Optional[Dict[str, Any]] = None,
    raw_answer: Optional[Dict[str, Any]] = None,
) -> QueryCache:
    """
    将 MySQL 查询结果及 SQL 信息写入 SQLite 缓存。
    """
    query_hash = QueryCache.make_hash(query_key)
    total = total if total is not None else len(results)

    defaults = {
        'structured_query': query_key,
        'results': results,
        'total': total,
        'hit_count': 0,
    }
    if sql_info is not None:
        defaults['sql_info'] = sql_info
    if raw_answer is not None:
        defaults['raw_answer'] = raw_answer

    cache_entry, created = QueryCache.objects.update_or_create(
        query_hash=query_hash,
        defaults=defaults
    )

    action = "created" if created else "updated"
    logger.info(f"Cache {action} for hash {query_hash[:8]}, results_count={total}")
    return cache_entry
