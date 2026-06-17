from django.db import models


class Conversation(models.Model):
    """
    对话轮次：由一次意图理解创建的生命周期单元。
    """
    title = models.CharField(max_length=200, help_text="自动取用户问题前N字做标题")
    query_hash = models.CharField(
        max_length=64, blank=True, null=True, db_index=True,
        help_text="关联 apps.query_cache 的 query_hash（冗余存储，便于缓存被清理后仍能追溯）"
    )
    query_cache_entry = models.ForeignKey(
        "query_cache.QueryCache",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
        help_text="外键关联到 query_cache 表（同在 SQLite 中）",
    )
    structured_query = models.JSONField(
        default=dict, blank=True,
        help_text="意图解析后的结构化查询条件"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        app_label = "chat"
        db_table = "chat_conversation"

    def __str__(self):
        return f"Conversation[{self.id}] {self.title}"


class ChatMessage(models.Model):
    """
    单条消息：记录对话轮次内的所有交互。
    """
    class Role(models.TextChoices):
        USER = "user", "用户"
        ASSISTANT = "assistant", "助手"

    class Type(models.TextChoices):
        INTENT_QUERY = "intent_query", "意图查询"
        FOLLOW_UP = "follow_up", "后续问答"
        SEARCH_RECORD = "search_record", "搜索记录"

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        help_text="所属对话轮次"
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    message_type = models.CharField(max_length=20, choices=Type.choices)
    content = models.TextField(help_text="消息文本内容")
    meta = models.JSONField(default=dict, blank=True, help_text="扩展字段")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        app_label = "chat"
        db_table = "chat_message"

    def __str__(self):
        return f"Message[{self.id}] {self.role} in Conv[{self.conversation_id}]"


class InitialResult(models.Model):
    """
    首轮意图查询结果（初表），长表格式。
    每个 conversation 只写入一次，永不更新。
    data_id 相同的数据属于同一条数据。
    """
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="initial_results",
        help_text="所属对话轮次",
    )
    data_id = models.BigIntegerField(help_text="实体ID，同一data_id的行属于同一条数据")
    title = models.CharField(max_length=255, blank=True, help_text="数据集/样品标题")
    property_name = models.CharField(max_length=255, help_text="属性英文名称（原始名，不加前缀）")
    bitmap_role = models.CharField(max_length=64, blank=True, help_text="属性类别：object / operate / result")
    value_text = models.TextField(blank=True, null=True, help_text="属性值（字符串存储）")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "chat"
        db_table = "chat_initial_result"
        indexes = [
            models.Index(fields=["conversation", "data_id"]),
            models.Index(fields=["conversation", "property_name"]),
        ]

    def __str__(self):
        return f"InitialResult[{self.id}] conv={self.conversation_id} data={self.data_id} prop={self.property_name}"


class CurrentResult(models.Model):
    """
    最近一次问答结果（当前表），长表格式。
    每次问答后先删除旧数据再插入新数据（覆盖更新）。
    """
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="current_results",
        help_text="所属对话轮次",
    )
    seq = models.PositiveIntegerField(default=1, help_text="产生该结果的问答轮次序号")
    data_id = models.BigIntegerField(help_text="实体ID")
    title = models.CharField(max_length=255, blank=True, help_text="数据集/样品标题")
    property_name = models.CharField(max_length=255, help_text="属性英文名称（原始名，不加前缀）")
    bitmap_role = models.CharField(max_length=64, blank=True, help_text="属性类别：object / operate / result")
    value_text = models.TextField(blank=True, null=True, help_text="属性值（字符串存储）")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "chat"
        db_table = "chat_current_result"
        indexes = [
            models.Index(fields=["conversation", "data_id"]),
        ]

    def __str__(self):
        return f"CurrentResult[{self.id}] conv={self.conversation_id} seq={self.seq} data={self.data_id}"
