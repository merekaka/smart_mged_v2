"""
重建 TF-IDF / 倒排索引预计算文件 (覆盖 `tfidf_results/*_{own,external}.json`)

用法:
  python tools/rebuild_tfidf_results.py

说明:
  - 从 `data/abstracts` 目录读取所有文本/markdown 文件
  - 以文件名（去掉后缀 `_abstract` 和尾部 `_数字`）作为文档 ID
  - 使用结巴分词并参考项目中的停用词、清洗规则计算词频、文档频率、IDF 和文档向量(tf-idf)
    - 输出覆盖到项目根目录下的 `tfidf_results/`，文件名为 `*_{own,external}.json`
"""
from pathlib import Path
import json
import math
import re
import sys

try:
    import jieba
except Exception:
    print("请先安装 jieba: pip install jieba")
    sys.exit(1)


def get_dirs():
    try:
        from django.conf import settings
        data_dir = Path(settings.DATA_DIR)
        out_dir = Path(settings.TFIDF_RESULTS_DIR)
    except Exception:
        BASE_DIR = Path(__file__).resolve().parents[1]
        data_dir = BASE_DIR / "data"
        out_dir = BASE_DIR / "tfidf_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, out_dir


# copy stop words and patterns from core/inverted_index for consistency
STOP_WORDS = {
    "的", "是", "在", "了", "和", "与", "或", "等", "中", "为", "以", "及",
    "对", "从", "向", "到", "由", "这", "那", "有", "个", "上", "下", "前",
    "后", "左", "右", "内", "外", "数据集", "数据", "组", "记录", "更新",
}

PATTERNS_TO_REMOVE = [r"\d+\.?\d*", r"[^\w\s\u4e00-\u9fff]"]


def clean_text(text: str) -> str:
    for pat in PATTERNS_TO_REMOVE:
        text = re.sub(pat, " ", text)
    return re.sub(r"\s+", " ", text).strip()


def mixed_cut(text: str):
    words = list(jieba.cut(text))
    en_words = re.findall(r"[A-Za-z0-9\-\.]+", text)
    all_words = words + en_words
    return [w.strip() for w in all_words if w.strip()]


def safe_doc_id_from_filename(name: str) -> str:
    import unicodedata
    stem = unicodedata.normalize("NFKC", name).strip().lower()
    safe = "".join(c for c in stem if c.isalnum() or c in ("-", "_"))
    if safe.endswith("_abstract"):
        safe = safe[: -len("_abstract")]
    safe = re.sub(r'_\d+$', '', safe)
    return safe


def build_from_abstracts():
    data_dir, out_dir = get_dirs()
    abstract_dir = data_dir / "abstracts"
    if not abstract_dir.exists():
        print(f"摘要目录不存在: {abstract_dir}")
        return

    docs = {}
    for p in sorted(abstract_dir.iterdir()):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            try:
                text = p.read_text(encoding="gbk")
            except Exception:
                continue
        doc_id = safe_doc_id_from_filename(p.stem)
        if not doc_id:
            doc_id = p.stem
        # store both text and original stem so filename tokens can be included
        docs[doc_id] = {"text": text, "stem": p.stem}

    total_docs = len(docs)
    print(f"加载摘要文件数: {total_docs}")

    term_freq = {}        # total term frequency across corpus
    doc_freq = {}         # number of documents containing term
    doc_term_counts = {}  # per-document term counts

    for doc_id, obj in docs.items():
        text = obj.get("text", "")
        stem = obj.get("stem", "")
        cleaned = clean_text(text)
        tokens = mixed_cut(cleaned)
        counts = {}
        for w in tokens:
            if not w or w in STOP_WORDS or len(w) <= 1:
                continue
            counts[w] = counts.get(w, 0) + 1
        # also include tokens from filename (stem)
        if stem:
            fname_clean = clean_text(stem.replace("_", " "))
            fname_tokens = mixed_cut(fname_clean)
            for w in fname_tokens:
                if not w or w in STOP_WORDS or len(w) <= 1:
                    continue
                # give filename tokens a small boost (count +1)
                counts[w] = counts.get(w, 0) + 1
        if not counts:
            continue
        doc_term_counts[doc_id] = counts
        for t, c in counts.items():
            term_freq[t] = term_freq.get(t, 0) + c
            doc_freq[t] = doc_freq.get(t, 0) + 1

    # compute idf and doc vectors (tf-idf)
    idf_values = {}
    doc_vectors = {}
    N = max(1, total_docs)
    for term, df in doc_freq.items():
        idf = math.log((N + 1) / (df + 1)) + 1.0
        idf_values[term] = idf

    for doc_id, counts in doc_term_counts.items():
        vec = {}
        for term, c in counts.items():
            tf = 1.0 + math.log(c)
            vec[term] = tf * idf_values.get(term, 0.0)
        doc_vectors[doc_id] = vec

    stats = {"total_docs": total_docs}

    # save files for both own/external to keep runtime behavior consistent
    out_dir = Path(out_dir)
    for mode in ("own", "external"):
        with open(out_dir / f"term_freq_{mode}.json", "w", encoding="utf-8") as f:
            json.dump(term_freq, f, ensure_ascii=False, indent=2)
        with open(out_dir / f"doc_freq_{mode}.json", "w", encoding="utf-8") as f:
            json.dump(doc_freq, f, ensure_ascii=False, indent=2)
        with open(out_dir / f"idf_values_{mode}.json", "w", encoding="utf-8") as f:
            json.dump(idf_values, f, ensure_ascii=False, indent=2)
        with open(out_dir / f"doc_vectors_{mode}.json", "w", encoding="utf-8") as f:
            json.dump(doc_vectors, f, ensure_ascii=False, indent=2)
        with open(out_dir / f"stats_{mode}.json", "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"已写入到: {out_dir} (模式: own + external)")


if __name__ == "__main__":
    build_from_abstracts()
