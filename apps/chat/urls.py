from django.urls import path
from .views import (
    ConversationListCreateView,
    ConversationEmptyView,
    ConversationInitView,
    ConversationDetailView,
    ConversationClearView,
    MessageCreateView,
    DataDetailView,
)

urlpatterns = [
    # 对话轮次管理
    path("conversations", ConversationListCreateView.as_view(), name="chat-conversations"),
    # 清空所有对话（必须放在带参数的路由之前，避免被 <int:conversation_id> 匹配）
    path(
        "conversations/clear",
        ConversationClearView.as_view(),
        name="chat-conversations-clear",
    ),
    # 创建空对话轮次（必须放在 <int:conversation_id> 之前）
    path(
        "conversations/empty",
        ConversationEmptyView.as_view(),
        name="chat-conversations-empty",
    ),
    path(
        "conversations/<int:conversation_id>",
        ConversationDetailView.as_view(),
        name="chat-conversation-detail",
    ),
    # 对空对话执行首轮意图理解
    path(
        "conversations/<int:conversation_id>/init",
        ConversationInitView.as_view(),
        name="chat-conversation-init",
    ),
    # 在某轮对话中继续问答
    path(
        "conversations/<int:conversation_id>/messages",
        MessageCreateView.as_view(),
        name="chat-messages",
    ),
    # 单条数据详情（点击 data_id 弹窗用）
    path(
        "data_detail/<int:data_id>",
        DataDetailView.as_view(),
        name="chat-data-detail",
    ),
]
