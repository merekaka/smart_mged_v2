from django.urls import path
from .views import TermExplanationView

urlpatterns = [
    path("term_explanation", TermExplanationView.as_view(), name="term-explanation"),
]
