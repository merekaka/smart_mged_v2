"""
原始数据加载器

根据 data_id（即 _meta_id）从 data/ 目录下的 JSON 文件中加载原始未处理数据。

使用方法:
    from apps.chat.raw_data_loader import load_raw_data_by_meta_id

    raw_data = load_raw_data_by_meta_id(14187895)
    # 返回原始 JSON 记录，包含 _id, _meta_id, _tid, data, title 等字段
"""
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# 项目根目录
BASE_DIR = Path(__file__).resolve().parents[2]

# 索引文件路径
INDEX_PATH = BASE_DIR / "data" / "raw_data_index.json"

# 缓存的索引数据
_index_cache: Optional[Dict[str, Any]] = None


def _load_index() -> Dict[str, Any]:
    """加载索引文件（带缓存）。"""
    global _index_cache
    if _index_cache is not None:
        return _index_cache

    if not INDEX_PATH.exists():
        logger.warning(f"原始数据索引文件不存在: {INDEX_PATH}")
        _index_cache = {}
        return _index_cache

    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            _index_cache = json.load(f)
        logger.info(f"原始数据索引加载完成: {len(_index_cache)} 条记录")
    except Exception as e:
        logger.error(f"加载原始数据索引失败: {e}")
        _index_cache = {}

    return _index_cache


def load_raw_data_by_meta_id(meta_id: int) -> Optional[Dict[str, Any]]:
    """
    根据 _meta_id（即前端的 data_id）加载原始 JSON 数据。

    :param meta_id: 数据的 _meta_id
    :return: 原始 JSON 记录（包含 _id, _meta_id, _tid, data, title），未找到返回 None
    """
    index = _load_index()
    key = str(meta_id)

    if key not in index:
        logger.warning(f"原始数据中未找到 _meta_id={meta_id}")
        return None

    entry = index[key]
    file_path = BASE_DIR / entry["file"]
    array_index = entry["index"]

    if not file_path.exists():
        logger.warning(f"原始数据文件不存在: {file_path}")
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list) or array_index >= len(data):
            logger.warning(f"原始数据文件格式错误或索引越界: {file_path}, index={array_index}")
            return None

        return data[array_index]

    except Exception as e:
        logger.error(f"读取原始数据失败 (_meta_id={meta_id}): {e}")
        return None


def reload_index() -> None:
    """强制重新加载索引（用于索引更新后）。"""
    global _index_cache
    _index_cache = None
    _load_index()
