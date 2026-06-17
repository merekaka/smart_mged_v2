#!/usr/bin/env python
"""
意图查询测试脚本 —— 以表格形式输出查询结果。

用法:
    python tools/test_intent_query.py "查找抗拉强度大于500MPa的钛合金"
    python tools/test_intent_query.py "钛合金和铝合金的熔点对比"
    python tools/test_intent_query.py "查找泊松比小于4.0的材料样本和加载条件小于27.6的样本"

环境要求:
    - Django 环境变量已配置（脚本会自动设置）
    - MySQL 可连接（依赖 pymysql）
    - 可选: pip install tabulate（表格更美观，未安装时用简易格式）
"""

import os
import sys

# 将项目根目录加入 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from apps.intent_engine.parser import IntentParser
from apps.chat.backend_client import query_with_details


def _fmt_table(rows, headers):
    """简易表格格式化（无 tabulate 时的 fallback）。"""
    col_widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0)) for i, h in enumerate(headers)]
    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    
    def _row_line(cells):
        return "|" + "|".join(f" {str(c):<{col_widths[i]}} " for i, c in enumerate(cells)) + "|"
    
    lines = [sep, _row_line(headers), sep]
    for r in rows:
        lines.append(_row_line(r))
    lines.append(sep)
    return "\n".join(lines)


def print_table(rows, headers, title=None):
    """优先使用 tabulate，无则 fallback。"""
    if title:
        print(f"\n{title}")
        print("-" * len(title))
    
    if not rows:
        print("  (无数据)")
        return
    
    try:
        from tabulate import tabulate
        print(tabulate(rows, headers=headers, tablefmt="grid"))
    except ImportError:
        print(_fmt_table(rows, headers))


def run_test(query_text: str):
    print("=" * 70)
    print(f"查询文本: {query_text}")
    print("=" * 70)

    # 1. 意图解析
    parser = IntentParser()
    intent = parser.parse(query_text)
    if not intent:
        print("\n[错误] 意图解析失败")
        return

    intent_dict = intent.to_dict()
    print(f"\n[意图解析]")
    print(f"  query_mode : {intent_dict.get('query_mode', 'simple')}")
    print(f"  intent_type: {intent_dict.get('intent_type', 'search')}")
    print(f"  entities   : {intent_dict.get('entities', [])}")
    print(f"  datasets1  : {intent_dict.get('datasets1', [])}")
    print(f"  conditions1: {intent_dict.get('conditions1', [])}")
    if intent_dict.get("query_mode") == "complex":
        print(f"  datasets2  : {intent_dict.get('datasets2', [])}")
        print(f"  conditions2: {intent_dict.get('conditions2', [])}")
        print(f"  group_logic: {intent_dict.get('group_logic_op', 'and')}")

    # 2. 执行 SQL 查询
    print("\n[执行查询...]")
    try:
        result = query_with_details(intent_dict, original_query=query_text)
    except Exception as e:
        print(f"\n[错误] 查询执行失败: {e}")
        return

    # 3. 输出 SQL
    print(f"\n[生成的 SQL]")
    if result.get("query_mode") == "complex":
        for g in result.get("group_sql", []):
            print(f"  Group {g['index']}: {g.get('sql_rendered', g['sql'])}")
        print(f"  Final     : {result.get('final_sql_rendered', result.get('final_sql', ''))}")
    else:
        print(f"  {result.get('sql_rendered', result.get('sql', ''))}")
        aggs = result.get("answer", {}).get("aggregations", [])
        for a in aggs:
            print(f"  [{a['agg_func'].upper()}] {a.get('stat_sql_rendered', a.get('stat_sql', ''))}")

    # 4. 输出结果表格
    answer = result.get("answer", {})
    data_ids = answer.get("matched_data_ids", [])
    total = answer.get("total", 0)
    records = answer.get("records", [])

    print(f"\n[查询结果] 共命中 {total} 条")

    if records:
        # 展示完整宽表记录摘要（前 10 条，取关键字段）
        display_keys = ["data_id", "title"]
        # 自动补充前几个数值属性作为示例
        if len(records) > 0:
            for k in list(records[0].keys()):
                if k not in display_keys and len(display_keys) < 6:
                    display_keys.append(k)
        rows = []
        for i, rec in enumerate(records[:10]):
            rows.append([rec.get(k, "") for k in display_keys])
        if len(records) > 10:
            rows.append(["..."] * len(display_keys))
        print_table(rows, headers=display_keys, title="完整记录摘要（前10条）")
    elif data_ids:
        rows = [[i + 1, did] for i, did in enumerate(data_ids[:100])]
        if len(data_ids) > 100:
            rows.append(["...", f"... 还有 {len(data_ids) - 100} 条"])
        print_table(rows, headers=["序号", "Data ID"], title="命中记录")
    else:
        print("  未命中任何数据")

    # 5. 聚合统计表格
    aggs = answer.get("aggregations", [])
    if aggs:
        agg_rows = []
        for a in aggs:
            val = a.get("agg_value")
            val_str = f"{val:.4f}" if isinstance(val, float) else str(val)
            matched = a.get("matched_data_ids", [])
            agg_rows.append([
                a.get("field", ""),
                a.get("agg_func", "").upper(),
                val_str,
                len(matched) if matched else "-",
            ])
        print_table(agg_rows, headers=["字段", "聚合", "值", "匹配记录数"], title="聚合统计")

    print()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        # 默认测试用例
        query = "查找抗拉强度大于500MPa的钛合金"
        print("提示: 未提供查询参数，使用默认测试用例。")
        print(f"      可执行: python {sys.argv[0]} \"你的查询文本\"")
    
    run_test(query)
