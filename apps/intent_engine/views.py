"""
意图理解引擎 - API视图
只负责将自然语言转换为 Intent 对象
"""
import json
import logging

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .parser import IntentParser
from apps.query_cache.utils import get_cached_results, set_cached_results

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class IntentParseView(View):
    """
    POST /api/intent/parse
    
    将自然语言转换为 Intent 对象
    
    请求体:
    {
        "query": "查找抗拉强度大于500MPa的钛合金材料"
    }
    
    响应:
    {
        "success": true,
        "data": {
            "original_query": "查找抗拉强度大于500MPa的钛合金材料",
            "parsed_intent": { ... }
        }
    }
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.parser = IntentParser()
    
    def post(self, request):
        """
        处理流程:
            1. 解析请求体获取用户查询字符串
            2. 调用 parser.parse() 生成 Intent 对象
            3. 返回 parsed_intent
        """
        try:
            body = json.loads(request.body or '{}')
            user_query = body.get("query", "").strip()
            
            if not user_query:
                logger.warning("IntentParseView: empty query received")
                return JsonResponse({
                    "success": False,
                    "error": "查询内容不能为空"
                }, status=400)
            
            logger.info(f"IntentParseView: parsing query={user_query[:100]!r}")
            # 生成 Intent 对象
            intent = self.parser.parse(user_query)
            if not intent:
                logger.warning(f"IntentParseView: intent parsing failed for query={user_query[:100]!r}")
                return JsonResponse({
                    "success": False,
                    "error": "意图解析失败"
                }, status=500)
            
            intent_dict = intent.to_dict()
            logger.info(f"IntentParseView: intent parsed successfully, query_mode={intent_dict.get('query_mode')}, "
                        f"groups={len(intent_dict.get('groups', []))}")
            return JsonResponse({
                "success": True,
                "data": {
                    "original_query": user_query,
                    "parsed_intent": intent_dict
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                "success": False,
                "error": "请求体格式错误"
            }, status=400)
        except Exception as e:
            logger.error(f"IntentParseView 错误: {e}", exc_info=True)
            return JsonResponse({
                "success": False,
                "error": f"服务器错误: {str(e)}"
            }, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class IntentQueryWithCacheView(View):
    """
    POST /api/intent/query_with_cache
    
    统一入口：意图解析 → 查 SQLite 缓存 →（未命中）→ 调后端查 MySQL → 写缓存 → 返回
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.parser = IntentParser()

    def post(self, request):
        """
        处理流程:
            1. 调用 parser.parse() 生成 Intent 对象
            2. 以 intent.to_dict() 为 key 查 SQLite 缓存
            3. 缓存命中 → 直接返回; 未命中 → 调后端查 MySQL → 写入缓存 → 返回
        """
        try:
            body = json.loads(request.body or '{}')
            user_query = body.get("query", "").strip()

            if not user_query:
                logger.warning("IntentQueryWithCacheView: empty query received")
                return JsonResponse({
                    "success": False,
                    "error": "查询内容不能为空"
                }, status=400)

            logger.info(f"IntentQueryWithCacheView: query={user_query[:100]!r}")
            # 1) 意图解析 → 生成 Intent 对象
            intent = self.parser.parse(user_query)
            if not intent:
                logger.warning(f"IntentQueryWithCacheView: intent parsing failed for query={user_query[:100]!r}")
                return JsonResponse({
                    "success": False,
                    "error": "意图解析失败"
                }, status=500)

            intent_dict = intent.to_dict()
            logger.info(f"IntentQueryWithCacheView: intent parsed, mode={intent_dict.get('query_mode')}")

            # 2) 查 SQLite 缓存
            cached = get_cached_results(intent_dict)
            if cached:
                logger.info(f"IntentQueryWithCacheView: cache hit, total={cached.get('total', 0)}")
                return JsonResponse({
                    "success": True,
                    "data": {
                        "original_query": user_query,
                        "parsed_intent": intent_dict,
                        "from_cache": True,
                        "results": cached["results"],
                        "total": cached["total"],
                    }
                })

            logger.info("IntentQueryWithCacheView: cache miss, fetching from backend")
            # 3) 未命中：调后端接口（当前为 mock 数据，等后端同学完成后替换）
            results, total = self._fetch_from_backend_with_details(intent_dict, user_query)
            logger.info(f"IntentQueryWithCacheView: backend returned total={total}")

            # 4) 写入 SQLite 缓存
            set_cached_results(intent_dict, results, total)

            return JsonResponse({
                "success": True,
                "data": {
                    "original_query": user_query,
                    "parsed_intent": intent_dict,
                    "from_cache": False,
                    "results": results,
                    "total": total,
                }
            })

        except json.JSONDecodeError:
            return JsonResponse({
                "success": False,
                "error": "请求体格式错误"
            }, status=400)
        except Exception as e:
            logger.error(f"IntentQueryWithCacheView 错误: {e}", exc_info=True)
            return JsonResponse({
                "success": False,
                "error": f"服务器错误: {str(e)}"
            }, status=500)

    def _fetch_from_backend(self, intent_dict: dict, original_query: str):
        """
        调用 szl/intent_sql_executor.py 执行真实的数据库查询。
        返回 data_id 列表和总数（executor 原生行为，保持纯粹）。
        """
        from szl.intent_sql_executor import run_from_intent
        try:
            result = run_from_intent(intent_dict, original_query=original_query)
            data_ids = result.get("answer", {}).get("matched_data_ids", [])
            total = result.get("answer", {}).get("total", 0)
            results = [{"data_id": did} for did in data_ids]
            return results, total
        except Exception as e:
            logger.error(f"数据库查询失败: {e}", exc_info=True)
            return [], 0

    def _fetch_from_backend_with_details(self, intent_dict: dict, original_query: str):
        """
        查询后端并自动回填完整实体详情（宽表记录）。
        新增包装函数，对原有 _fetch_from_backend 做加法。
        """
        from apps.chat.backend_client import fetch_results_with_details
        return fetch_results_with_details(intent_dict, original_query=original_query)


class HealthView(View):
    """GET /api/intent/health"""
    
    def get(self, request):
        from django.conf import settings
        api_key = getattr(settings, 'DEEPSEEK_API_KEY', None)
        
        return JsonResponse({
            "status": "healthy",
            "service": "intent_engine",
            "llm_configured": bool(api_key),
            "version": "1.4.0-intent-only"
        })
