#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
临时脚本：将聚合查询的结构化结果（sql_nl_test_samples_500_agg_cleaned.json）
融合到主文件（sql_nl_test_samples_500_cleaned.json）中。
只更新 property_constraints 和 groups 字段，不添加 agg_functions 字段。
"""
import json
import os

MAIN_FILE = "sql_nl_test_samples_500_cleaned.json"
AGG_FILE = "sql_nl_test_samples_500_agg_cleaned.json"
OUTPUT_FILE = "sql_nl_test_samples_500_cleaned.json"


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    main_path = os.path.join(base_dir, MAIN_FILE)
    agg_path = os.path.join(base_dir, AGG_FILE)
    output_path = os.path.join(base_dir, OUTPUT_FILE)

    with open(main_path, "r", encoding="utf-8") as f:
        main_data = json.load(f)

    with open(agg_path, "r", encoding="utf-8") as f:
        agg_data = json.load(f)

    # 按 sample_id 建立 agg 数据映射
    agg_map = {item["sample_id"]: item for item in agg_data}

    updated_count = 0
    for item in main_data:
        sid = item["sample_id"]
        if sid in agg_map:
            agg_item = agg_map[sid]
            # 只更新 property_constraints 和 groups 字段
            item["property_constraints"] = agg_item["property_constraints"]
            item["groups"] = agg_item["groups"]
            # cleaned_conditions 也同步更新（聚合查询的清洗结果更准确）
            item["cleaned_conditions"] = agg_item["cleaned_conditions"]
            updated_count += 1

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(main_data, f, ensure_ascii=False, indent=2)

    print(f"已融合 {updated_count} 条聚合查询，结果保存至: {output_path}")

    # 验证更新后的样例
    print("\n========== 验证更新后的样例 ==========\n")
    for item in main_data:
        if item["sample_id"] in [10, 13, 14, 16]:
            print(f"【Sample {item['sample_id']}】{item['natural_language']}")
            print(f"  property_constraints: {json.dumps(item['property_constraints'], ensure_ascii=False)}")
            print(f"  groups: {json.dumps(item['groups'], ensure_ascii=False)}")
            print()


if __name__ == "__main__":
    main()
