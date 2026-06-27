"""
apps/chat/views.py
-------------------
对话轮次管理中心 API

  POST   /api/chat/conversations             → 创建新对话（含意图解析+查缓存+结果返回）
  GET    /api/chat/conversations             → 获取对话列表摘要
  GET    /api/chat/conversations/<id>       → 获取某轮对话详情及消息流
  DELETE /api/chat/conversations/<id>       → 删除某轮对话
  POST   /api/chat/conversations/<id>/messages  → 在对话中追加后续问答
"""
import json
import logging

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.query_cache.models import QueryCache
from apps.query_cache.utils import get_cached_results, set_cached_results
from .models import Conversation, ChatMessage, InitialResult
from .services import (
    create_conversation,
    add_follow_up_message,
    get_conversation_detail,
    list_conversations,
    delete_conversation,
    delete_all_conversations,
    get_result_context,
    build_result_summary,
    create_empty_conversation,
)
from .backend_client import fetch_full_result
from .result_fetcher import to_classified_format, fetch_result_details
from .element_composition import build_element_composition
from .raw_data_loader import load_raw_data_by_meta_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内部辅助：对已有 conversation 执行首轮意图理解初始化
# ---------------------------------------------------------------------------

def _execute_intent_init(conv: Conversation, user_query: str):
    """
    对指定空 conversation 执行意图解析、缓存查询、结果持久化和消息创建。
    返回 (data_dict, error_msg)。
    """
    from apps.intent_engine import parse_intent
    intent = parse_intent(user_query)
    if not intent:
        logger.warning(f"_execute_intent_init: intent parsing failed for query={user_query[:100]!r}")
        return None, "意图解析失败"

    intent_dict = intent.to_dict()
    logger.info(f"_execute_intent_init: intent parsed, mode={intent_dict.get('query_mode')}, groups={len(intent_dict.get('groups', []))}")

    # 查 SQLite 缓存
    query_hash = QueryCache.make_hash(intent_dict)
    cached = get_cached_results(intent_dict)
    classified_results = []
    sql_info = {}
    if cached:
        results = cached["results"]
        total = cached["total"]
        from_cache = True
        qce = QueryCache.objects.get(query_hash=query_hash)
        data_ids = [r.get("data_id") for r in results if r.get("data_id")]
        if data_ids:
            from .result_fetcher import fetch_result_details
            classified_results = fetch_result_details(data_ids)
        # 从缓存中恢复 sql_info
        sql_info = cached.get("sql_info") or {}
    else:
        # 未命中：调后端 → 获取完整 result（含 SQL）→ 写入缓存
        full_result = fetch_full_result(intent_dict, user_query)
        answer = full_result.get("answer", {})
        results = answer.get("records", [])
        classified_results = answer.get("classified_records", [])
        data_ids = answer.get("matched_data_ids", [])

        if not results and data_ids:
            results = [{"data_id": did} for did in data_ids]

        if data_ids and not classified_results:
            from .result_fetcher import fetch_result_details
            classified_results = fetch_result_details(data_ids)

        total = answer.get("total", 0)

        sql_info = {
            "sql": full_result.get("sql"),
            "sql_params": full_result.get("sql_params", []),
            "sql_rendered": full_result.get("sql_rendered"),
        }
        if full_result.get("query_mode") == "complex":
            sql_info["group_sql"] = full_result.get("group_sql", [])
            sql_info["final_sql"] = full_result.get("final_sql")
            sql_info["final_sql_rendered"] = full_result.get("final_sql_rendered")
        aggs = answer.get("aggregations", [])
        if aggs:
            sql_info["aggregation_sql"] = [
                {"field": a.get("field"), "agg_func": a.get("agg_func"),
                 "agg_value": a.get("agg_value"),
                 "stat_sql": a.get("stat_sql"), "stat_sql_rendered": a.get("stat_sql_rendered")}
                for a in aggs
            ]

        qce = set_cached_results(
            intent_dict,
            results,
            total,
            sql_info=sql_info,
            raw_answer=answer,
        )
        from_cache = False

    # 降级：如果没有分类格式，用宽表转换（兜底）
    if not classified_results and results:
        classified_results = to_classified_format(results)

    # 更新 conversation（不创建新的）
    conv.title = user_query[:200]
    conv.query_hash = query_hash
    conv.query_cache_entry = qce
    conv.structured_query = intent_dict
    conv.save()

    # 创建首条消息（user + assistant）
    ChatMessage.objects.create(
        conversation=conv,
        role=ChatMessage.Role.USER,
        message_type=ChatMessage.Type.INTENT_QUERY,
        content=user_query,
        meta={"query_hash": query_hash, "structured_query": intent_dict, "query_cache_id": qce.id if qce else None},
    )
    result_meta = {
        "total": total,
        "from_cache": from_cache,
        "results": results or [],
        "classified_results": classified_results or [],
        "sql": sql_info.get("sql"),
        "sql_params": sql_info.get("sql_params", []),
        "sql_rendered": sql_info.get("sql_rendered"),
    }
    # 如果有聚合结果，将聚合信息加入 meta，供前端展示
    aggs = (sql_info or {}).get("aggregation_sql") or []
    if aggs:
        result_meta["aggregations"] = aggs

    ChatMessage.objects.create(
        conversation=conv,
        role=ChatMessage.Role.ASSISTANT,
        message_type=ChatMessage.Type.INTENT_QUERY,
        content=build_result_summary(total, results),
        meta=result_meta,
    )

    # 将 result 表数据写入 SQLite（长表格式）
    try:
        from .result_fetcher import fetch_result_long
        from .services import save_initial_results, save_current_results
        if data_ids:
            long_rows = fetch_result_long(data_ids)
            save_initial_results(conv, long_rows)
            save_current_results(conv, seq=1, long_rows=long_rows)
            logger.info(f"_execute_intent_init: saved {len(long_rows)} long rows to SQLite for conversation_id={conv.id}")
        else:
            logger.warning(f"_execute_intent_init: no data_ids to save for conversation_id={conv.id}")
    except Exception as e:
        logger.error(f"_execute_intent_init: Result 表写入 SQLite 失败: {e}", exc_info=True)

    data = {
        "conversation_id": conv.id,
        "title": conv.title,
        "original_query": user_query,
        "from_cache": from_cache,
        "results": results,
        "classified_results": classified_results,
        "total": total,
        "structured_query": intent_dict,
        "sql": sql_info.get("sql"),
        "sql_params": sql_info.get("sql_params", []),
        "sql_rendered": sql_info.get("sql_rendered"),
        "aggregations": (sql_info or {}).get("aggregation_sql") or [],
    }
    return data, None


# ---------------------------------------------------------------------------
# 内部辅助：模拟后端查询（待替换为真实调用）
# ---------------------------------------------------------------------------

def _fetch_from_backend(intent_dict: dict, original_query: str):
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


def _fetch_from_backend_with_details(intent_dict: dict, original_query: str):
    """
    查询后端并自动回填完整实体详情（宽表记录）。
    新增包装函数，对原有 _fetch_from_backend 做加法。
    """
    from .backend_client import fetch_results_with_details
    return fetch_results_with_details(intent_dict, original_query=original_query)


# ---------------------------------------------------------------------------
# ConversationListCreateView
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class ConversationListCreateView(View):
    """
    GET  /api/chat/conversations    → 对话列表
    POST /api/chat/conversations    → 创建新对话
    """

    def get(self, request):
        try:
            data = list_conversations()
            return JsonResponse({"success": True, "conversations": data})
        except Exception as e:
            logger.error(f"ConversationListView GET error: {e}", exc_info=True)
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    def post(self, request):
        """
        流程：用户提问 → 意图解析 → 查缓存/调后端 → 创建对话 → 返回。
        """
        try:
            body = json.loads(request.body or "{}")
            user_query = body.get("query", "").strip()

            if not user_query:
                logger.warning("ConversationListCreateView: empty query received")
                return JsonResponse(
                    {"success": False, "error": "查询内容不能为空"}, status=400
                )

            logger.info(f"ConversationListCreateView: new conversation, query={user_query[:100]!r}")

            # 1) 意图解析
            from apps.intent_engine import parse_intent
            intent = parse_intent(user_query)
            if not intent:
                logger.warning(f"ConversationListCreateView: intent parsing failed for query={user_query[:100]!r}")
                return JsonResponse(
                    {"success": False, "error": "意图解析失败"}, status=500
                )

            intent_dict = intent.to_dict()
            logger.info(f"ConversationListCreateView: intent parsed, mode={intent_dict.get('query_mode')}, groups={len(intent_dict.get('groups', []))}")

            # 2) 查 SQLite 缓存
            query_hash = QueryCache.make_hash(intent_dict)
            cached = get_cached_results(intent_dict)
            classified_results = []
            sql_info = None
            if cached:
                results = cached["results"]
                total = cached["total"]
                from_cache = True
                # 命中时取出 QueryCache 对象供外键关联
                qce = QueryCache.objects.get(query_hash=query_hash)
                # 从缓存中读取 SQL 信息
                sql_info = qce.sql_info or {}
                # 无论缓存格式新旧，始终从 result 表重新读取分类格式，
                # 避免旧缓存中缺少 classified_records 导致降级转换误分类
                data_ids = [r.get("data_id") for r in results if r.get("data_id")]
                if data_ids:
                    from .result_fetcher import fetch_result_details
                    classified_results = fetch_result_details(data_ids)
            else:
                # 3) 未命中：调后端 → 获取完整 result（含 SQL）→ 写入缓存
                full_result = fetch_full_result(intent_dict, user_query)
                answer = full_result.get("answer", {})
                results = answer.get("records", [])
                classified_results = answer.get("classified_records", [])
                data_ids = answer.get("matched_data_ids", [])

                if not results and data_ids:
                    results = [{"data_id": did} for did in data_ids]

                # executor 当前不返回 classified_records，需从 result 表还原
                if data_ids and not classified_results:
                    from .result_fetcher import fetch_result_details
                    classified_results = fetch_result_details(data_ids)

                total = answer.get("total", 0)

                # 提取 SQL 信息存入缓存
                sql_info = {
                    "sql": full_result.get("sql"),
                    "sql_params": full_result.get("sql_params", []),
                    "sql_rendered": full_result.get("sql_rendered"),
                }
                if full_result.get("query_mode") == "complex":
                    sql_info["group_sql"] = full_result.get("group_sql", [])
                    sql_info["final_sql"] = full_result.get("final_sql")
                    sql_info["final_sql_rendered"] = full_result.get("final_sql_rendered")
                aggs = answer.get("aggregations", [])
                if aggs:
                    sql_info["aggregation_sql"] = [
                        {"field": a.get("field"), "agg_func": a.get("agg_func"),
                         "agg_value": a.get("agg_value"),
                         "stat_sql": a.get("stat_sql"), "stat_sql_rendered": a.get("stat_sql_rendered")}
                        for a in aggs
                    ]

                qce = set_cached_results(
                    intent_dict,
                    results,
                    total,
                    sql_info=sql_info,
                    raw_answer=answer,
                )
                from_cache = False

            # 降级：如果没有分类格式，用宽表转换（兜底）
            if not classified_results and results:
                classified_results = to_classified_format(results)

            # 4) 创建对话轮次（外键关联到 QueryCache）
            conv = create_conversation(
                title=user_query[:200],
                user_query=user_query,
                query_hash=query_hash,
                query_cache_entry=qce,
                structured_query=intent_dict,
                results=results,
                classified_results=classified_results,
                total=total,
                from_cache=from_cache,
                sql_info=sql_info,
            )
            logger.info(f"ConversationListCreateView: conversation created, id={conv.id}, from_cache={from_cache}")

            # 5) 将 result 表数据写入 SQLite（长表格式）
            try:
                from .result_fetcher import fetch_result_long
                from .services import save_initial_results, save_current_results

                # 从 MySQL 读取长表数据（缓存命中和未命中的情况下都可用）
                if data_ids:
                    long_rows = fetch_result_long(data_ids)
                    save_initial_results(conv, long_rows)
                    save_current_results(conv, seq=1, long_rows=long_rows)
                    logger.info(f"ConversationListCreateView: saved {len(long_rows)} long rows to SQLite for conversation_id={conv.id}")
                else:
                    logger.warning(f"ConversationListCreateView: no data_ids to save for conversation_id={conv.id}")
            except Exception as e:
                logger.error(f"Result 表写入 SQLite 失败: {e}", exc_info=True)

            return JsonResponse({
                "success": True,
                "data": {
                    "conversation_id": conv.id,
                    "title": conv.title,
                    "from_cache": from_cache,
                    "results": results,
                    "classified_results": classified_results,
                    "total": total,
                    "structured_query": intent_dict,
                    "sql": sql_info.get("sql"),
                    "sql_params": sql_info.get("sql_params", []),
                    "sql_rendered": sql_info.get("sql_rendered"),
                    "aggregations": (sql_info or {}).get("aggregation_sql") or [],
                },
            })

        except json.JSONDecodeError:
            return JsonResponse(
                {"success": False, "error": "请求体格式错误"}, status=400
            )
        except Exception as e:
            logger.error(f"ConversationListCreateView POST error: {e}", exc_info=True)
            return JsonResponse(
                {"success": False, "error": f"服务器错误: {str(e)}"}, status=500
            )


# ---------------------------------------------------------------------------
# ConversationEmptyView
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class ConversationEmptyView(View):
    """
    POST /api/chat/conversations/empty  → 创建空对话轮次
    """

    def post(self, request):
        try:
            body = json.loads(request.body or "{}")
            title = body.get("title", "新对话").strip() or "新对话"
            conv = create_empty_conversation(title=title)
            return JsonResponse({
                "success": True,
                "data": {
                    "conversation_id": conv.id,
                    "title": conv.title,
                    "created_at": conv.created_at.isoformat(),
                    "message_count": 0,
                },
            })
        except json.JSONDecodeError:
            return JsonResponse(
                {"success": False, "error": "请求体格式错误"}, status=400
            )
        except Exception as e:
            logger.error(f"ConversationEmptyView POST error: {e}", exc_info=True)
            return JsonResponse(
                {"success": False, "error": f"服务器错误: {str(e)}"}, status=500
            )


# ---------------------------------------------------------------------------
# ConversationInitView
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class ConversationInitView(View):
    """
    POST /api/chat/conversations/<id>/init  → 对空对话执行首轮意图理解
    """

    def post(self, request, conversation_id):
        try:
            body = json.loads(request.body or "{}")
            user_query = body.get("query", "").strip()

            if not user_query:
                return JsonResponse(
                    {"success": False, "error": "查询内容不能为空"}, status=400
                )

            try:
                conv = Conversation.objects.get(pk=int(conversation_id))
            except Conversation.DoesNotExist:
                return JsonResponse(
                    {"success": False, "error": "对话不存在"}, status=404
                )

            # 幂等检查：若已有 InitialResult，拒绝重复初始化
            if InitialResult.objects.filter(conversation=conv).exists():
                return JsonResponse(
                    {"success": False, "error": "该对话已初始化，请使用 /messages 接口进行后续问答"}, status=400
                )

            data, error = _execute_intent_init(conv, user_query)
            if error:
                return JsonResponse(
                    {"success": False, "error": error}, status=500
                )

            return JsonResponse({"success": True, "data": data})

        except json.JSONDecodeError:
            return JsonResponse(
                {"success": False, "error": "请求体格式错误"}, status=400
            )
        except Exception as e:
            logger.error(f"ConversationInitView POST error: {e}", exc_info=True)
            return JsonResponse(
                {"success": False, "error": f"服务器错误: {str(e)}"}, status=500
            )


# ---------------------------------------------------------------------------
# ConversationDetailView
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class ConversationClearView(View):
    """
    DELETE /api/chat/conversations/clear  → 清空所有对话并重置 ID 计数
    """

    def delete(self, request):
        try:
            deleted_count = delete_all_conversations()
            return JsonResponse({
                "success": True,
                "message": f"已清空全部 {deleted_count} 条对话记录，ID 计数器已重置",
                "deleted_count": deleted_count,
            })
        except Exception as e:
            logger.error(f"ConversationClearView DELETE error: {e}", exc_info=True)
            return JsonResponse(
                {"success": False, "error": str(e)}, status=500
            )


class ConversationDetailView(View):
    """
    GET    /api/chat/conversations/<id>  → 对话详情
    DELETE /api/chat/conversations/<id>  → 删除对话
    """

    def get(self, request, conversation_id):
        try:
            logger.info(f"ConversationDetailView GET: conversation_id={conversation_id}")
            data = get_conversation_detail(int(conversation_id))
            if data is None:
                logger.warning(f"ConversationDetailView GET: conversation {conversation_id} not found")
                return JsonResponse(
                    {"success": False, "error": "对话不存在"}, status=404
                )
            logger.info(f"ConversationDetailView GET: returned conversation_id={conversation_id}, messages={len(data.get('messages', []))}")
            return JsonResponse({"success": True, "data": data})
        except Exception as e:
            logger.error(f"ConversationDetailView GET error: {e}", exc_info=True)
            return JsonResponse(
                {"success": False, "error": str(e)}, status=500
            )

    def delete(self, request, conversation_id):
        try:
            logger.info(f"ConversationDetailView DELETE: conversation_id={conversation_id}")
            # Django ORM 级联删除会自动清理关联的 InitialResult + CurrentResult（SQLite）
            ok = delete_conversation(int(conversation_id))
            if ok:
                logger.info(f"ConversationDetailView DELETE: conversation {conversation_id} deleted")
                return JsonResponse(
                    {"success": True, "message": f"对话 {conversation_id} 已删除"}
                )
            logger.warning(f"ConversationDetailView DELETE: conversation {conversation_id} not found")
            return JsonResponse(
                {"success": False, "error": f"对话 {conversation_id} 不存在"}, status=404
            )
        except Exception as e:
            logger.error(f"ConversationDetailView DELETE error: {e}", exc_info=True)
            return JsonResponse(
                {"success": False, "error": str(e)}, status=500
            )


# ---------------------------------------------------------------------------
# MessageCreateView
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class MessageCreateView(View):
    """
    POST /api/chat/conversations/<id>/messages
    
    在已有对话中追加后续问答。
    具体回答生成逻辑（基于已有数据上下文）待后续实现。
    """

    def post(self, request, conversation_id):
        try:
            body = json.loads(request.body or "{}")
            user_content = body.get("content", "").strip()

            if not user_content:
                logger.warning(f"MessageCreateView: empty content for conversation_id={conversation_id}")
                return JsonResponse(
                    {"success": False, "error": "消息内容不能为空"}, status=400
                )

            try:
                conv = Conversation.objects.get(pk=int(conversation_id))
            except Conversation.DoesNotExist:
                return JsonResponse(
                    {"success": False, "error": "对话不存在"}, status=404
                )

            # 【保险措施】检查是否已有 InitialResult（初表）
            has_initial = InitialResult.objects.filter(conversation=conv).exists()

            if not has_initial:
                logger.info(f"MessageCreateView: insurance triggered, conversation_id={conversation_id} has no InitialResult, treating as intent init")
                data, error = _execute_intent_init(conv, user_content)
                if error:
                    return JsonResponse(
                        {"success": False, "error": error}, status=500
                    )
                return JsonResponse({"success": True, "data": data})

            logger.info(f"MessageCreateView: follow-up message, conversation_id={conversation_id}, content={user_content[:100]!r}")
            # 执行真实的 follow-up 查询（多轮递进）
            from apps.follow_up.services import process_follow_up
            result = process_follow_up(int(conversation_id), user_content)

            if result.get("error"):
                logger.error(f"MessageCreateView: follow-up failed, conversation_id={conversation_id}, error={result['error']}")
                # 区分"对话不存在"（404）和"查询执行失败"（500）
                if "对话不存在" in result["error"]:
                    return JsonResponse(
                        {"success": False, "error": result["error"]}, status=404
                    )
                return JsonResponse(
                    {"success": False, "error": result["error"]}, status=500
                )
            logger.info(f"MessageCreateView: follow-up success, conversation_id={conversation_id}, total={result.get('total', 0)}")

            logger.info(
                f"MessageCreateView: response prepared, chart_data_type={type(result.get('chart_data')).__name__}, "
                f"has_chart_data={bool(result.get('chart_data'))}"
            )
            return JsonResponse({
                "success": True,
                "data": {
                    "user_message_id": result["user_message_id"],
                    "assistant_message_id": result["assistant_message_id"],
                    "answer": result["answer"],
                    "sql": result.get("sql"),
                    "params": result.get("params"),
                    "total": result.get("total", 0),
                    "results": result.get("results", []),
                    "classified_results": result.get("classified_results", []),
                    "intent": result.get("intent"),
                    "analysis_result": result.get("analysis_result"),
                    "chart_data": result.get("chart_data"),
                    "scope": result.get("scope", "current"),
                    "original_query": result.get("original_query", ""),
                },
            })

        except json.JSONDecodeError:
            return JsonResponse(
                {"success": False, "error": "请求体格式错误"}, status=400
            )
        except Exception as e:
            logger.error(f"MessageCreateView POST error: {e}", exc_info=True)
            return JsonResponse(
                {"success": False, "error": f"服务器错误: {str(e)}"}, status=500
            )


# ---------------------------------------------------------------------------
# DataDetailView
# ---------------------------------------------------------------------------

class DataDetailView(View):
    """
    GET /api/chat/data_detail/<int:data_id>
    根据 data_id 查询原始 JSON 数据（从 data/ 目录下的 JSON 文件）。
    """

    def get(self, request, data_id):
        try:
            logger.info(f"DataDetailView GET: data_id={data_id}")
            # 优先从原始 JSON 文件加载
            raw_data = load_raw_data_by_meta_id(int(data_id))
            if raw_data:
                logger.info(f"DataDetailView GET: data_id={data_id}, loaded raw data from file")
                return JsonResponse({
                    "success": True,
                    "data": {
                        "raw_json": raw_data,
                        "data_id": data_id,
                    },
                })

            # 回退：从 MySQL 加载处理后的数据（兼容旧数据）
            details = fetch_result_details([int(data_id)])
            if not details:
                logger.warning(f"DataDetailView GET: data_id={data_id} not found in raw data or MySQL")
                return JsonResponse(
                    {"success": False, "error": "数据不存在"}, status=404
                )
            logger.info(f"DataDetailView GET: data_id={data_id}, fallback to MySQL data")
            detail_data = details[0]
            # 自动计算元素组成（用于饼图展示）
            detail_data["element_composition"] = build_element_composition(detail_data)
            return JsonResponse({
                "success": True,
                "data": detail_data,
            })
        except Exception as e:
            logger.error(f"DataDetailView GET error: {e}", exc_info=True)
            return JsonResponse(
                {"success": False, "error": f"服务器错误: {str(e)}"}, status=500
            )
