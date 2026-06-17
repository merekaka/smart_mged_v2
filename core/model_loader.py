"""
core/model_loader.py
--------------------
Singleton helpers for loading/caching embedding models and FAISS indices.
Extracted from the original app.py.
"""
import logging
import os
import json
import re

import numpy as np
import torch
import faiss
from sentence_transformers import SentenceTransformer

from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (mirroring the Flask global variables)
# ---------------------------------------------------------------------------
_model = None
_index = None
_abstract_ids = None
_abstracts = None
_current_model = None
_current_abstract_mode = None

def _extract_base_name(abstract_id: str) -> str:
    """
    从 abstract_id 中提取基础文件名。
    规则: 去掉末尾的 '_数字_abstract' 后缀
    """
    base_name = re.sub(r'_\d+_abstract$', '', abstract_id)
    return base_name
def get_model(model_name: str = "m3e-base"):
    """Return a (cached) embedding model instance."""
    global _model, _current_model

    if _current_model == model_name and _model is not None:
        return _model

    logger.info(f"加载模型: {model_name}")
    if _model is not None:
        logger.info(f"释放旧模型: {_current_model}")
        del _model
        _model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_cfg = settings.MODEL_CONFIGS[model_name]

    if model_name == "UniME-Phi3.5-V-4.2B":
        from modelscope import AutoProcessor, AutoModelForCausalLM
        processor = AutoProcessor.from_pretrained(
            model_cfg["path"], trust_remote_code=True
        )
        processor.tokenizer.padding_side = "left"
        processor.tokenizer.padding = True
        _model = AutoModelForCausalLM.from_pretrained(
            model_cfg["path"],
            device_map=device,
            torch_dtype=torch.float16,
            trust_remote_code=True,
            _attn_implementation="eager",
        )
        _model.processor = processor
    else:
        _model = SentenceTransformer(
            model_cfg["path"],
            device=device,
            trust_remote_code=model_cfg["trust_remote_code"],
        )
        _model.max_seq_length = model_cfg["max_seq_length"]

    _current_model = model_name
    logger.info(f"模型加载完成: {model_name}")
    return _model


def get_data(model_name: str, abstract_mode: str = "external"):
    """Return (faiss_index, abstract_ids, abstracts), loading once per combination."""
    global _index, _abstract_ids, _abstracts, _current_model, _current_abstract_mode

    if (
        _index is not None
        and _abstract_ids is not None
        and _abstracts is not None
        and _current_model == model_name
        and _current_abstract_mode == abstract_mode
    ):
        return _index, _abstract_ids, _abstracts

    logger.info(f"加载索引数据 - 模型: {model_name}, 摘要模式: {abstract_mode}")

    # Ensure model is loaded first
    get_model(model_name)

    vdb = settings.VECTOR_DATABASE_DIR
    data_dir = settings.DATA_DIR

    if abstract_mode == "own":
        index_file = vdb / "abstract_faiss" / f"processed_index_{model_name}_normalized.faiss"
        ids_file   = vdb / "abstract_ids"   / f"processed_abstract_ids_{model_name}_normalized.json"
    else:
        index_file = vdb / "abstract_faiss" / f"index_{model_name}_normalized.faiss"
        ids_file   = vdb / "abstract_ids"   / f"ids_{model_name}_normalized.json"

    if not os.path.exists(index_file):
        raise FileNotFoundError(f"索引文件不存在: {index_file}")
    _index = faiss.read_index(str(index_file))
    logger.info("FAISS 索引加载完成")

    if not os.path.exists(ids_file):
        raise FileNotFoundError(f"ID文件不存在: {ids_file}")
    with open(ids_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        _abstract_ids = data["ids"]  # 取出 "ids" 键对应的列表
    logger.info(f"ID 列表加载完成，共 {len(_abstract_ids)} 条")
    _abstracts = []
    processed_dir = data_dir / "processed_data"
    abstract_dir  = data_dir / "abstracts"
    for abstract_id in _abstract_ids:
        base_name = _extract_base_name(abstract_id)
        if abstract_mode == "own":
            fp = processed_dir / f"{base_name}.json"
            if not fp.exists():
                logger.warning(f"处理后的文件不存在: {fp}")
                _abstracts.append("")
                continue
            with open(fp, "r", encoding="utf-8") as f:
                d = json.load(f)
            _abstracts.append(d.get("abstract", ""))
        else:
            fp = abstract_dir / f"{abstract_id}.md"
            if not fp.exists():
                logger.warning(f"摘要文件不存在: {fp}")
                _abstracts.append("")
                continue
            with open(fp, "r", encoding="utf-8") as f:
                _abstracts.append(f.read())

    _current_abstract_mode = abstract_mode
    logger.info(f"摘要内容加载完成，共 {len(_abstracts)} 条")
    return _index, _abstract_ids, _abstracts
