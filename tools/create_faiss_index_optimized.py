"""
Optimized FAISS index builder for bge-m3 with progress saving and resume support.
Splits work into chunks to avoid timeout issues.
"""
import os
import sys
import json
import time
from pathlib import Path
import numpy as np

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from django.conf import settings

try:
    import faiss
except Exception:
    print('ERROR: faiss 未安装，请先 pip install faiss-cpu（或 faiss-gpu）')
    sys.exit(2)

# 配置
MODEL_NAME = 'bge-m3'
if len(sys.argv) > 1:
    MODEL_NAME = sys.argv[1]

EMB_DIR = Path(settings.VECTOR_DATABASE_DIR) / 'abstract_embeddings'
OUT_FAISS_DIR = Path(settings.VECTOR_DATABASE_DIR) / 'abstract_faiss'
OUT_IDS_DIR = Path(settings.VECTOR_DATABASE_DIR) / 'abstract_ids'

OUT_FAISS_DIR.mkdir(parents=True, exist_ok=True)
OUT_IDS_DIR.mkdir(parents=True, exist_ok=True)

emb_path = EMB_DIR / f'{MODEL_NAME}_abstract_embeddings.npy'
ids_path = EMB_DIR / f'{MODEL_NAME}_abstract_ids.json'

# 分块配置
CHUNK_SIZE = 2000  # 每批处理 2000 条，保存一次中间结果
BATCH_SIZE = 32    # 模型编码 batch size


def gather_texts():
    """收集所有摘要文本和 ID，不编码。"""
    abstract_dir = Path(settings.DATA_DIR) / 'abstracts'
    if not abstract_dir.exists():
        print(f'ERROR: 摘要目录不存在: {abstract_dir}')
        print('请先运行数据预处理脚本生成 abstracts/')
        sys.exit(1)

    files = [p for p in sorted(abstract_dir.iterdir()) if p.is_file()]
    texts = []
    ids = []
    names = []
    import re

    for p in files:
        txt = ''
        if p.suffix.lower() in ('.md', '.txt'):
            try:
                txt = p.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                txt = ''
        elif p.suffix.lower() == '.json':
            try:
                obj = json.loads(p.read_text(encoding='utf-8'))
                def extract(o):
                    if isinstance(o, str):
                        return o
                    if isinstance(o, dict):
                        for k in ('abstract', '摘要', 'MGE18_摘要', 'abstract_text'):
                            if k in o and o[k]:
                                return o[k]
                        if 'data' in o and isinstance(o, dict):
                            for v in o['data'].values():
                                if isinstance(v, str) and len(v) > 20:
                                    return v
                    if isinstance(o, list):
                        for it in o:
                            t = extract(it)
                            if t:
                                return t
                    return ''
                txt = extract(obj)
            except Exception:
                txt = ''
        if not txt:
            continue
        m = re.search(r'_(\d+)(_abstract)?$', p.name)
        tid = m.group(1) if m else p.stem
        ids.append(str(tid))
        names.append(p.name)
        texts.append(txt)

    if not texts:
        print('未找到摘要文本，退出')
        sys.exit(1)

    print(f'共收集 {len(texts)} 篇摘要')
    return texts, ids, names


def encode_in_chunks(texts, ids, names, model):
    """分块编码，支持断点续传。"""
    total = len(texts)
    chunk_dir = EMB_DIR / 'chunks'
    chunk_dir.mkdir(parents=True, exist_ok=True)

    # 检查已有进度
    done_chunks = sorted(chunk_dir.glob(f'{MODEL_NAME}_chunk_*.npy'))
    done_indices = set()
    for f in done_chunks:
        try:
            idx = int(f.stem.split('_')[-1])
            done_indices.add(idx)
        except ValueError:
            pass

    print(f'已有进度: {len(done_indices)} / { (total + CHUNK_SIZE - 1) // CHUNK_SIZE } 个块')

    all_embs = []
    all_ids = []

    # 加载已完成的块
    for idx in sorted(done_indices):
        chunk_emb_path = chunk_dir / f'{MODEL_NAME}_chunk_{idx}.npy'
        chunk_ids_path = chunk_dir / f'{MODEL_NAME}_chunk_{idx}.json'
        if chunk_emb_path.exists() and chunk_ids_path.exists():
            embs = np.load(str(chunk_emb_path))
            with open(chunk_ids_path, 'r', encoding='utf-8') as f:
                chunk_ids = json.load(f)
            all_embs.append(embs)
            all_ids.extend(chunk_ids)
            print(f'  加载已完成的块 {idx}: {len(chunk_ids)} 条')

    # 处理未完成的块
    num_chunks = (total + CHUNK_SIZE - 1) // CHUNK_SIZE
    for i in range(num_chunks):
        if i in done_indices:
            continue

        start = i * CHUNK_SIZE
        end = min(start + CHUNK_SIZE, total)
        chunk_texts = texts[start:end]
        chunk_ids = ids[start:end]

        print(f'\n处理块 {i+1}/{num_chunks} (索引 {start}-{end-1})...')
        chunk_start_time = time.time()

        # 编码
        embs = []
        for j in range(0, len(chunk_texts), BATCH_SIZE):
            b = chunk_texts[j:j+BATCH_SIZE]
            emb = model.encode(b, show_progress_bar=False, batch_size=BATCH_SIZE)
            embs.append(emb)

        chunk_embs = np.vstack(embs).astype('float32')
        chunk_elapsed = time.time() - chunk_start_time
        speed = len(chunk_texts) / chunk_elapsed
        print(f'  块 {i+1} 完成: {len(chunk_texts)} 条, {chunk_elapsed:.1f}s, 速度 {speed:.1f} 条/秒')

        # 保存块
        chunk_emb_path = chunk_dir / f'{MODEL_NAME}_chunk_{i}.npy'
        chunk_ids_path = chunk_dir / f'{MODEL_NAME}_chunk_{i}.json'
        np.save(str(chunk_emb_path), chunk_embs)
        with open(chunk_ids_path, 'w', encoding='utf-8') as f:
            json.dump(chunk_ids, f, ensure_ascii=False)
        print(f'  已保存块到: {chunk_emb_path}')

        all_embs.append(chunk_embs)
        all_ids.extend(chunk_ids)

    # 合并所有块
    print(f'\n合并 {len(all_embs)} 个块...')
    final_embs = np.vstack(all_embs).astype('float32')
    print(f'最终 embeddings 形状: {final_embs.shape}')

    # 保存完整 embeddings
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    np.save(str(emb_path), final_embs)
    with open(ids_path, 'w', encoding='utf-8') as f:
        json.dump({'ids': all_ids, 'names': names}, f, ensure_ascii=False)
    print(f'已保存完整 embeddings: {emb_path}')
    print(f'已保存完整 ids: {ids_path}')

    return final_embs, all_ids


def build_faiss_index(embs, ids):
    """构建并保存 FAISS 索引。"""
    # 归一化
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    embs = embs / (norms + 1e-12)

    d = embs.shape[1]
    print(f'\n向量维度: {d}, 数量: {embs.shape[0]}')

    # 构建 FAISS 索引
    index = faiss.IndexFlatIP(d)
    index.add(embs)
    print('FAISS 索引构建完成')

    # 保存索引与 ids
    index_names = [
        OUT_FAISS_DIR / f'index_{MODEL_NAME}_normalized.faiss',
        OUT_FAISS_DIR / f'processed_index_{MODEL_NAME}_normalized.faiss',
    ]
    ids_names = [
        OUT_IDS_DIR / f'ids_{MODEL_NAME}_normalized.json',
        OUT_IDS_DIR / f'processed_abstract_ids_{MODEL_NAME}_normalized.json',
    ]

    for p in index_names:
        faiss.write_index(index, str(p))
        print('已保存索引:', p)
    for p in ids_names:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'ids': ids}, f, ensure_ascii=False)
        print('已保存 id 列表:', p)

    print('\nFAISS 索引生成完成！')


# 主流程
if __name__ == '__main__':
    print(f'=== 生成 FAISS 索引: {MODEL_NAME} ===\n')

    # 如果已有 embeddings 文件，直接加载
    if emb_path.exists() and ids_path.exists():
        print('加载已有 embeddings:', emb_path)
        embs = np.load(str(emb_path))
        with open(ids_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        ids = meta.get('ids') or meta
        if isinstance(ids, dict) and 'ids' in ids:
            ids = ids['ids']
        print(f'加载完成: {embs.shape[0]} 条向量')
    else:
        # 收集文本
        texts, ids, names = gather_texts()

        # 加载模型
        print(f'\n加载模型: {MODEL_NAME}')
        from core.model_loader import get_model
        model = get_model(MODEL_NAME)
        print('模型加载完成')

        # 分块编码
        embs, ids = encode_in_chunks(texts, ids, names, model)

    # 构建 FAISS 索引
    build_faiss_index(embs, ids)
