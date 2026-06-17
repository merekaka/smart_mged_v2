#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
临时脚本：清洗 sql_nl_test_samples_500.json 中的 SQL，
删除固定模板部分，保留实际筛选条件，并将 property_id 转换为 property_name。

数据读取方式：
1. 属性映射(property_id -> property_name)来自数据库 smart_mged.property_table。
2. 为免每次运行都连接数据库，已将映射导出到同目录的 property_id_map.json，
   本脚本直接读取该本地文件。

输出到 sql_nl_test_samples_500_cleaned.json
"""
import json
import os
import re

INPUT_FILE = "sql_nl_test_samples_500.json"
MAP_FILE = "property_id_map.json"
OUTPUT_FILE = "sql_nl_test_samples_500_cleaned.json"


def load_property_map(base_dir: str) -> dict:
    map_path = os.path.join(base_dir, MAP_FILE)
    with open(map_path, "r", encoding="utf-8") as f:
        # JSON key 是字符串，转为 int
        raw = json.load(f)
        return {int(k): v for k, v in raw.items()}


def clean_sql(sql: str) -> str:
    s = sql.strip()

    # 1. 删除 SELECT ... FROM ... 到 WHERE 之前的固定前缀
    where_match = re.search(r'\bWHERE\b', s, re.IGNORECASE)
    if where_match:
        s = s[where_match.end():].strip()

    # 2. 删除结尾的 ORDER BY e.data_id ASC[;\n]*
    s = re.sub(r'\s*\bORDER\s+BY\s+e\.data_id\s+ASC\s*;?\s*$', '', s, flags=re.IGNORECASE)

    # 3. 删除 vX.value != '' / value != ''
    s = re.sub(
        r'\s*\bAND\b\s+(?:v\d*\.)?value\s*!=\s*\'\'\s*',
        ' ', s, flags=re.IGNORECASE
    )
    s = re.sub(
        r'^\s*(?:v\d*\.)?value\s*!=\s*\'\'\s*',
        ' ', s, flags=re.IGNORECASE
    )

    # 4. 删除 vX.value IS NOT NULL / value IS NOT NULL
    s = re.sub(
        r'\s*\bAND\b\s+(?:v\d*\.)?value\s+IS\s+NOT\s+NULL\s*',
        ' ', s, flags=re.IGNORECASE
    )
    s = re.sub(
        r'^\s*(?:v\d*\.)?value\s+IS\s+NOT\s+NULL\s*',
        ' ', s, flags=re.IGNORECASE
    )

    # 5. 清理首尾多余空白和分号
    s = s.strip().rstrip(';').strip()
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n\s*\n', '\n', s)
    s = s.strip()

    return s


def extract_property_constraints(cleaned_sql: str, id2name: dict) -> tuple:
    """
    从清洗后的 SQL 条件文本中提取：
    1. dataset_constraints: e.title 相关的全局数据集限定
    2. property_constraints: 每个 property_id 对应的结构化约束

    返回: (dataset_constraints, property_constraints)
    """
    if not cleaned_sql:
        return [], []

    working = cleaned_sql

    # 1. 先提取全局 e.title 中的数据集名称，并从工作文本中删除
    dataset_constraints = []
    # e.title IN ('数据集1', '数据集2')
    title_in_pat = re.compile(r"e\.title\s+IN\s*\(([^)]+)\)", re.IGNORECASE)
    # e.title = '数据集'
    title_eq_pat = re.compile(r"e\.title\s*=\s*'([^']+)'", re.IGNORECASE)

    for m in title_in_pat.finditer(cleaned_sql):
        dataset_constraints.extend(re.findall(r"'([^']*)'", m.group(1)))
    for m in title_eq_pat.finditer(cleaned_sql):
        dataset_constraints.append(m.group(1))

    # 从 working 中移除 e.title 条件（连同前面的 AND）
    working = title_in_pat.sub('', working)
    working = title_eq_pat.sub('', working)
    working = re.sub(r'\s*\bAND\b\s*$', '', working, flags=re.IGNORECASE)
    working = re.sub(r'^\s*\bAND\b\s+', '', working, flags=re.IGNORECASE)
    working = re.sub(r'\s+\bAND\b\s+', ' AND ', working, flags=re.IGNORECASE)
    working = re.sub(r'\s+', ' ', working).strip()

    # 2. 提取 property_id 约束
    constraints = []
    pid_pattern = re.compile(r'(v\d*?)\.property_id\s*=\s*(\d+)', re.IGNORECASE)
    pid_pattern_no_alias = re.compile(r'\bproperty_id\s*=\s*(\d+)', re.IGNORECASE)

    matches = list(pid_pattern.finditer(working))
    no_alias_matches = list(pid_pattern_no_alias.finditer(working))

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
            all_positions.append((m.start(), m.end(), '', pid))

    all_positions.sort(key=lambda x: x[0])

    for idx, (start, end, alias, pid) in enumerate(all_positions):
        pname = id2name.get(pid, f"UNKNOWN({pid})")

        if idx + 1 < len(all_positions):
            seg_end = all_positions[idx + 1][0]
        else:
            seg_end = len(working)
        segment = working[start:seg_end].strip()
        segment = re.sub(r'^\s*\bAND\b\s+', '', segment, flags=re.IGNORECASE)
        segment = re.sub(r'\s+\bAND\b\s*$', '', segment, flags=re.IGNORECASE)

        conditions = []
        alias_prefix = re.escape(alias) + r'\.' if alias else r'(?:v\d*\.)?'

        # 数值比较
        num_pat = re.compile(
            rf"CAST\({alias_prefix}value\s+AS\s+DECIMAL\([^)]+\)\)\s*"
            r"(=|<>|!=|<|>|<=|>=)\s*([+-]?\d+(?:\.\d+)?)",
            re.IGNORECASE
        )
        for m2 in num_pat.finditer(segment):
            val_str = m2.group(2)
            val = float(val_str) if '.' in val_str else int(val_str)
            conditions.append({
                "type": "numeric",
                "operator": m2.group(1),
                "value": val
            })

        # BETWEEN
        between_pat = re.compile(
            rf"CAST\({alias_prefix}value\s+AS\s+DECIMAL\([^)]+\)\)\s*"
            r"BETWEEN\s+([+-]?\d+(?:\.\d+)?)\s+AND\s+([+-]?\d+(?:\.\d+)?)",
            re.IGNORECASE
        )
        for m2 in between_pat.finditer(segment):
            conditions.append({
                "type": "numeric",
                "operator": "BETWEEN",
                "value": [float(m2.group(1)), float(m2.group(2))]
            })

        # 字符串精确匹配
        str_pat = re.compile(
            rf"{alias_prefix}value\s*=\s*'([^']+)'",
            re.IGNORECASE
        )
        for m2 in str_pat.finditer(segment):
            conditions.append({
                "type": "string",
                "operator": "=",
                "value": m2.group(1)
            })

        # 将 property_name 下沉到每个 condition 的 field 字段，并确保 field 在字典最前面
        for i, cond in enumerate(conditions):
            new_cond = {"field": pname}
            for k, v in cond.items():
                if k != "type":
                    new_cond[k] = v
            conditions[i] = new_cond

        constraints.append({
            "property_id": pid,
            "raw_fragment": segment,
            "conditions": conditions
        })

    return dataset_constraints, constraints


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(base_dir, INPUT_FILE)
    output_path = os.path.join(base_dir, OUTPUT_FILE)

    id2name = load_property_map(base_dir)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cleaned_data = []
    for item in data:
        cleaned_sql = clean_sql(item.get("sql", ""))
        dataset_constraints, constraints = extract_property_constraints(cleaned_sql, id2name)

        # 按照参考结构构建 groups：每个 property_constraint 对应一个 group
        groups = []
        for c in constraints:
            group_conditions = []
            for cond in c["conditions"]:
                base = {
                    "field": cond["field"],
                    "unit": None,
                    "agg_func": None
                }
                if cond["operator"] == "BETWEEN":
                    # 闭区间拆分为 >= 和 <= 两个条件
                    lo, hi = cond["value"]
                    group_conditions.append({**base, "operator": ">=", "value": lo})
                    group_conditions.append({**base, "operator": "<=", "value": hi})
                else:
                    group_conditions.append({**base, "operator": cond["operator"], "value": cond["value"]})

            groups.append({
                "logic_op": "and",
                "conditions": group_conditions,
                "datasets": dataset_constraints
            })

        new_item = {
            "sample_id": item.get("sample_id"),
            "natural_language": item.get("natural_language"),
            "cleaned_conditions": cleaned_sql,
            "dataset_constraints": dataset_constraints,
            "property_constraints": constraints,
            "groups": groups,
        }
        cleaned_data.append(new_item)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_data, f, ensure_ascii=False, indent=2)

    print(f"已处理 {len(cleaned_data)} 条记录，结果保存至: {output_path}")

    # 打印前 10 条预览
    print("\n========== 前 10 条预览 ==========\n")
    for item in cleaned_data[:10]:
        print(f"【Sample {item['sample_id']}】{item['natural_language']}")
        print(f"  清洗文本: {item['cleaned_conditions']}")
        if item['dataset_constraints']:
            print(f"  [数据集限定] {', '.join(item['dataset_constraints'])}")
        for c in item['property_constraints']:
            cond_strs = []
            for vc in c['conditions']:
                field_name = vc.get('field', 'UNKNOWN')
                if vc['operator'] == 'BETWEEN':
                    cond_strs.append(f"{field_name} BETWEEN {vc['value'][0]} AND {vc['value'][1]}")
                else:
                    cond_strs.append(f"{field_name} {vc['operator']} {vc['value']!r}")
            print(f"  → {'; '.join(cond_strs)}")
        # 展示 groups 结构
        if item['groups']:
            total_cond = sum(len(g['conditions']) for g in item['groups'])
            print(f"  [groups] 共{len(item['groups'])}个group, 总{total_cond}条conditions")
        print()


if __name__ == "__main__":
    main()
