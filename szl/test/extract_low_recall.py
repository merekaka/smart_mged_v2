#!/usr/bin/env python3
"""
提取 recall 值小于阈值的 sample_id
用法: python extract_low_recall.py [输入文件路径] [阈值]
默认读取: query_results_and_recall.txt
默认输出: low_recall_samples.txt
"""

import sys
import re
from pathlib import Path
from datetime import datetime


def extract_low_recall_samples(filepath: Path, threshold: float = 0.95):
    """从文件中提取 recall < threshold 的 sample_id"""
    low_recall_samples = []
    current_sample_id = None

    with filepath.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # 匹配 sample_id
            sample_match = re.match(r"\[sample_id=(\d+)\]", line)
            if sample_match:
                current_sample_id = int(sample_match.group(1))
                continue

            # 匹配 recall 行
            recall_match = re.match(r"recall:\s*([\d.]+)", line)
            if recall_match and current_sample_id is not None:
                recall_value = float(recall_match.group(1))
                if recall_value < threshold:
                    low_recall_samples.append({
                        "sample_id": current_sample_id,
                        "recall": recall_value,
                    })
                current_sample_id = None

    return low_recall_samples


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    default_input = script_dir / "query_results_and_recall.txt"
    default_output = script_dir / "low_recall_samples.txt"

    filepath = Path(sys.argv[1]) if len(sys.argv) > 1 else default_input
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.95
    output_path = Path(sys.argv[3]) if len(sys.argv) > 3 else default_output

    if not filepath.exists():
        print(f"错误: 找不到文件 {filepath}")
        sys.exit(1)

    results = extract_low_recall_samples(filepath, threshold)

    lines = []
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"源文件: {filepath}")
    lines.append(f"阈值: recall < {threshold}")
    lines.append(f"共找到 {len(results)} 条 recall < {threshold} 的数据")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"{'sample_id':<12}{'recall':<10}")
    lines.append("-" * 22)
    for item in results:
        lines.append(f"{item['sample_id']:<12}{item['recall']:<10.6f}")
    lines.append("")
    lines.append("列表格式:")
    lines.append(str([item["sample_id"] for item in results]))

    content = "\n".join(lines)

    with output_path.open("w", encoding="utf-8") as f:
        f.write(content + "\n")

    print(content)
    print(f"\n结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
