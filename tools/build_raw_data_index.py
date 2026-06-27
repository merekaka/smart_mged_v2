#!/usr/bin/env python3
"""
原始数据索引构建脚本

扫描 data/ 目录下所有 JSON 文件，建立 _meta_id -> (文件路径, 数组索引) 的映射索引。
索引文件保存为 JSON 格式，供后端快速查找原始数据。

用法:
    python tools/build_raw_data_index.py
    python tools/build_raw_data_index.py --data-dir /path/to/data --output /path/to/index.json

索引格式:
    {
        "_meta_id_1": {"file": "data/钛合金数据.json", "index": 0},
        "_meta_id_2": {"file": "data/铝合金数据.json", "index": 5},
        ...
    }
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any


def build_index(data_dir: str, output_path: str) -> Dict[str, Any]:
    """
    扫描 data_dir 下所有 .json 文件，构建 _meta_id 索引。
    """
    data_path = Path(data_dir)
    if not data_path.exists():
        raise FileNotFoundError(f"数据目录不存在: {data_dir}")

    index: Dict[str, Any] = {}
    json_files = sorted([f for f in data_path.iterdir() if f.suffix == ".json"])

    print(f"扫描 {len(json_files)} 个 JSON 文件...")

    for json_file in json_files:
        rel_path = f"data/{json_file.name}"
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [跳过] {rel_path}: 读取失败 ({e})")
            continue

        if not isinstance(data, list):
            print(f"  [跳过] {rel_path}: 不是数组格式")
            continue

        count = 0
        for idx, record in enumerate(data):
            meta_id = record.get("_meta_id")
            if meta_id is not None:
                key = str(meta_id)
                if key in index:
                    # 重复 _meta_id 警告（理论上不应该发生）
                    print(f"  [警告] _meta_id={key} 重复，文件: {rel_path} 和 {index[key]['file']}")
                index[key] = {
                    "file": rel_path,
                    "index": idx,
                    "title": record.get("title", ""),
                }
                count += 1

        print(f"  [OK] {rel_path}: {count} 条记录")

    # 保存索引
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"\n索引构建完成: {len(index)} 条记录")
    print(f"索引文件保存至: {output_path}")
    return index


def main():
    parser = argparse.ArgumentParser(description="构建原始数据索引")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="数据目录路径 (默认: data)",
    )
    parser.add_argument(
        "--output",
        default="data/raw_data_index.json",
        help="索引文件输出路径 (默认: data/raw_data_index.json)",
    )
    args = parser.parse_args()

    build_index(args.data_dir, args.output)


if __name__ == "__main__":
    main()
