import logging
from typing import Optional, List, Dict, Any

from django.utils import timezone
from django.db import transaction

from apps.query_cache.models import QueryCache
from apps.query_cache.utils import get_cached_results
from .models import Conversation, ChatMessage, InitialResult, CurrentResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conversation 生命周期
# ---------------------------------------------------------------------------

def create_empty_conversation(title: str = "新对话") -> Conversation:
    """
    创建一个空的对话轮次，不创建任何消息和结果。
    供前端点击"新建对话"时立即创建可见记录。
    """
    conv = Conversation.objects.create(
        title=title[:200],
        query_hash="",
        structured_query={},
    )
    logger.info(f"create_empty_conversation: conversation_id={conv.id}")
    return conv


def create_conversation(
    title: str,
    user_query: str,
    query_hash: Optional[str] = None,
    query_cache_entry: Optional[QueryCache] = None,
    structured_query: Optional[dict] = None,
    results: Optional[List[Dict]] = None,
    classified_results: Optional[List[Dict]] = None,
    total: int = 0,
    from_cache: bool = False,
    sql_info: Optional[Dict[str, Any]] = None,
) -> Conversation:
    """
    创建一轮新对话，并写入首条消息（用户意图查询 + 助手返回结果）。
    """
    logger.info(f"create_conversation: title={title[:60]!r}, from_cache={from_cache}, total={total}")
    with transaction.atomic():
        conv = Conversation.objects.create(
            title=title[:200],
            query_hash=query_hash or "",
            query_cache_entry=query_cache_entry,
            structured_query=structured_query or {},
        )

        # 用户的首条提问
        ChatMessage.objects.create(
            conversation=conv,
            role=ChatMessage.Role.USER,
            message_type=ChatMessage.Type.INTENT_QUERY,
            content=user_query,
            meta={"query_hash": query_hash, "structured_query": structured_query, "query_cache_id": query_cache_entry.id if query_cache_entry else None},
        )

        # 助手返回的结果摘要
        result_meta = {
            "total": total,
            "from_cache": from_cache,
            "results": results or [],
            "classified_results": classified_results or [],
            "sql": (sql_info or {}).get("sql"),
            "sql_params": (sql_info or {}).get("sql_params", []),
            "sql_rendered": (sql_info or {}).get("sql_rendered"),
        }
        ChatMessage.objects.create(
            conversation=conv,
            role=ChatMessage.Role.ASSISTANT,
            message_type=ChatMessage.Type.INTENT_QUERY,
            content=build_result_summary(total, results),
            meta=result_meta,
        )

    logger.info(f"create_conversation finished: conversation_id={conv.id}, messages_created=2")
    return conv


def add_follow_up_message(
    conversation_id: int,
    user_content: str,
    assistant_content: str,
    assistant_meta: Optional[Dict[str, Any]] = None,
    classified_results: Optional[List[Dict]] = None,
) -> Optional[Dict[str, Any]]:
    """
    在某轮对话中追加一组后续问答消息（user + assistant）。
    返回包含两条消息 ID 的字典，失败返回 None。
    """
    logger.info(f"add_follow_up_message: conversation_id={conversation_id}, user_content={user_content[:60]!r}")
    try:
        conv = Conversation.objects.get(pk=conversation_id)
    except Conversation.DoesNotExist:
        logger.warning(f"add_follow_up_message: conversation {conversation_id} not found")
        return None

    with transaction.atomic():
        user_msg = ChatMessage.objects.create(
            conversation=conv,
            role=ChatMessage.Role.USER,
            message_type=ChatMessage.Type.FOLLOW_UP,
            content=user_content,
        )
        meta = assistant_meta or {}
        if classified_results is not None:
            meta["classified_results"] = classified_results
        assistant_msg = ChatMessage.objects.create(
            conversation=conv,
            role=ChatMessage.Role.ASSISTANT,
            message_type=ChatMessage.Type.FOLLOW_UP,
            content=assistant_content,
            meta=meta,
        )
        # 更新对话时间戳
        conv.save(update_fields=["updated_at"])

    logger.info(f"add_follow_up_message finished: conversation_id={conversation_id}, user_msg_id={user_msg.id}, assistant_msg_id={assistant_msg.id}")
    return {
        "user_message_id": user_msg.id,
        "assistant_message_id": assistant_msg.id,
    }


def get_conversation_detail(conversation_id: int) -> Optional[Dict[str, Any]]:
    """
    获取某轮对话的完整详情及消息流。
    """
    logger.info(f"get_conversation_detail: conversation_id={conversation_id}")
    try:
        conv = Conversation.objects.prefetch_related("messages").get(pk=conversation_id)
    except Conversation.DoesNotExist:
        logger.warning(f"get_conversation_detail: conversation {conversation_id} not found")
        return None

    return {
        "conversation_id": conv.id,
        "title": conv.title,
        "query_hash": conv.query_hash,
        "structured_query": conv.structured_query,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "message_type": msg.message_type,
                "content": msg.content,
                "meta": msg.meta,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in conv.messages.all()
        ],
    }


def list_conversations() -> List[Dict[str, Any]]:
    """
    返回所有对话轮次的摘要列表（按最后更新时间倒序）。
    """
    conversations = Conversation.objects.prefetch_related("messages").all()
    logger.info(f"list_conversations: total={conversations.count()}")
    result = []
    for conv in conversations:
        first_user_msg = conv.messages.filter(role=ChatMessage.Role.USER).first()
        latest_msg = conv.messages.last()
        result.append({
            "conversation_id": conv.id,
            "title": conv.title,
            "latest_message": latest_msg.content[:100] if latest_msg else "",
            "latest_timestamp": conv.updated_at.isoformat(),
            "message_count": conv.messages.count(),
            "query_hash": conv.query_hash,
        })
    return result


def delete_conversation(conversation_id: int) -> bool:
    """
    删除某轮对话及其所有消息（级联删除）。
    InitialResult 和 CurrentResult 会通过 ORM 级联自动清理。
    """
    logger.info(f"delete_conversation: conversation_id={conversation_id}")
    deleted, _ = Conversation.objects.filter(pk=conversation_id).delete()
    logger.info(f"delete_conversation: conversation_id={conversation_id}, deleted={deleted > 0}")
    return deleted > 0


def delete_all_conversations() -> int:
    """
    清空所有对话及其关联消息/结果，并重置 SQLite 自增 ID 计数器，
    使下一轮对话的 conversation_id 重新从 1 开始。
    返回被删除的对话数量。
    """
    from utils.db_utils import reset_sqlite_sequence

    count = Conversation.objects.count()

    # Django ORM 级联删除会自动清理 ChatMessage、InitialResult、CurrentResult
    Conversation.objects.all().delete()

    # 重置 SQLite 自增序列，使新记录的 id 从 1 开始
    reset_sqlite_sequence('cache_sqlite', [
        'chat_conversation',
        'chat_message',
        'chat_initial_result',
        'chat_current_result',
    ])

    logger.info(f"Deleted all conversations (count={count}) and reset auto-increment counters.")
    return count


# ---------------------------------------------------------------------------
# 结果持久化（长表格式）
# ---------------------------------------------------------------------------

def save_initial_results(
    conversation: Conversation,
    long_rows: List[Dict[str, Any]],
) -> int:
    """
    将首轮查询结果（长表格式）持久化到 InitialResult。
    每个 conversation 只调用一次。

    long_rows 示例:
        [
            {"data_id": 1, "title": "钛合金1", "property_name": "tensile_strength", "bitmap_role": "result", "value_text": "500"},
            ...
        ]
    """
    logger.info(f"save_initial_results: conversation_id={conversation.id}, rows={len(long_rows)}")
    if not long_rows:
        return 0

    objs = [
        InitialResult(
            conversation=conversation,
            data_id=row.get("data_id"),
            title=row.get("title", ""),
            property_name=row.get("property_name", ""),
            bitmap_role=row.get("bitmap_role", ""),
            value_text=row.get("value_text"),
        )
        for row in long_rows
    ]
    InitialResult.objects.bulk_create(objs)
    logger.info(f"save_initial_results finished: created {len(objs)} rows")
    return len(objs)


def save_current_results(
    conversation: Conversation,
    seq: int,
    long_rows: List[Dict[str, Any]],
) -> int:
    """
    将最近一次问答结果（长表格式）持久化到 CurrentResult。
    先删除该 conversation 的旧数据，再插入新数据（覆盖更新）。
    """
    logger.info(f"save_current_results: conversation_id={conversation.id}, seq={seq}, rows={len(long_rows)}")
    with transaction.atomic():
        deleted, _ = CurrentResult.objects.filter(conversation=conversation).delete()
        logger.info(f"save_current_results: deleted old rows={deleted}")

        if not long_rows:
            return 0

        objs = [
            CurrentResult(
                conversation=conversation,
                seq=seq,
                data_id=row.get("data_id"),
                title=row.get("title", ""),
                property_name=row.get("property_name", ""),
                bitmap_role=row.get("bitmap_role", ""),
                value_text=row.get("value_text"),
            )
            for row in long_rows
        ]
        CurrentResult.objects.bulk_create(objs)

    logger.info(f"save_current_results finished: created {len(objs)} rows")
    return len(objs)


def get_initial_results(conversation_id: int) -> List[Dict[str, Any]]:
    """
    获取某对话的首轮结果（初表），长表格式。
    """
    rows = InitialResult.objects.filter(conversation_id=conversation_id).values(
        "data_id", "title", "property_name", "bitmap_role", "value_text"
    )
    return list(rows)


def get_current_results(conversation_id: int) -> List[Dict[str, Any]]:
    """
    获取某对话的最近一次结果（当前表），长表格式。
    """
    rows = CurrentResult.objects.filter(conversation_id=conversation_id).values(
        "data_id", "title", "property_name", "bitmap_role", "value_text", "seq"
    )
    return list(rows)


# ---------------------------------------------------------------------------
# 与 query_cache 的上下文衔接
# ---------------------------------------------------------------------------

def get_result_context(conversation_id: int) -> Optional[Dict[str, Any]]:
    """
    根据对话 ID 获取该轮对话关联的查询结果上下文。
    用于后续问答模块作为数据上下文。
    """
    try:
        conv = Conversation.objects.get(pk=conversation_id)
    except Conversation.DoesNotExist:
        return None

    # 优先通过外键直接取缓存对象（最结构化、最高效）
    if conv.query_cache_entry:
        return {
            "total": conv.query_cache_entry.total,
            "items": conv.query_cache_entry.results,
            "structured_query": conv.query_cache_entry.structured_query,
        }

    if not conv.query_hash:
        return {"total": 0, "items": [], "structured_query": conv.structured_query}

    cached = get_cached_results(conv.structured_query) if conv.structured_query else None
    if cached:
        return {
            "total": cached.get("total", 0),
            "items": cached.get("results", []),
            "structured_query": cached.get("structured_query", {}),
        }

    # 若缓存已过期，尝试直接用 query_hash 读取
    try:
        entry = QueryCache.objects.get(query_hash=conv.query_hash)
        return {
            "total": entry.total,
            "items": entry.results,
            "structured_query": entry.structured_query,
        }
    except QueryCache.DoesNotExist:
        return {"total": 0, "items": [], "structured_query": conv.structured_query}


# ---------------------------------------------------------------------------
# 兼容 search 模块的历史记录
# ---------------------------------------------------------------------------

def save_search_record(session_id: str, query_text: str, response_data: dict) -> Conversation:
    """
    兼容 apps.search 的会话存档需求。
    使用 session_id 作为标识查找或创建对话，并追加一条搜索记录消息。
    """
    with transaction.atomic():
        conv, created = Conversation.objects.get_or_create(
            defaults={
                "title": query_text[:200],
                "query_hash": "",
                "structured_query": {},
            }
        )
        if not created and not conv.title:
            conv.title = query_text[:200]
            conv.save(update_fields=["title"])

        ChatMessage.objects.create(
            conversation=conv,
            role=ChatMessage.Role.ASSISTANT,
            message_type=ChatMessage.Type.SEARCH_RECORD,
            content=query_text,
            meta={"response_data": response_data},
        )
        conv.save(update_fields=["updated_at"])

    return conv


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def build_result_summary(total: int, results: Optional[List[Dict]]) -> str:
    """
    根据结果集生成一段简单的文本摘要，作为首条 assistant 消息的 content。
    """
    if total == 0:
        return "未找到符合条件的数据。"
    count = len(results) if results else 0
    return f"共找到 {total} 条相关数据，以下展示前 {count} 条结果。"


# ---------------------------------------------------------------------------
# Follow-up 多轮递进查询
# ---------------------------------------------------------------------------
#
# 注：process_follow_up 与 get_current_results 已迁移至 apps.follow_up.services
#     chat 模块仅保留对话生命周期管理，追问逻辑由 follow_up 模块独立处理。
#
