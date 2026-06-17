from django.urls import path
from .views import DatasetFilterView, FullRowsView, DatasetAdvancedView

urlpatterns = [
    path("advanced",  DatasetAdvancedView.as_view(), name="dataset-advanced"),
    path("filter",    DatasetFilterView.as_view(), name="dataset-filter"),
    path("full_rows", FullRowsView.as_view(),      name="dataset-full-rows"),
]
