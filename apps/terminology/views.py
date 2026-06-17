"""
apps/terminology/views.py
--------------------------
Django view for:
  GET /api/terminology/term_explanation?term=<term>
"""
import logging

from django.http import JsonResponse
from django.views import View

from utils.ac_terminology_matcher import get_term_explanation

logger = logging.getLogger(__name__)


class TermExplanationView(View):
    """GET /api/terminology/term_explanation"""

    def get(self, request):
        try:
            term = request.GET.get("term")
            if not term:
                return JsonResponse({"error": "Term parameter is required"}, status=400)
            explanation = get_term_explanation(term)
            if explanation:
                return JsonResponse({"term": term, "explanation": explanation})
            return JsonResponse({"error": f'Term "{term}" not found'}, status=404)
        except Exception as e:
            logger.error(f"TermExplanationView error: {e}")
            return JsonResponse({"error": str(e)}, status=500)
