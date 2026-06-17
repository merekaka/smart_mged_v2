"""
core/inverted_index.py
-----------------------
InvertedIndex class + initialize_inverted_index() helper.
Extracted verbatim from the original app.py.
[注意：此文件保留用于其他功能，但精确搜索功能已在 views.py 中禁用]
"""
import json
import logging
import math
import os
import re
from collections import defaultdict

import jieba
from django.conf import settings

logger = logging.getLogger(__name__)

_inverted_index = None  # module-level singleton


class InvertedIndex:
    def __init__(self, abstract_mode="own"):
        self.abstract_mode = abstract_mode
        self.documents = {}
        self.term_freq = {}
        self.doc_freq = {}
        self.idf_values = {}
        self.doc_vectors = {}
        self.total_docs = 0
        self.inverted_index = {}

        # Element name ↔ symbol mappings (abbreviated excerpt kept for brevity;
        # full mapping identical to original app.py)
        self.element_mapping = {
            "氢": "H", "氦": "He", "锂": "Li", "铍": "Be", "硼": "B", "碳": "C",
            "氮": "N", "氧": "O", "氟": "F", "氖": "Ne", "钠": "Na", "镁": "Mg",
            "铝": "Al", "硅": "Si", "磷": "P", "硫": "S", "氯": "Cl", "氩": "Ar",
            "钾": "K", "钙": "Ca", "钪": "Sc", "钛": "Ti", "钒": "V", "铬": "Cr",
            "锰": "Mn", "铁": "Fe", "钴": "Co", "镍": "Ni", "铜": "Cu", "锌": "Zn",
            "镓": "Ga", "锗": "Ge", "砷": "As", "硒": "Se", "溴": "Br", "氪": "Kr",
            "铷": "Rb", "锶": "Sr", "钇": "Y", "锆": "Zr", "铌": "Nb", "钼": "Mo",
            "锝": "Tc", "钌": "Ru", "铑": "Rh", "钯": "Pd", "银": "Ag", "镉": "Cd",
            "铟": "In", "锡": "Sn", "锑": "Sb", "碲": "Te", "碘": "I", "氙": "Xe",
            "铯": "Cs", "钡": "Ba", "镧": "La", "铈": "Ce", "镨": "Pr", "钕": "Nd",
            "钷": "Pm", "钐": "Sm", "铕": "Eu", "钆": "Gd", "铽": "Tb", "镝": "Dy",
            "钬": "Ho", "铒": "Er", "铥": "Tm", "镱": "Yb", "镥": "Lu", "铪": "Hf",
            "钽": "Ta", "钨": "W", "铼": "Re", "锇": "Os", "铱": "Ir", "铂": "Pt",
            "金": "Au", "汞": "Hg", "铊": "Tl", "铅": "Pb", "铋": "Bi", "钋": "Po",
            "砹": "At", "氡": "Rn", "钫": "Fr", "镭": "Ra", "锕": "Ac", "钍": "Th",
            "镤": "Pa", "铀": "U", "镎": "Np", "钚": "Pu", "镅": "Am", "锔": "Cm",
            "锫": "Bk", "锎": "Cf", "锿": "Es", "镄": "Fm", "钔": "Md", "锘": "No",
            "铹": "Lr",
        }
        self.symbol_to_name = {v: k for k, v in self.element_mapping.items()}

        self.stop_words = {
            "的", "是", "在", "了", "和", "与", "或", "等", "中", "为", "以", "及",
            "对", "从", "向", "到", "由", "这", "那", "有", "个", "上", "下", "前",
            "后", "左", "右", "内", "外", "数据集", "数据", "组", "记录", "更新",
            "发布", "整合", "自研", "本", "该", "其", "此", "这些", "那些", "一个",
            "一种", "一些", "若干", "多个", "各种", "各类", "年", "月", "日", "时",
            "分", "秒", "wt", "℃", "J", "g", "kg", "m", "cm", "mm", "nm", "μm",
            "通过", "基于", "用于", "可以", "能够", "需要", "应该", "必须", "可能",
            "研究", "分析", "实验", "测试", "测量", "观察", "发现", "表明", "显示",
            "证明", "具有", "存在", "产生", "形成", "发生", "出现", "导致", "引起",
            "造成", "影响", "不同", "哪里", "找到", "基",
            "the", "and", "of", "in", "to", "for", "with", "on", "by", "an", "is",
            "are", "as", "at", "from", "that", "this", "it", "be", "or", "not",
            "can", "will", "has", "have", "was", "were", "but", "which", "their",
            "its", "if", "also", "such", "may", "more", "other", "than", "these",
            "those", "all", "any", "each", "both", "some", "no", "nor", "so",
            "very", "just", "like", "one", "two", "first", "new", "used", "using",
            "use", "based", "between", "into", "over", "after", "before", "during",
            "under", "out", "up", "down", "about", "above", "below", "through",
            "per", "via", "etc",
        }

        self.patterns_to_remove = [
            r"\d+\.?\d*",
            r"[^\w\s\u4e00-\u9fff]",
        ]
        self.load_precomputed_values()

    # ------------------------------------------------------------------
    # Element helpers
    # ------------------------------------------------------------------
    def is_element_symbol(self, word):
        return word in self.symbol_to_name

    def is_element_name(self, word):
        return word in self.element_mapping

    def get_element_pair(self, word):
        if self.is_element_name(word):
            return word, self.element_mapping[word]
        elif self.is_element_symbol(word):
            return self.symbol_to_name[word], word
        return None, None

    # ------------------------------------------------------------------
    # Text processing
    # ------------------------------------------------------------------
    def clean_text(self, text):
        for pattern in self.patterns_to_remove:
            text = re.sub(pattern, " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def mixed_cut(self, text):
        words = list(jieba.cut(text))
        en_words = re.findall(r"[A-Za-z0-9\-\.]+", text)
        all_words = words + en_words
        return [w.strip() for w in all_words if w.strip()]

    def extract_keywords(self, text):
        logger.info(f"关键词提取 - 源文本: {text}")
        processed_text = text

        compound_patterns = []
        for name, symbol in self.element_mapping.items():
            compound_patterns.extend([
                (f"{name}基", f"{name} 基"),
                (f"{name}合金", f"{name} 合金"),
                (f"{symbol}基", f"{symbol} 基"),
                (f"{symbol}合金", f"{symbol} 合金"),
            ])
        compound_patterns.sort(key=lambda x: len(x[0]), reverse=True)
        for pat, repl in compound_patterns:
            if pat in processed_text:
                processed_text = processed_text.replace(pat, repl)

        for symbol, name in self.symbol_to_name.items():
            for ctx in [f"-{symbol}-", f"-{symbol} ", f" {symbol}-", f" {symbol} "]:
                if ctx in processed_text:
                    processed_text = processed_text.replace(ctx, ctx.replace(symbol, name))
            if re.search(r"\b" + symbol + r"\b", processed_text):
                processed_text = re.sub(r"\b" + symbol + r"\b", name, processed_text)

        cleaned_text = self.clean_text(processed_text)
        words = self.mixed_cut(cleaned_text)
        keywords = []
        for w in words:
            w = w.strip()
            if not w:
                continue
            name, symbol = self.get_element_pair(w)
            if name and symbol:
                keywords.append(name)
                keywords.append(symbol)
            elif w not in self.stop_words:
                keywords.append(w)

        return list(dict.fromkeys(keywords))

    def process_query(self, query):
        keywords = self.extract_keywords(query)
        keyword_matches = self.get_keyword_matches(keywords)
        return keywords, keyword_matches

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------
    def build_inverted_index(self):
        self.inverted_index = {}
        for doc_id, vector in self.doc_vectors.items():
            for term in vector:
                self.inverted_index.setdefault(term, [])
                self.inverted_index[term].append(doc_id)
        for term in self.inverted_index:
            self.inverted_index[term] = list(set(self.inverted_index[term]))
        logger.info(f"倒排索引构建完成，词项数: {len(self.inverted_index)}")

    def load_precomputed_values(self):
        mode = self.abstract_mode
        base_dir = str(settings.TFIDF_RESULTS_DIR)
        try:
            with open(os.path.join(base_dir, f"idf_values_{mode}.json"), "r", encoding="utf-8") as f:
                self.idf_values = json.load(f)
            with open(os.path.join(base_dir, f"doc_vectors_{mode}.json"), "r", encoding="utf-8") as f:
                self.doc_vectors = json.load(f)
            with open(os.path.join(base_dir, f"term_freq_{mode}.json"), "r", encoding="utf-8") as f:
                self.term_freq = json.load(f)
            with open(os.path.join(base_dir, f"doc_freq_{mode}.json"), "r", encoding="utf-8") as f:
                self.doc_freq = json.load(f)
            with open(os.path.join(base_dir, f"stats_{mode}.json"), "r", encoding="utf-8") as f:
                stats = json.load(f)
                self.total_docs = stats["total_docs"]
            self.build_inverted_index()
            logger.info(f"TF-IDF 预计算值加载完成 (模式: {mode})")
        except Exception as e:
            logger.error(f"加载预计算 TF-IDF 值失败: {e}")
            raise

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def get_keyword_matches(self, keywords):
        matches = {}
        for keyword in keywords:
            if keyword in self.inverted_index:
                doc_ids = self.inverted_index[keyword]
                matching_docs = [
                    (doc_id, self.doc_vectors[doc_id][keyword])
                    for doc_id in doc_ids
                    if doc_id in self.doc_vectors and keyword in self.doc_vectors[doc_id]
                ]
                if matching_docs:
                    matching_docs.sort(key=lambda x: x[1], reverse=True)
                    matches[keyword] = {
                        "document_count": len(matching_docs),
                        "document_scores": matching_docs,
                    }
        return matches

    def search(self, query, operator="AND"):
        cleaned_query = self.clean_text(query)
        words = [
            w for w in self.mixed_cut(cleaned_query)
            if w not in self.stop_words and len(w) > 1
        ]
        if not words:
            return [], {}
        doc_sets = []
        keyword_matches = {}
        for word in words:
            if word in self.inverted_index:
                doc_ids = set(self.inverted_index[word])
                doc_sets.append(doc_ids)
                keyword_matches[word] = list(doc_ids)
        if not doc_sets:
            return [], {}
        if operator == "AND":
            result_ids = set.intersection(*doc_sets)
        else:
            result_ids = set.union(*doc_sets)
        results = []
        for doc_id in result_ids:
            total_score = sum(
                self.doc_vectors[doc_id].get(w, 0)
                for w in words
                if doc_id in self.doc_vectors
            )
            results.append({"id": doc_id, "text": self.documents.get(doc_id, ""), "score": total_score})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def get_index_info(self):
        return {
            "total_docs": self.total_docs,
            "total_terms": len(self.doc_freq),
            "total_vectors": len(self.doc_vectors),
            "inverted_index_size": len(self.inverted_index),
            "top_terms": sorted(
                [(t, len(d)) for t, d in self.inverted_index.items()],
                key=lambda x: x[1],
                reverse=True,
            )[:10],
        }


def get_inverted_index(abstract_mode: str = "own") -> InvertedIndex:
    """Return a (cached) InvertedIndex for the given abstract_mode."""
    global _inverted_index
    if _inverted_index is None or getattr(_inverted_index, "abstract_mode", None) != abstract_mode:
        logger.info(f"初始化倒排索引 (模式: {abstract_mode})...")
        _inverted_index = InvertedIndex(abstract_mode=abstract_mode)

        data_dir = settings.DATA_DIR
        processed_dir = data_dir / "processed_data"
        abstract_dir  = data_dir / "dataset_abstract"

        for filename in os.listdir(processed_dir):
            if not (filename.startswith("processed_") and filename.endswith(".json")):
                continue
            abstract_id = filename[len("processed_"):-len(".json")]
            fp = processed_dir / filename
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    doc_data = json.load(f)
                if abstract_mode == "external":
                    abs_fp = abstract_dir / f"abstract_{abstract_id}.txt"
                    if abs_fp.exists():
                        with open(abs_fp, "r", encoding="utf-8") as f2:
                            abstract = f2.read()
                    else:
                        abstract = doc_data.get("abstract", "")
                else:
                    abstract = doc_data.get("abstract", "")
                _inverted_index.documents[abstract_id] = f"{doc_data.get('name', '')} {abstract}"
            except Exception as e:
                logger.error(f"处理文件 {filename} 出错: {e}")

        logger.info(f"倒排索引初始化完成 (模式: {abstract_mode})")
    return _inverted_index
