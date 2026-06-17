from django.urls import path, include, re_path
from config.frontend_views import frontend_index, frontend_page

urlpatterns = [
    # 意图理解对话页面（默认首页）
    path('', frontend_page, kwargs={'page': 'intent_chat.html'}, name='frontend-index'),
    
    # API接口
    path('api/search/',       include('apps.search.urls')),
    # 知识图谱问答API
    path('api/graph/',        include('apps.graph.urls')),
    path('api/terminology/',  include('apps.terminology.urls')),
    path('api/chat/',         include('apps.chat.urls')),
    path('api/datasets/',     include('apps.datasets.urls')),
    # 新增：意图理解引擎API
    path('api/intent/',       include('apps.intent_engine.urls')),
    
    # 前端页面
    re_path(r'^(?P<page>[A-Za-z0-9_\-]+\.html)$', frontend_page, name='frontend-page'),
]
