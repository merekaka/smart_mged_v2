import os
import sys
import json
from pathlib import Path
import numpy as np

# 将项目根目录加入 sys.path，以便导入 config 模块
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
MODEL_NAME = 'm3e-base'
# 支持从命令行传入模型名：
if len(sys.argv) > 1:
    MODEL_NAME = sys.argv[1]
EMB_DIR = Path(settings.VECTOR_DATABASE_DIR) / 'abstract_embeddings'
OUT_FAISS_DIR = Path(settings.VECTOR_DATABASE_DIR) / 'abstract_faiss'
OUT_IDS_DIR = Path(settings.VECTOR_DATABASE_DIR) / 'abstract_ids'

OUT_FAISS_DIR.mkdir(parents=True, exist_ok=True)
OUT_IDS_DIR.mkdir(parents=True, exist_ok=True)

emb_path = EMB_DIR / f'{MODEL_NAME}_abstract_embeddings.npy'
ids_path = EMB_DIR / f'{MODEL_NAME}_abstract_ids.json'

# 如果没有预生成 embeddings，则尝试按 encode_abstracts 的逻辑生成
def gather_texts_and_compute_embeddings():
    print('未发现 embeddings 文件，尝试直接从 data/abstracts 生成 embeddings（需要模型与依赖）')
    from core.model_loader import get_model
    model = get_model(MODEL_NAME)
    abstract_dir = Path(settings.DATA_DIR) / 'abstracts'
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
                # 简单提取较长字符串字段
                def extract(o):
                    if isinstance(o, str):
                        return o
                    if isinstance(o, dict):
                        for k in ('abstract','摘要','MGE18_摘要','abstract_text'):
                            if k in o and o[k]:
                                return o[k]
                        if 'data' in o and isinstance(o['data'], dict):
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
    print(f'计算 {len(texts)} 篇摘要的 embeddings...')
    batch = 32
    embs = []
    for i in range(0, len(texts), batch):
        b = texts[i:i+batch]
        emb = model.encode(b, show_progress_bar=False)
        embs.append(emb)
    embs = np.vstack(embs).astype('float32')
    # 保存到 EMB_DIR
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    np.save(emb_path, embs)
    with open(ids_path, 'w', encoding='utf-8') as f:
        json.dump({'ids': ids, 'names': names}, f, ensure_ascii=False)
    return embs, ids

# 主流程
if emb_path.exists() and ids_path.exists():
    print('加载 embeddings:', emb_path)
    embs = np.load(str(emb_path))
    with open(ids_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    ids = meta.get('ids') or meta
    if isinstance(ids, dict) and 'ids' in ids:
        ids = ids['ids']
else:
    embs, ids = gather_texts_and_compute_embeddings()

# 确保为 float32
embs = np.asarray(embs, dtype='float32')
# 归一化
norms = np.linalg.norm(embs, axis=1, keepdims=True)
embs = embs / (norms + 1e-12)

d = embs.shape[1]
print(f'向量维度: {d}, 数量: {embs.shape[0]}')

# 构建 FAISS 索引（内积搜索，因向量已归一化等价于余弦相似度）
index = faiss.IndexFlatIP(d)
index.add(embs)

# 保存索引与 ids 到多个路径以兼容现有加载逻辑（覆盖旧索引）
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

print('FAISS 索引生成并覆盖完成。')
