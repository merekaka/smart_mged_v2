#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
临时脚本：从 sql_nl_test_samples_500.json 中提取除 result 字段外的其他字段，
输出到 sql_nl_test_samples_500_no_result.json
"""
import json
import os

INPUT_FILE = "sql_nl_test_samples_500.json"
OUTPUT_FILE = "sql_nl_test_samples_500_no_result.json"

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(base_dir, INPUT_FILE)
    output_path = os.path.join(base_dir, OUTPUT_FILE)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    filtered = []
    for item in data:
        new_item = {k: v for k, v in item.items() if k != "result"}
        filtered.append(new_item)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)

    print(f"已提取 {len(filtered)} 条记录，结果保存至: {output_path}")

if __name__ == "__main__":
    main()
