"""
apps/datasets/views.py
-----------------------
Django views for:
  POST /api/datasets/filter       → DatasetFilterView
  POST /api/datasets/full_rows    → FullRowsView
"""
import json
import logging
import os
import requests

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.conf import settings

logger = logging.getLogger(__name__)


def _advanced_error(message: str, status: int = 200):
    """Return frontend-compatible error payload for details panel."""
    return JsonResponse(
        {
            "code": 1,
            "message": message,
            "data": {"rows": [], "num_data": 0, "num_pages": 0},
        },
        status=status,
    )


@method_decorator(csrf_exempt, name="dispatch")
class DatasetFilterView(View):
    """POST /api/datasets/filter"""

    def post(self, request):
        try:
            body = json.loads(request.body)
            if not body:
                return JsonResponse({"error": "请求体不能为空"}, status=400)

            dataset_id = body.get("dataset_id")
            filter_requirements = body.get("filter_requirements")

            if not dataset_id:
                return JsonResponse({"error": "dataset_id参数是必需的"}, status=400)
            if not filter_requirements:
                return JsonResponse({"error": "filter_requirements参数是必需的"}, status=400)

            logger.info(f"数据集筛选 - ID: {dataset_id}, 需求: {filter_requirements}")

            import sys
            sys.path.insert(0, str(settings.SZL_DIR))
            from data_query_service import query_dataset_data

            result = query_dataset_data(dataset_id, filter_requirements)

            if result["success"]:
                return JsonResponse({
                    "success": True,
                    "message": "筛选成功",
                    "data": result["data"],
                    "metadata": {
                        "dataset_id": dataset_id,
                        "filter_requirements": filter_requirements,
                        "total_count": result["total_count"],
                        "es_query": result.get("es_query", {}),
                        "query_metadata": result.get("metadata", {}),
                    },
                })
            return JsonResponse({"success": False, "error": result.get("error", "筛选失败"), "data": []}, status=500)

        except Exception as e:
            logger.error(f"DatasetFilterView error: {e}")
            return JsonResponse({"success": False, "error": f"筛选过程中发生错误: {e}", "data": []}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class FullRowsView(View):
    """POST /api/datasets/full_rows"""

    def post(self, request):
        try:
            body = json.loads(request.body)
            id_list = body.get("id_list", [])

            all_data_path = settings.SZL_DIR / "all_data.json"
            with open(all_data_path, "r", encoding="utf-8") as f:
                all_data = json.load(f)

            if isinstance(all_data, dict):
                all_data = list(all_data.values())

            id_set = {str(i) for i in id_list}
            full_rows = [row for row in all_data if str(row.get("id")) in id_set]
            return JsonResponse({"success": True, "data": full_rows})

        except Exception as e:
            logger.error(f"FullRowsView error: {e}")
            return JsonResponse({"success": False, "error": str(e)}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class DatasetAdvancedView(View):
    """POST /api/datasets/advanced

    Proxy remote dataset advanced endpoint to avoid browser-side CORS failures.
    """

    def post(self, request):
        try:
            body = json.loads(request.body or "{}")
            dataset_id = body.get("dataset_id")
            if not dataset_id:
                return _advanced_error("dataset_id参数是必需的", status=400)

            payload = {
                "page": int(body.get("page", 1)),
                "page_size": int(body.get("page_size", 5)),
                "query": body.get("query", ""),
                "sort": body.get("sort", ""),
            }

            # Keep this endpoint lightweight; do not import heavy SZL dependencies.
            base_url = os.getenv(
                "DATASET_PORTAL_BASE_URL",
                "http://223.223.185.189:12027/api/portal/datasets/",
            )
            username = os.getenv("DATASET_PORTAL_USERNAME", "admin")
            password = os.getenv("DATASET_PORTAL_PASSWORD", "C_gW9ziT8P-hfBL_c4J4tzATu")

            url = f"{base_url}{dataset_id}/advanced"
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                auth=(username, password),
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            return JsonResponse(data, safe=False)

        except requests.RequestException as e:
            upstream = ""
            if getattr(e, "response", None) is not None:
                upstream = f"; status={e.response.status_code}; body={e.response.text[:200]}"
            logger.error(f"DatasetAdvancedView upstream error: {e}{upstream}", exc_info=True)
            return _advanced_error(f"上游服务请求失败: {e}")
        except Exception as e:
            logger.error(f"DatasetAdvancedView error: {e}", exc_info=True)
            return _advanced_error(f"服务内部错误: {e}")
