"""
core/data_utils.py
------------------
Helpers shared across multiple Django apps:
  - get_processed_data()
  - extract_tag_ids()
  - format_results()
  - _build_citations()
  - _build_context_block()
Extracted from the original app.py.
"""
import json
import logging
import os
import re

from django.conf import settings

from utils.tag_config import TAG_ID_MAPPING

logger = logging.getLogger(__name__)


def _extract_base_name(abstract_id: str) -> str:
    """
    从 abstract_id 中提取基础文件名。
    规则: 去掉末尾的 '_数字_abstract' 后缀
    """
    base_name = re.sub(r'_\d+_abstract$', '', abstract_id)
    return base_name


def extract_tag_ids(tag_dict: dict) -> dict:
    """Map tag names → tag UUIDs using TAG_ID_MAPPING."""
    tag_ids, tag_names = [], []
    for category, tags in tag_dict.items():
        for tag_name in tags:
            if category in TAG_ID_MAPPING and tag_name in TAG_ID_MAPPING[category]:
                tag_ids.append(TAG_ID_MAPPING[category][tag_name])
                tag_names.append(tag_name)
    return {"ids": tag_ids, "names": tag_names}


def get_processed_data(abstract_id) -> dict | None:
    """Load a processed_<id>.json from data/processed_data/ and enrich it."""
    try:
        base_name = _extract_base_name(abstract_id)
        file_path = settings.DATA_DIR / "processed_data" / f"{base_name}.json"
        if not file_path.exists():
            logger.warning(f"文件不存在: {file_path}")
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "tag_dict" in data:
            tag_info = extract_tag_ids(data["tag_dict"])
            data["tag_ids"] = tag_info["ids"]
            data["tag_names"] = tag_info["names"]
        data.setdefault("category_name", "-")
        data.setdefault("template_name", "-")
        return data
    except Exception as e:
        logger.error(f"读取处理后的数据出错: {e}")
        return None


def format_results(results: list, search_mode: str = "vector") -> list:
    """Enrich raw search hits with metadata and term highlights."""
    from utils.ac_terminology_matcher import highlight_terms  # lazy import to avoid circular

    formatted = []
    for result in results:
        processed_data = None
        tags = []

        if search_mode == "hybrid":
            processed_data = get_processed_data(result["id"])
            if processed_data:
                tags = [
                    {"type": "hybrid_score", "text": f"混合分数: {result['hybrid_score']}%"},
                    {"type": "vector_score", "text": f"向量相似度: {result['vector_score']}%"},
                    {"type": "tfidf_score", "text": f"TF-IDF分数: {result['tfidf_score']}%"},
                    {"type": "id", "text": f"ID: {result['id']}"},
                ]
        elif search_mode == "vector":
            processed_data = get_processed_data(result["id"])
            if processed_data:
                tags = [
                    {"type": "similarity", "text": f"相似度: {result['similarity']:.2f}%"},
                    {"type": "id", "text": f"ID: {result['id']}"},
                ]
        else:  # exact
            processed_data = result.get("processed_data")
            if processed_data:
                tags = [{"type": "id", "text": f"ID: {result['id']}"}]
                for tag_name in processed_data.get("query_tag_names", []):
                    tags.append({"type": "query_tag", "text": f"查询标签: {tag_name}"})
                if "matched_keywords" in result:
                    tags.append({"type": "keywords", "text": f"匹配关键词: {', '.join(result['matched_keywords'])}"})
                if "tfidf_score" in result:
                    tags.append({"type": "tfidf", "text": f"TF-IDF分数: {result['tfidf_score']:.4f}"})

        if not processed_data:
            continue

        tags.extend([
            {"type": "data", "text": f"数据量: {processed_data['num_data']}"},
            {"type": "time", "text": f"添加时间: {processed_data['add_time']}"},
        ])
        tag_dict = processed_data.get("tag_dict", {})
        type_map = {
            "实验表征方法": "characterization",
            "计算模拟方法": "simulation",
            "性能/性质信息": "performance",
            "结构/尺度信息": "structure",
            "工艺制备信息": "preparation",
        }
        for tag_name, tag_value in tag_dict.items():
            tag_type = type_map.get(tag_name, "other")
            label = type_map.get(tag_name, tag_name)
            if tag_type == "other":
                tags.append({"type": "other", "text": f"{tag_name}: {tag_value}"})
            else:
                labels = {"characterization": "表征", "simulation": "模拟", "performance": "性能",
                          "structure": "结构", "preparation": "工艺"}
                tags.append({"type": tag_type, "text": f"{labels[tag_type]}: {tag_value}"})

        fr = {
            "id": result["id"],
            "title": processed_data["name"],
            "abstract": result.get("abstract", ""),
            "count": processed_data["num_data"],
            "tags": tags,
            "category": processed_data.get("category_name", "-"),
            "template": processed_data.get("template_name", "-"),
        }
        try:
            fr["highlight_title"] = highlight_terms(processed_data["name"])
            fr["highlight_abstract"] = highlight_terms(result.get("abstract", ""))
        except Exception as e:
            logger.warning(f"术语高亮失败: {e}")
            fr["highlight_title"] = processed_data["name"]
            fr["highlight_abstract"] = result.get("abstract", "")

        formatted.append(fr)
    return formatted


def build_citations(results: list, search_mode: str, max_citations: int = 5) -> list:
    citations = []
    for idx, r in enumerate(results[:max_citations]):
        doc_id = r.get("id")
        if search_mode == "hybrid":
            score = r.get("hybrid_score")
        elif search_mode == "vector":
            score = r.get("similarity")
        else:
            score = r.get("tfidf_score")
        processed = get_processed_data(doc_id)
        title = processed["name"] if processed else f"数据集 {doc_id}"
        citations.append({
            "index": idx + 1,
            "id": doc_id,
            "title": title,
            "score": score,
            "abstract": r.get("abstract", ""),
        })
    return citations


def build_context_block(citations: list, max_chars: int = 800) -> str:
    lines = []
    for c in citations:
        abstract = (c.get("abstract") or "")[:max_chars]
        if len(c.get("abstract", "")) > max_chars:
            abstract += "..."
        lines.append(f"【{c['index']}】标题: {c['title']}\n摘要: {abstract}")
    return "\n\n".join(lines)
