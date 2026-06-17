#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
临时脚本：从 sql_nl_test_samples_500_no_result.json 中，
提取包含 MAX / MIN / AVG 聚合函数的统计分析问题，
输出到 sql_nl_test_samples_500_agg.json
"""
import json
import os
import re

INPUT_FILE = "sql_nl_test_samples_500_no_result.json"
OUTPUT_FILE = "sql_nl_test_samples_500_agg.json"

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(base_dir, INPUT_FILE)
    output_path = os.path.join(base_dir, OUTPUT_FILE)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 匹配 SELECT MAX/MIN/AVG(
    agg_pattern = re.compile(r'SELECT\s+(?:MAX|MIN|AVG)\s*\(', re.IGNORECASE)

    agg_samples = []
    for item in data:
        sql = item.get("sql", "")
        if agg_pattern.search(sql):
            # 识别具体用了哪些聚合函数
            found = []
            for fn in ["MAX", "MIN", "AVG"]:
                if re.search(rf'\b{fn}\s*\(', sql, re.IGNORECASE):
                    found.append(fn)
            item["agg_functions"] = found
            agg_samples.append(item)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(agg_samples, f, ensure_ascii=False, indent=2)

    print(f"已提取 {len(agg_samples)} 条聚合查询样本，保存至: {output_path}")
    print(f"  MAX: {sum(1 for s in agg_samples if 'MAX' in s['agg_functions'])}")
    print(f"  MIN: {sum(1 for s in agg_samples if 'MIN' in s['agg_functions'])}")
    print(f"  AVG: {sum(1 for s in agg_samples if 'AVG' in s['agg_functions'])}")

    # 预览前 10 条
    print("\n========== 前 10 条预览 ==========\n")
    for item in agg_samples[:10]:
        print(f"【Sample {item['sample_id']}】[{', '.join(item['agg_functions'])}]")
        print(f"  NL: {item['natural_language']}")
        # 只打印 SQL 的第一行（聚合函数声明）
        first_line = item['sql'].strip().split('\n')[0]
        print(f"  SQL: {first_line}")
        print()

if __name__ == "__main__":
    main()
