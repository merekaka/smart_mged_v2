#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
临时脚本：对 sql_nl_test_samples_500_agg.json 中的聚合查询进行结构化处理，
提取 property_id → property_name、agg_func、dataset 限定等，
输出结构与主测试集清洗结果保持一致。
"""
import json
import os
import re

INPUT_FILE = "sql_nl_test_samples_500_agg.json"
MAP_FILE = "property_id_map.json"
OUTPUT_FILE = "sql_nl_test_samples_500_agg_cleaned.json"


def load_property_map(base_dir: str) -> dict:
    map_path = os.path.join(base_dir, MAP_FILE)
    with open(map_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
        return {int(k): v for k, v in raw.items()}


def extract_agg_func(sql: str) -> list:
    """提取 SQL 中的聚合函数名（MAX/MIN/AVG）"""
    funcs = []
    for fn in ["MAX", "MIN", "AVG"]:
        if re.search(rf"\b{fn}\s*\(", sql, re.IGNORECASE):
            funcs.append(fn)
    return funcs


def clean_agg_sql(sql: str) -> str:
    """清洗聚合查询 SQL，删除固定模板"""
    s = sql.strip()

    # 1. 删除 SELECT ... 到 FROM 之前的部分（聚合函数声明）
    # 保留 FROM 之后的部分，如果有 WHERE 则保留 WHERE 及之后
    from_match = re.search(r"\bFROM\b", s, re.IGNORECASE)
    if from_match:
        s = s[from_match.start():].strip()

    # 2. 删除 FROM smart_mged.entity_table e [JOIN ...] 到 WHERE 之前的前缀
    where_match = re.search(r"\bWHERE\b", s, re.IGNORECASE)
    if where_match:
        s = s[where_match.end():].strip()
    else:
        # 无 WHERE 的聚合查询非常少见
        pass

    # 3. 删除 value != '' 和 value IS NOT NULL（含/不含 alias）
    s = re.sub(r"\s*\bAND\b\s+(?:v\d*\.)?value\s*!=\s*''\s*", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*(?:v\d*\.)?value\s*!=\s*''\s*", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\bAND\b\s+(?:v\d*\.)?value\s+IS\s+NOT\s+NULL\s*", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*(?:v\d*\.)?value\s+IS\s+NOT\s+NULL\s*", " ", s, flags=re.IGNORECASE)

    # 4. 删除结尾分号
    s = s.strip().rstrip(";").strip()
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n", "\n", s)
    s = s.strip()

    return s


def extract_dataset_constraints(sql: str) -> list:
    """提取 e.title = '...' 或 e.title IN ('...') 中的数据集名称"""
    datasets = []
    # e.title IN ('数据集1', '数据集2')
    title_in_pat = re.compile(r"e\.title\s+IN\s*\(([^)]+)\)", re.IGNORECASE)
    # e.title = '数据集'
    title_eq_pat = re.compile(r"e\.title\s*=\s*'([^']+)'", re.IGNORECASE)

    for m in title_in_pat.finditer(sql):
        datasets.extend(re.findall(r"'([^']*)'", m.group(1)))
    for m in title_eq_pat.finditer(sql):
        datasets.append(m.group(1))

    return datasets


def extract_property_constraints(cleaned_sql: str, id2name: dict) -> list:
    """提取聚合查询中的 property_id 约束"""
    constraints = []
    if not cleaned_sql:
        return constraints

    # 聚合查询中 property_id 可能带 alias 或没有
    pid_pattern = re.compile(r"(v\d*?)\.property_id\s*=\s*(\d+)", re.IGNORECASE)
    pid_pattern_no_alias = re.compile(r"\bproperty_id\s*=\s*(\d+)", re.IGNORECASE)

    matches = list(pid_pattern.finditer(cleaned_sql))
    no_alias_matches = list(pid_pattern_no_alias.finditer(cleaned_sql))

    all_positions = []
    seen_pids = set()
    for m in matches:
        alias = m.group(1)
        pid = int(m.group(2))
        if pid not in seen_pids:
            seen_pids.add(pid)
            all_positions.append((m.start(), m.end(), alias, pid))
    for m in no_alias_matches:
        pid = int(m.group(1))
        if pid not in seen_pids:
            seen_pids.add(pid)
            all_positions.append((m.start(), m.end(), "", pid))

    all_positions.sort(key=lambda x: x[0])

    for idx, (start, end, alias, pid) in enumerate(all_positions):
        pname = id2name.get(pid, f"UNKNOWN({pid})")

        if idx + 1 < len(all_positions):
            seg_end = all_positions[idx + 1][0]
        else:
            seg_end = len(cleaned_sql)
        segment = cleaned_sql[start:seg_end].strip()
        segment = re.sub(r"^\s*\bAND\b\s+", "", segment, flags=re.IGNORECASE)
        segment = re.sub(r"\s+\bAND\b\s*$", "", segment, flags=re.IGNORECASE)

        # 聚合查询的 property_id 条件没有数值比较条件（value 条件）
        constraints.append({
            "property_id": pid,
            "raw_fragment": segment,
            "conditions": [
                {
                    "field": pname,
                    "operator": None,
                    "value": None
                }
            ]
        })

    return constraints


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(base_dir, INPUT_FILE)
    output_path = os.path.join(base_dir, OUTPUT_FILE)

    id2name = load_property_map(base_dir)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cleaned_data = []
    for item in data:
        sql = item.get("sql", "")
        agg_funcs = extract_agg_func(sql)
        cleaned_sql = clean_agg_sql(sql)
        dataset_constraints = extract_dataset_constraints(sql)
        constraints = extract_property_constraints(cleaned_sql, id2name)

        # 构建 groups：每个 property_constraint 对应一个 group
        groups = []
        for c in constraints:
            for cond in c["conditions"]:
                base = {
                    "field": cond["field"],
                    "unit": None,
                    "agg_func": agg_funcs[0] if agg_funcs else None
                }
                groups.append({
                    "logic_op": "and",
                    "conditions": [
                        {
                            **base,
                            "operator": cond["operator"],
                            "value": cond["value"]
                        }
                    ],
                    "datasets": dataset_constraints
                })

        new_item = {
            "sample_id": item.get("sample_id"),
            "natural_language": item.get("natural_language"),
            "sql": sql,
            "cleaned_conditions": cleaned_sql,
            "agg_functions": agg_funcs,
            "dataset_constraints": dataset_constraints,
            "property_constraints": constraints,
            "groups": groups,
        }
        cleaned_data.append(new_item)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_data, f, ensure_ascii=False, indent=2)

    print(f"已处理 {len(cleaned_data)} 条聚合查询，结果保存至: {output_path}")

    # 打印前 10 条预览
    print("\n========== 前 10 条预览 ==========\n")
    for item in cleaned_data[:10]:
        print(f"【Sample {item['sample_id']}】[{', '.join(item['agg_functions'])}] {item['natural_language']}")
        print(f"  清洗文本: {item['cleaned_conditions']}")
        if item['dataset_constraints']:
            print(f"  [数据集限定] {', '.join(item['dataset_constraints'])}")
        for g in item['groups']:
            cond = g['conditions'][0]
            print(f"  → {cond['field']} agg_func={cond['agg_func']}, datasets={g['datasets']}")
        print()


if __name__ == "__main__":
    main()
