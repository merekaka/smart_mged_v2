"""
apps/search/services.py
-----------------------
Business logic for vector search.
[修改说明：仅保留向量搜索，精确搜索和混合搜索已注释]
"""
import logging
import time

import numpy as np
import torch
import torch.nn.functional as F

from core.model_loader import get_model, get_data

logger = logging.getLogger(__name__)


def vector_search(question: str, index, model, abstracts: list, abstract_ids: list,
                  k: int = 20, target_ids=None):
    """
    向量搜索 - 核心功能
    """
    try:
        total_start = time.time()
        logger.info(f"向量搜索 - 问题: {question}, k={k}")

        # 编码查询
        encode_start = time.time()
        if "UniME" in str(type(model).__name__):
            text_prompt = "<|user|>\n<sent>\nSummary above sentence in one word: <|end|>\n<|assistant|>\n"
            input_texts = text_prompt.replace("<sent>", question)
            inputs = model.processor(text=input_texts, images=None, return_tensors="pt", padding=True)
            for key in inputs:
                inputs[key] = inputs[key].to("cuda")
            with torch.no_grad():
                outputs = model(**inputs, output_hidden_states=True, return_dict=True)
                q_emb = outputs.hidden_states[-1][:, -1, :]
                q_emb = F.normalize(q_emb, dim=-1)
                question_embedding = q_emb.cpu().numpy().astype("float32").reshape(-1)
        else:
            model_dim = model.get_sentence_embedding_dimension()
            if model_dim != index.d:
                raise ValueError(f"模型维度 ({model_dim}) 与索引维度 ({index.d}) 不匹配")
            question_embedding = model.encode([question], batch_size=1)[0]
            question_embedding = (question_embedding / np.linalg.norm(question_embedding)).astype("float32")

        encode_time = time.time() - encode_start

        # 搜索
        search_start = time.time()
        results = []

        if target_ids is not None:
            target_indices = [i for i, did in enumerate(abstract_ids) if did in target_ids]
            if not target_indices:
                return [], {"total_time": 0, "encode_time": encode_time, "search_time": 0}
            target_vectors = index.reconstruct_batch(target_indices)
            similarities = np.dot(target_vectors, question_embedding)
            top_k_indices = np.argsort(similarities)[-k:][::-1]
            for idx in top_k_indices:
                doc_idx = target_indices[idx]
                results.append({
                    "id": abstract_ids[doc_idx],
                    "similarity": round(float(100 * similarities[idx]), 2),
                    "abstract": abstracts[doc_idx],
                    "rank": len(results) + 1,
                })
        else:
            q_vec = question_embedding.reshape(1, -1)
            if q_vec.shape[1] != index.d:
                raise ValueError(f"查询向量维度 ({q_vec.shape[1]}) 与索引维度 ({index.d}) 不匹配")
            distances, indices = index.search(q_vec, k)
            for i, (idx, dist) in enumerate(zip(indices[0], distances[0])):
                if idx < 0 or idx >= len(abstract_ids):
                    continue
                doc_id = abstract_ids[idx]
                results.append({
                    "id": doc_id,
                    "similarity": round(float(100 * dist), 2),
                    "abstract": abstracts[idx],
                    "rank": i + 1,
                    "category": "-",
                    "template": "-",
                })

        search_time = time.time() - search_start
        total_time = time.time() - total_start
        return results, {"total_time": total_time, "encode_time": encode_time, "search_time": search_time}

    except Exception as e:
        logger.error(f"向量搜索出错: {e}", exc_info=True)
        return [], {"total_time": 0, "encode_time": 0, "search_time": 0}


# # ---------------------------------------------------------------------------
# # 以下是与精确搜索(TF-IDF)和混合搜索相关的函数，已注释
# # ---------------------------------------------------------------------------
#
# from collections import defaultdict
# from django.conf import settings
# from core.inverted_index import get_inverted_index
# from core.data_utils import get_processed_data
# from utils.tag_config import TAG_ID_MAPPING
#
# def extract_tags_from_query(query: str) -> dict:
#     """标签提取 - 已注释"""
#     tag_ids, tag_names = [], []
#     for tags in TAG_ID_MAPPING.values():
#         for tag_name, tag_id in tags.items():
#             if tag_name in query:
#                 tag_ids.append(tag_id)
#                 tag_names.append(tag_name)
#                 break
#     return {"ids": tag_ids, "names": tag_names}
#
#
# def exact_search(query: str, abstract_mode: str = "own", topk: int = 20) -> list:
#     """精确搜索(TF-IDF) - 已注释"""
#     try:
#         index = get_inverted_index(abstract_mode)
#         query_tags = extract_tags_from_query(query)
#         keywords, keyword_matches = index.process_query(query)
#
#         doc_scores: dict = defaultdict(float)
#         for kw, match_info in keyword_matches.items():
#             for doc_id, score in match_info["document_scores"]:
#                 doc_scores[doc_id] += score
#
#         sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
#
#         results = []
#         data_dir = settings.DATA_DIR
#         for doc_id, total_score in sorted_docs[:topk]:
#             processed = get_processed_data(doc_id)
#             if not processed:
#                 continue
#
#             if abstract_mode == "external":
#                 abs_fp = data_dir / "dataset_abstract" / f"abstract_{doc_id}.txt"
#                 if abs_fp.exists():
#                     with open(abs_fp, "r", encoding="utf-8") as f:
#                         abstract = f.read()
#                 else:
#                     abstract = processed.get("abstract", "")
#             else:
#                 abstract = processed.get("abstract", "")
#
#             processed["query_tag_ids"] = query_tags["ids"]
#             processed["query_tag_names"] = query_tags["names"]
#
#             matched_kws = [
#                 kw for kw, mi in keyword_matches.items()
#                 if any(doc_id == d[0] for d in mi["document_scores"])
#             ]
#             results.append({
#                 "id": doc_id,
#                 "name": processed["name"],
#                 "abstract": abstract,
#                 "processed_data": processed,
#                 "matched_keywords": matched_kws,
#                 "tfidf_score": total_score,
#                 "category": processed.get("category_name", "-"),
#                 "template": processed.get("template_name", "-"),
#             })
#
#         return results
#     except Exception as e:
#         logger.error(f"精确搜索出错: {e}")
#         return []
#
#
# def hybrid_search(query: str, model_name: str = "m3e-base", topk: int = 50,
#                   abstract_mode: str = "own", hybrid_weight: float = 0.5):
#     """混合搜索 - 已注释"""
#     try:
#         total_start = time.time()
#         faiss_index, abstract_ids, abstracts = get_data(model_name, abstract_mode)
#         model = get_model(model_name)
#
#         exact_results = exact_search(query, abstract_mode=abstract_mode, topk=topk)
#
#         if not exact_results:
#             logger.warning("精确搜索无结果，回退到向量搜索")
#             vec_results, timing = vector_search(query, faiss_index, model, abstracts, abstract_ids, k=topk)
#             hybrid_results = [
#                 {
#                     "id": r["id"],
#                     "hybrid_score": r["similarity"],
#                     "vector_score": r["similarity"],
#                     "tfidf_score": 0,
#                     "abstract": r["abstract"],
#                     "rank": r["rank"],
#                     "category": r.get("category", "-"),
#                     "template": r.get("template", "-"),
#                 }
#                 for r in vec_results
#             ]
#             return hybrid_results, timing
#
#         candidate_ids = [r["id"] for r in exact_results]
#         tfidf_scores = {r["id"]: r["tfidf_score"] for r in exact_results}
#
#         vec_results, timing = vector_search(
#             query, faiss_index, model, abstracts, abstract_ids,
#             k=len(candidate_ids), target_ids=candidate_ids,
#         )
#
#         tfidf_min = min(tfidf_scores.values()) if tfidf_scores else 0
#         tfidf_max = max(tfidf_scores.values()) if tfidf_scores else 0
#         tfidf_range = tfidf_max - tfidf_min if tfidf_max != tfidf_min else 0
#
#         hybrid_results = []
#         for r in vec_results:
#             doc_id = r["id"]
#             vec_score = r["similarity"] / 100.0
#             raw_tfidf = tfidf_scores.get(doc_id, 0)
#             processed = get_processed_data(doc_id)
#             if not processed:
#                 continue
#             tfidf_norm = (raw_tfidf - tfidf_min) / tfidf_range if tfidf_range > 0 else 1
#             hybrid_score = hybrid_weight * vec_score + (1 - hybrid_weight) * tfidf_norm
#             hybrid_results.append({
#                 "id": doc_id,
#                 "hybrid_score": round(hybrid_score * 100, 2),
#                 "vector_score": r["similarity"],
#                 "tfidf_score": round(tfidf_norm * 100, 2),
#                 "abstract": r["abstract"],
#                 "rank": len(hybrid_results) + 1,
#                 "category": processed.get("category_name", "-"),
#                 "template": processed.get("template_name", "-"),
#             })
#
#         hybrid_results.sort(key=lambda x: x["hybrid_score"], reverse=True)
#         hybrid_results = hybrid_results[:topk]
#         timing["total_time"] = time.time() - total_start
#         return hybrid_results, timing
#
#     except Exception as e:
#         logger.error(f"混合搜索出错: {e}", exc_info=True)
#         return [], {"total_time": 0, "encode_time": 0, "search_time": 0}
