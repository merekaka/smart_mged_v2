from django.http import Http404
from django.shortcuts import render


ALLOWED_FRONTEND_PAGES = {
    "intent_chat.html",   # 意图理解对话页面
}


def frontend_index(request):
    return render(request, "frontend/intent_chat.html")


def frontend_page(request, page: str):
    if page not in ALLOWED_FRONTEND_PAGES:
        raise Http404("Page not found")
    return render(request, f"frontend/{page}")
