"""
后端查询增强客户端

在 szl.intent_sql_executor 的纯 SQL 执行能力之上，封装"查询 + 详情回填"的完整流程。

设计原则（加法优先）：
- intent_sql_executor.py 保持纯粹，只负责生成/执行 SQL，返回 data_id 列表。
- 本模块独立负责：根据 data_id 列表反查 smart_mged.result 表，返回分类格式 + 宽表格式。
- 调用方可按需选择：
    • run_from_intent()          — 只拿 data_id（executor 原生）
    • query_with_details()       — 拿完整记录（本模块）
    • fetch_results_with_details() — 便捷函数，直接返回 (records, total)
    • fetch_full_result()        — 返回完整 result dict（含 classified / wide 双格式）
"""

import logging
from typing import List, Dict, Any, Tuple

from szl.intent_sql_executor import run_from_intent
from .result_fetcher import fetch_result_classified_and_wide

logger = logging.getLogger(__name__)


def query_with_details(intent_dict: dict, original_query: str = "") -> Dict[str, Any]:
    """
    执行意图查询，并在结果中自动回填 result 表详情。

    返回结构与 run_from_intent 完全一致，但 answer 中额外包含：
        - records: List[Dict]  宽表格式的完整记录（供 follow-up / ResultStore 使用）
        - classified_records: List[Dict]  分类格式（供前端卡片展示）
    """
    logger.info(f"query_with_details: original_query={original_query[:100]!r}, intent_mode={intent_dict.get('query_mode')}")
    result = run_from_intent(intent_dict, original_query=original_query)
    answer = result.get("answer", {})
    data_ids = answer.get("matched_data_ids", [])
    total = answer.get("total", 0)
    logger.info(f"query_with_details: executor returned total={total}, data_ids={len(data_ids)}")

    if data_ids:
        try:
            detail = fetch_result_classified_and_wide(data_ids)
            answer["records"] = detail["wide"]
            answer["classified_records"] = detail["classified"]
            logger.info(f"query_with_details: detail fetch success, wide={len(detail['wide'])}, classified={len(detail['classified'])}")
        except Exception as exc:
            logger.warning(f"query_with_details: detail fetch failed (data_ids={len(data_ids)}): {exc}")
            # fallback：保持 data_id 列表，前端可降级展示
            answer["records"] = [{"data_id": did} for did in data_ids]
            answer["classified_records"] = [{"data_id": did, "title": "", "object": {}, "operate": {}, "result": {}} for did in data_ids]

    return result


def fetch_results_with_details(intent_dict: dict, original_query: str = "") -> Tuple[List[Dict[str, Any]], int]:
    """
    便捷入口：直接返回 (records_list, total)。

    records 为宽表记录；若回填失败，则 fallback 到 [{"data_id": did}] 旧格式。
    """
    logger.info(f"fetch_results_with_details: original_query={original_query[:100]!r}")
    result = query_with_details(intent_dict, original_query=original_query)
    answer = result.get("answer", {})
    total = answer.get("total", 0)

    records = answer.get("records", [])
    if not records:
        data_ids = answer.get("matched_data_ids", [])
        records = [{"data_id": did} for did in data_ids]

    logger.info(f"fetch_results_with_details: returning records={len(records)}, total={total}")
    return records, total


def fetch_full_result(intent_dict: dict, original_query: str = "") -> Dict[str, Any]:
    """
    返回 intent_sql_executor 的完整结果（含 SQL 信息 + 双格式记录）。

    返回结构：
    {
        "sql": "...",
        "sql_params": [...],
        "sql_rendered": "...",
        "answer": {
            "matched_data_ids": [...],
            "total": N,
            "aggregations": [...],
            "records": [...],           # 宽表记录（供 follow-up）
            "classified_records": [...] # 分类记录（供前端卡片展示）
        },
        ...
    }
    """
    logger.info(f"fetch_full_result: original_query={original_query[:100]!r}")
    result = query_with_details(intent_dict, original_query=original_query)
    return result
