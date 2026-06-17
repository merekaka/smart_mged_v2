from django.urls import path
from .views import QueryView, HealthView, ModelsView, IndexInfoView, QueryKeywordsView

urlpatterns = [
    path("query",          QueryView.as_view(),         name="search-query"),
    path("health",         HealthView.as_view(),         name="search-health"),
    path("models",         ModelsView.as_view(),         name="search-models"),
    path("index_info",     IndexInfoView.as_view(),      name="search-index-info"),
    path("query_keywords", QueryKeywordsView.as_view(),  name="search-query-keywords"),
]
