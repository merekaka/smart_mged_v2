#!/usr/bin/env python
"""
================================================================================
intent_engine 交互式测试工具
================================================================================

用法:
    python tools/test_intent_engine.py

功能:
    手动输入自然语言查询，实时查看意图解析结果（Intent 对象）。
    支持连续输入，输入 q/quit/exit 退出。

================================================================================
"""
import os
import sys
import json

# 设置 Django 环境
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, PROJECT_ROOT)

import django
django.setup()

from apps.intent_engine.api import parse_intent


def print_intent(intent):
    """美化打印 Intent 对象"""
    if intent is None:
        print("\n  [结果] 解析失败或空输入，返回 None")
        return

    d = intent.to_dict()
    print("\n" + "=" * 60)
    print("  Intent 对象解析结果")
    print("=" * 60)
    print(f"  intent_type       : {d.get('intent_type')}")
    print(f"  query_mode        : {d.get('query_mode')}")
    print(f"  group_logic_op    : {d.get('group_logic_op')}")
    print(f"  limit             : {d.get('limit')}")
    print(f"  explanation       : {d.get('explanation')}")
    print(f"  target_properties : {d.get('target_properties')}")
    print(f"  limit             : {d.get('limit')}")
    print(f"  groups 数量       : {len(d.get('groups', []))}")

    for gi, g in enumerate(d.get('groups', [])):
        print(f"\n  --- groups[{gi}] ---")
        print(f"    logic_op  : {g.get('logic_op')}")
        print(f"    datasets  : {g.get('datasets')}")
        conditions = g.get('conditions', [])
        if conditions:
            for ci, c in enumerate(conditions):
                print(f"    conditions[{ci}]:")
                print(f"      field     : {c.get('field')}")
                print(f"      operator  : {c.get('operator')}")
                print(f"      value     : {c.get('value')}")
                print(f"      unit      : {c.get('unit')}")
                print(f"      agg_func  : {c.get('agg_func')}")
        else:
            print(f"    conditions: []")

    print("=" * 60)


def main():
    print("=" * 60)
    print("  intent_engine 交互式测试工具")
    print("  输入自然语言查询，查看解析后的 Intent 对象")
    print("  输入 q / quit / exit 退出")
    print("=" * 60)

    while True:
        try:
            user_input = input("\n>>> 请输入查询: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input.lower() in ("q", "quit", "exit"):
            print("再见！")
            break

        print(f"\n[解析中] {user_input!r} ...")
        intent = parse_intent(user_input)
        print_intent(intent)


if __name__ == "__main__":
    main()
