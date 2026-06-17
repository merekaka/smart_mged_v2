"""
多轮追问引擎 - URL路由（可选）
当前追问入口统一通过 chat 模块的 /api/chat/conversations/<id>/messages 处理，
此处预留独立路由供后续扩展。
"""
from django.urls import path

urlpatterns = [
    # 预留：如后续需要独立追问接口可在此添加
]
