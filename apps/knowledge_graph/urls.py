from django.urls import path
from .views import RecommendView, TermGraphView

urlpatterns = [
    path("recommend",  RecommendView.as_view(), name="graph-recommend"),
    path("term_graph", TermGraphView.as_view(), name="graph-term"),
]
