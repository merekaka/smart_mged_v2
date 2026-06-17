"""
多轮追问引擎 (Follow-up Engine)
--------------------------------
处理对话中的后续追问，基于已有结果集进行意图解析、SQL 过滤和回答生成。

其他模块可通过导入使用:
    from apps.follow_up.services import process_follow_up
    result = process_follow_up(conversation_id, user_text)
"""

default_app_config = 'apps.follow_up.apps.FollowUpConfig'
