#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图谱词汇表预构建脚本

功能：
1. 检查 apps/graph/cache/ 目录下是否已有词汇表缓存
2. 如果已存在，确认缓存有效后退出
3. 如果不存在，从 Neo4j 拉取实体并预计算 Embedding，保存到本地缓存

用法：
    python tools/build_graph_vocab_cache.py
    python tools/build_graph_vocab_cache.py --force  # 强制重建缓存
"""

import os
import sys
import json
import argparse
import numpy as np
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

# 设置 stdout 编码为 utf-8，避免 Windows 终端中文乱码
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

# ================= 配置 =================
# 项目根目录（本脚本位于 tools/ 目录下）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Neo4j 连接配置（从环境变量读取，优先于硬编码默认值）
NEO4J_URI = os.environ.get("NEO4J_URL", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "CHANGE_ME_IN_PRODUCTION")

# 本地向量模型路径
EMBEDDING_MODEL_PATH = os.path.join(PROJECT_ROOT, "llm", "bge-m3")
EMBEDDING_DEVICE = "cpu"

# 缓存目录
VOCAB_CACHE_DIR = os.path.join(PROJECT_ROOT, "apps", "graph", "cache")
VOCAB_FILE = os.path.join(VOCAB_CACHE_DIR, "graph_vocabulary.json")
EMBEDDING_FILE = os.path.join(VOCAB_CACHE_DIR, "graph_embeddings.npy")

# Cypher 查询：提取所有实体名称
CYPHER_QUERY = """
MATCH (n)
WHERE (n:Term OR n:Classification) AND n.name IS NOT NULL
RETURN DISTINCT n.name AS entity_name
"""


def check_cache_exists():
    """检查缓存文件是否都已存在且非空"""
    if not os.path.exists(VOCAB_FILE):
        return False, f"词汇表文件不存在: {VOCAB_FILE}"
    if not os.path.exists(EMBEDDING_FILE):
        return False, f"向量文件不存在: {EMBEDDING_FILE}"
    if os.path.getsize(VOCAB_FILE) == 0:
        return False, f"词汇表文件为空: {VOCAB_FILE}"
    if os.path.getsize(EMBEDDING_FILE) == 0:
        return False, f"向量文件为空: {EMBEDDING_FILE}"
    return True, "缓存文件已存在且非空"


def verify_cache_integrity():
    """验证缓存的一致性：词汇表长度与向量矩阵行数是否匹配"""
    try:
        with open(VOCAB_FILE, 'r', encoding='utf-8') as f:
            vocab = json.load(f)
        embeddings = np.load(EMBEDDING_FILE)

        vocab_len = len(vocab)
        embed_rows = embeddings.shape[0]

        if vocab_len == embed_rows:
            return True, f"缓存有效: {vocab_len} 个实体, 向量维度 {embeddings.shape[1]}"
        else:
            return False, f"缓存不一致: 词汇表 {vocab_len} 个, 向量矩阵 {embed_rows} 行"
    except Exception as e:
        return False, f"缓存验证失败: {e}"


def build_and_cache_vocabulary():
    """从 Neo4j 构建词汇表并保存到本地缓存"""
    print("[系统日志] 正在连接 Neo4j 数据库...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    print("[系统日志] 正在提取全量实体名称...")
    all_entities = []
    with driver.session() as session:
        results = session.run(CYPHER_QUERY)
        for record in results:
            all_entities.append(record["entity_name"])
    driver.close()

    print(f"[系统日志] 提取完成，共计 {len(all_entities)} 个全局实体。")

    print(f"[系统日志] 正在加载本地向量模型 ({EMBEDDING_MODEL_PATH})...")
    embedding_model = SentenceTransformer(
        model_name_or_path=EMBEDDING_MODEL_PATH,
        device=EMBEDDING_DEVICE
    )

    print("[系统日志] 正在为全量实体预计算向量表示 (这可能需要 1-2 分钟)...")
    embeddings = embedding_model.encode(all_entities, show_progress_bar=True)

    print("[系统日志] 正在将词表与向量序列化保存至本地缓存...")
    os.makedirs(VOCAB_CACHE_DIR, exist_ok=True)

    with open(VOCAB_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_entities, f, ensure_ascii=False, indent=2)

    np.save(EMBEDDING_FILE, embeddings)

    print(f"[系统日志] 全局向量索引构建并缓存完成。")
    print(f"  - 词汇表: {VOCAB_FILE}")
    print(f"  - 向量矩阵: {EMBEDDING_FILE}")
    print(f"  - 实体数量: {len(all_entities)}")
    print(f"  - 向量维度: {embeddings.shape[1]}")


def main():
    parser = argparse.ArgumentParser(description="图谱词汇表预构建工具")
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="强制重建缓存，忽略已有缓存"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("图谱词汇表缓存构建工具")
    print("=" * 60)

    # 1. 检查缓存是否存在
    exists, msg = check_cache_exists()
    print("[检查] 缓存文件已存在且非空")

    if exists and not args.force:
        # 2. 验证缓存完整性
        valid, verify_msg = verify_cache_integrity()
        print(f"[验证] {verify_msg}")
        if valid:
            print("\n 词汇表缓存已就绪，无需重建。")
            sys.exit(0)
        else:
            print("\n 缓存损坏，将重新构建...")
    elif exists and args.force:
        print("\n 强制重建模式，将忽略已有缓存并重新构建...")

    # 3. 构建并保存缓存
    build_and_cache_vocabulary()

    # 4. 再次验证
    valid, verify_msg = verify_cache_integrity()
    print(f"\n[验证] {verify_msg}")
    if valid:
        print(" 词汇表缓存构建成功！")
    else:
        print(" 缓存构建后验证失败，请检查日志。")
        sys.exit(1)


if __name__ == "__main__":
    main()
