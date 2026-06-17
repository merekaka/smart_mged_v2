import logging
from typing import List, Dict, Any, Optional

from apps.chat.models import Conversation, ChatMessage
from apps.chat.services import add_follow_up_message, get_current_results as _get_current_results_from_service, save_current_results
from apps.chat.result_fetcher import to_classified_format, wide_to_long
from apps.follow_up.result_store import ResultStore
from apps.follow_up.classifier import classify_follow_up_intent
from apps.follow_up.filter.engine import FollowUpQueryEngine
from apps.follow_up.statistics.parser import StatisticalIntentParser
from apps.follow_up.statistics.engine import StatisticalEngine

logger = logging.getLogger(__name__)


def _get_long_rows(conversation_id: int, scope: str) -> List[Dict[str, Any]]:
    """
    根据 scope 读取长表数据。
    scope="original" → InitialResult（初表）
    scope="current"  → CurrentResult（当前表）
    """
    from apps.chat.services import get_initial_results, get_current_results

    if scope == "original":
        rows = get_initial_results(conversation_id)
        logger.info(f"_get_long_rows: source=InitialResult, conversation_id={conversation_id}, rows={len(rows)}")
    else:
        rows = get_current_results(conversation_id)
        logger.info(f"_get_long_rows: source=CurrentResult, conversation_id={conversation_id}, rows={len(rows)}")
    return rows


def process_follow_up(conversation_id: int, user_text: str) -> Dict[str, Any]:
    """
    处理一轮 follow-up 查询的入口函数。
    1. 获取对话
    2. 意图分流（筛选 vs 统计分析）
    3. 分派到对应处理流程
    """
    logger.info(f"process_follow_up: conversation_id={conversation_id}, user_text={user_text[:100]!r}")
    try:
        conv = Conversation.objects.select_related("query_cache_entry").get(pk=conversation_id)
    except Conversation.DoesNotExist:
        logger.warning(f"process_follow_up: conversation {conversation_id} not found")
        return {"error": "对话不存在", "answer": "对话不存在。", "results": [], "total": 0}

    # === 意图分流 ===
    intent_category = classify_follow_up_intent(user_text)
    logger.info(f"process_follow_up: classified as '{intent_category}'")

    if intent_category == "statistics":
        return _process_statistical_analysis(conv, user_text)
    return _process_filter_follow_up(conv, user_text)


def _process_filter_follow_up(conv: Conversation, user_text: str) -> Dict[str, Any]:
    """
    处理筛选类 follow-up（原有逻辑）。
    流程：意图解析 → 读取数据 → SQL 生成执行 → 覆盖 CurrentResult → 创建消息。
    """
    conversation_id = conv.id

    # 1) 意图解析（复用 follow_up 下的独立 intent_engine，避免误改原始模块）
    from apps.follow_up.intent_engine.parser import IntentParser
    parser = IntentParser()
    intent = parser.parse(user_text)
    if not intent:
        logger.warning(f"process_follow_up: intent parsing failed for user_text={user_text[:100]!r}")
        return {
            "error": "意图解析失败",
            "answer": "无法理解您的问题，请尝试更具体的描述。",
            "results": [],
            "total": 0,
            "sql": None,
            "intent": {},
        }

    intent_dict = intent.to_dict()
    scope = intent_dict.get("follow_up_scope", "current")
    logger.info(f"process_follow_up: intent parsed, scope={scope}")

    # 2) 读取长表数据
    long_rows = _get_long_rows(conversation_id, scope)

    if not long_rows:
        # 回退：从 meta.results 加载（兼容旧数据）
        logger.warning(f"process_follow_up: no long rows found, fallback to meta.results")
        current_results = _get_current_results_from_service(conv)
        if not current_results:
            logger.warning(f"process_follow_up: no current results for conversation {conversation_id}")
            return {
                "error": "当前对话没有可查询的结果集",
                "answer": "当前对话没有关联的查询数据，无法回答。",
                "results": [],
                "total": 0,
                "sql": None,
                "intent": intent_dict,
            }
        store = ResultStore(current_results)
        logger.info(f"process_follow_up: ResultStore (:memory:) loaded with {len(current_results)} rows")
    else:
        # 长表 → 宽表（内存转置）
        wide_results = ResultStore.long_to_wide(long_rows)
        logger.info(f"process_follow_up: long_to_wide completed, wide_rows={len(wide_results)}, cols={list(wide_results[0].keys()) if wide_results else []}")

        if not wide_results:
            return {
                "error": "当前对话没有可查询的结果集",
                "answer": "当前对话没有关联的查询数据，无法回答。",
                "results": [],
                "total": 0,
                "sql": None,
                "intent": intent_dict,
            }

        store = ResultStore(wide_results)
        current_results = wide_results
        logger.info(f"process_follow_up: ResultStore (:memory:) loaded with {len(wide_results)} wide rows")

    # 3) 执行 follow-up 查询
    engine = FollowUpQueryEngine()
    result = engine.query(
        user_text=user_text,
        current_results=current_results,
        store=store,
        intent_dict=intent_dict,
    )
    logger.info(f"process_follow_up: engine.query returned total={result.get('total', 0)}, has_error={bool(result.get('error'))}")

    if result.get("error"):
        return {
            "error": result["error"],
            "answer": result.get("answer", "查询失败。"),
            "results": [],
            "total": 0,
            "sql": result.get("sql"),
            "intent": intent_dict,
        }

    # 4) 将新结果（宽表）转回长表，覆盖写入 CurrentResult
    follow_up_results = result.get("results", [])

    # 从 InitialResult 构建 property_name → bitmap_role 映射，用于分类和回填
    from apps.chat.services import get_initial_results
    initial_rows = get_initial_results(conversation_id)
    role_map = {
        r["property_name"]: r["bitmap_role"]
        for r in initial_rows
        if r.get("property_name") and r.get("bitmap_role")
    }

    if follow_up_results:
        try:
            long_rows_new = wide_to_long(follow_up_results, role_map=role_map)
            # 计算 seq：当前 CurrentResult 中最大的 seq + 1，如果没有则设为 2（首轮是 1）
            from apps.chat.models import CurrentResult
            max_seq = CurrentResult.objects.filter(conversation_id=conversation_id).values_list("seq", flat=True).order_by("-seq").first()
            new_seq = (max_seq or 1) + 1
            save_current_results(conv, seq=new_seq, long_rows=long_rows_new)
            logger.info(f"process_follow_up: saved {len(long_rows_new)} long rows to CurrentResult, seq={new_seq}, role_map_size={len(role_map)}")
        except Exception as e:
            logger.error(f"process_follow_up: failed to save current results: {e}", exc_info=True)
    else:
        logger.info(f"process_follow_up: no results to persist")

    # 5) 创建消息（assistant.meta 中缓存本轮结果，形成递进）
    assistant_meta = {
        "results": follow_up_results,
        "total": result.get("total", 0),
        "sql": result.get("sql"),
        "params": [str(p) for p in result.get("params", [])] if result.get("params") else [],
        "intent": intent_dict,
    }

    # 将宽表结果转换为分类格式，供前端卡片展示（使用 role_map 确保与初表分组一致）
    follow_up_classified = to_classified_format(follow_up_results, role_map=role_map)

    msg_result = add_follow_up_message(
        conversation_id=conversation_id,
        user_content=user_text,
        assistant_content=result.get("answer", ""),
        assistant_meta=assistant_meta,
        classified_results=follow_up_classified,
    )

    if msg_result is None:
        logger.error(f"process_follow_up: add_follow_up_message returned None for conversation_id={conversation_id}")
        return {"error": "消息保存失败", "answer": "消息保存失败。", "results": [], "total": 0}

    logger.info(f"process_follow_up finished: conversation_id={conversation_id}, user_msg_id={msg_result['user_message_id']}, assistant_msg_id={msg_result['assistant_message_id']}")
    return {
        "user_message_id": msg_result["user_message_id"],
        "assistant_message_id": msg_result["assistant_message_id"],
        "answer": result.get("answer", ""),
        "sql": result.get("sql"),
        "params": result.get("params"),
        "results": follow_up_results,
        "classified_results": follow_up_classified,
        "total": result.get("total", 0),
        "intent": intent_dict,
        "scope": scope,
        "original_query": user_text,
    }


def _process_statistical_analysis(conv: Conversation, user_text: str) -> Dict[str, Any]:
    """
    处理统计分析类 follow-up。
    流程：统计意图解析 → 读取数据 → 宽表转换 → 统计分析 → 创建消息（不覆盖 CurrentResult）。
    """
    conversation_id = conv.id

    # 1) 统计意图解析
    parser = StatisticalIntentParser()
    stat_intent = parser.parse(user_text)
    if not stat_intent:
        logger.warning(f"_process_statistical_analysis: intent parsing failed for user_text={user_text[:100]!r}")
        return {
            "error": "统计意图解析失败",
            "answer": "无法理解您的统计分析请求，请尝试更具体的描述（如'按某属性排序'或'画个饼图'）。",
            "results": [],
            "total": 0,
            "intent": {},
        }

    scope = stat_intent.get("follow_up_scope", "current")
    logger.info(f"_process_statistical_analysis: stat_intent parsed, op={stat_intent.get('analysis_op')}, scope={scope}")

    # 2) 读取长表数据（复用筛选流程的数据获取）
    long_rows = _get_long_rows(conversation_id, scope)

    if not long_rows:
        # 回退：从 meta.results 加载
        logger.warning(f"_process_statistical_analysis: no long rows found, fallback to meta.results")
        current_results = _get_current_results_from_service(conv)
        if not current_results:
            logger.warning(f"_process_statistical_analysis: no current results for conversation {conversation_id}")
            return {
                "error": "当前对话没有可查询的结果集",
                "answer": "当前对话没有关联的查询数据，无法进行统计分析。",
                "results": [],
                "total": 0,
                "intent": stat_intent,
            }
        wide_results = current_results
    else:
        wide_results = ResultStore.long_to_wide(long_rows)
        logger.info(f"_process_statistical_analysis: long_to_wide completed, wide_rows={len(wide_results)}, cols={list(wide_results[0].keys()) if wide_results else []}")

    if not wide_results:
        return {
            "error": "当前对话没有可查询的结果集",
            "answer": "当前对话没有关联的查询数据，无法进行统计分析。",
            "results": [],
            "total": 0,
            "intent": stat_intent,
        }

    # 3) 执行统计分析
    engine = StatisticalEngine()
    result = engine.analyze(stat_intent, wide_results)
    logger.info(f"_process_statistical_analysis: engine.analyze returned total={result.get('total', 0)}, has_error={bool(result.get('error'))}")

    if result.get("error"):
        return {
            "error": result["error"],
            "answer": result.get("answer", "统计分析失败。"),
            "results": result.get("results", []),
            "total": result.get("total", 0),
            "intent": stat_intent,
        }

    # 4) 构建 role_map（用于分类格式转换）
    from apps.chat.services import get_initial_results
    initial_rows = get_initial_results(conversation_id)
    role_map = {
        r["property_name"]: r["bitmap_role"]
        for r in initial_rows
        if r.get("property_name") and r.get("bitmap_role")
    }

    # 统计分析不覆盖 CurrentResult（不改变筛选结果集）
    analysis_results = result.get("results", [])
    follow_up_classified = to_classified_format(analysis_results, role_map=role_map)

    # 5) 创建消息
    assistant_meta = {
        "results": analysis_results,
        "total": result.get("total", 0),
        "intent": stat_intent,
        "analysis_result": result.get("analysis_result"),
        "chart_data": result.get("chart_data"),
        "is_statistical_analysis": True,
    }

    msg_result = add_follow_up_message(
        conversation_id=conversation_id,
        user_content=user_text,
        assistant_content=result.get("answer", ""),
        assistant_meta=assistant_meta,
        classified_results=follow_up_classified,
    )

    if msg_result is None:
        logger.error(f"_process_statistical_analysis: add_follow_up_message returned None for conversation_id={conversation_id}")
        return {"error": "消息保存失败", "answer": "消息保存失败。", "results": [], "total": 0}

    logger.info(f"_process_statistical_analysis finished: conversation_id={conversation_id}, user_msg_id={msg_result['user_message_id']}, assistant_msg_id={msg_result['assistant_message_id']}")
    return {
        "user_message_id": msg_result["user_message_id"],
        "assistant_message_id": msg_result["assistant_message_id"],
        "answer": result.get("answer", ""),
        "total": result.get("total", 0),
        "results": analysis_results,
        "classified_results": follow_up_classified,
        "intent": stat_intent,
        "analysis_result": result.get("analysis_result"),
        "chart_data": result.get("chart_data"),
        "scope": scope,
        "original_query": user_text,
    }
