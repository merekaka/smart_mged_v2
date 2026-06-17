"""
apps/search/views.py
--------------------
Django views corresponding to the Flask routes:
  POST /api/query           → QueryView (仅支持向量搜索)
  GET  /api/health          → HealthView
  GET  /api/models          → ModelsView
  GET  /api/index_info      → IndexInfoView
  POST /api/query_keywords  → QueryKeywordsView
[修改说明：QueryView 仅支持向量搜索，精确搜索和混合搜索已注释]
"""
import logging

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from core.model_loader import get_model, get_data, _current_model
from core.inverted_index import get_inverted_index
from core.data_utils import format_results, build_citations
from core.answer_generator import generate_answer, extractive_fallback
from django.conf import settings

from .services import vector_search

import json
import time

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class QueryView(View):
    """POST /api/search/query - 仅支持向量搜索"""

    def post(self, request):
        try:
            body = json.loads(request.body)
            query_text    = body.get("query")
            # [修改：忽略search_mode参数，强制使用向量搜索]
            # search_mode   = body.get("search_mode", "hybrid")
            search_mode   = "vector"  # 强制使用向量搜索
            model_name    = body.get("model", "m3e-base")
            topk          = int(body.get("topk", 20))
            # [修改：忽略hybrid_weight参数]
            # hybrid_weight = float(body.get("hybrid_weight", 0.5))
            abstract_mode = body.get("abstract_mode", "own")
            session_id    = body.get("session_id")
            max_citations = int(body.get("max_citations", 5))

            logger.info(f"Query: {query_text} | mode={search_mode} | model={model_name}")

            if not query_text:
                return JsonResponse({"error": "Query is required"}, status=400)

            # -- 仅执行向量搜索 --
            faiss_index, abstract_ids, abstracts = get_data(model_name, abstract_mode)
            if faiss_index is None:
                return JsonResponse({"error": "Failed to load vector index"}, status=500)
            results, timing = vector_search(
                query_text, faiss_index, get_model(model_name),
                abstracts, abstract_ids, k=topk,
            )
            formatted = format_results(results, search_mode)
            response_data = {"results": formatted, "timing": timing}

            # [已注释 - 精确搜索]
            # elif search_mode == "exact":
            #     results = exact_search(query_text, abstract_mode=abstract_mode, topk=topk)
            #     formatted = format_results(results, search_mode)
            #     response_data = {"results": formatted}

            # [已注释 - 混合搜索]
            # else:  # hybrid
            #     results, timing = hybrid_search(
            #         query_text, model_name=model_name, topk=topk,
            #         abstract_mode=abstract_mode, hybrid_weight=hybrid_weight,
            #     )
            #     formatted = format_results(results, search_mode)
            #     response_data = {"results": formatted, "timing": timing}

            # -- Generate answer --
            try:
                citations = build_citations(results, search_mode, max_citations)
                answer_text = generate_answer(query_text, citations)
                response_data["answer"] = answer_text
            except Exception as gen_e:
                logger.error(f"生成回答失败，使用抽取式回退: {gen_e}")
                try:
                    citations = build_citations(results, search_mode, max_citations)
                    response_data["answer"] = extractive_fallback(citations)
                except Exception:
                    citations = []
                    response_data["answer"] = ""

            response_data["citations"] = [
                {"index": c["index"], "id": c["id"], "title": c["title"], "score": c.get("score")}
                for c in citations
            ]

            # -- Persist session --
            if session_id:
                from apps.chat.services import save_search_record
                conv = save_search_record(session_id, query_text, response_data)
                response_data["session_id"] = session_id
                response_data["conversation_id"] = conv.id

            return JsonResponse(response_data)

        except Exception as e:
            logger.error(f"QueryView error: {e}", exc_info=True)
            return JsonResponse({"error": str(e)}, status=500)


class HealthView(View):
    """GET /api/search/health"""

    def get(self, request):
        return JsonResponse({"status": "healthy"})


class ModelsView(View):
    """GET /api/search/models"""

    def get(self, request):
        return JsonResponse({
            "models": list(settings.MODEL_CONFIGS.keys()),
            "current_model": _current_model,
        })


class IndexInfoView(View):
    """GET /api/search/index_info"""

    def get(self, request):
        try:
            idx = get_inverted_index()
            return JsonResponse(idx.get_index_info())
        except Exception as e:
            logger.error(f"IndexInfoView error: {e}")
            return JsonResponse({"error": str(e)}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class QueryKeywordsView(View):
    """POST /api/search/query_keywords"""

    def post(self, request):
        try:
            body = json.loads(request.body)
            query_text = body.get("query", "")
            idx = get_inverted_index()
            keywords = idx.extract_keywords(query_text)
            keyword_matches = idx.get_keyword_matches(keywords)
            return JsonResponse({
                "query": query_text,
                "extracted_keywords": keywords,
                "keyword_matches": keyword_matches,
            })
        except Exception as e:
            logger.error(f"QueryKeywordsView error: {e}")
            return JsonResponse({"error": str(e)}, status=500)
