#!/usr/bin/env python
"""
================================================================================
动态刷新属性白名单
================================================================================

功能:
    查询 MySQL 数据库 smart_mged.property_table，获取 property_name 和
    property_description 两个字段，生成 property_names_dynamic.txt。

用法:
    作为独立脚本执行:
        python refresh_property_names.py

    或在 Django 环境中被导入调用:
        from apps.intent_engine.resources.refresh_property_names import refresh
        refresh()

输出文件:
    同目录下的 property_names_dynamic.txt
    格式: 每行 "property_name: property_description"
================================================================================
"""
import os
import sys


def _setup_django():
    """自动推断项目根目录并设置 Django 环境。"""
    # 本文件位于 apps/intent_engine/resources/
    # 项目根目录需要向上回溯 4 层
    current_file = os.path.abspath(__file__)
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
    )
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

    import django
    django.setup()


def refresh() -> bool:
    """
    查询数据库并生成 property_names_dynamic.txt。
    返回 True 表示成功，False 表示失败。
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(current_dir, "property_names_dynamic.txt")

    try:
        from django.db import connections
        with connections['default'].cursor() as cursor:
            cursor.execute(
                "SELECT property_name, property_description "
                "FROM property_table "
                "ORDER BY property_name"
            )
            rows = cursor.fetchall()
    except Exception as e:
        print(f"[refresh_property_names] 查询数据库失败: {e}")
        return False

    lines = ["# property_name: property_description\n"]
    for name, desc in rows:
        # 清理换行符，避免破坏 txt 格式
        desc = desc.replace('\n', ' ').replace('\r', '') if desc else ''
        lines.append(f"{name}: {desc}\n")

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)
    except Exception as e:
        print(f"[refresh_property_names] 写入文件失败: {e}")
        return False

    print(f"[refresh_property_names] 已刷新 {len(rows)} 条属性到 {output_file}")
    return True


def load_dynamic_properties() -> list:
    """
    读取已生成的 property_names_dynamic.txt，返回 [(name, desc), ...] 列表。
    若文件不存在，自动调用 refresh() 生成。
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(current_dir, "property_names_dynamic.txt")

    if not os.path.exists(output_file):
        _setup_django()
        refresh()

    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            result = []
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if ':' in line:
                    name, desc = line.split(':', 1)
                    result.append((name.strip(), desc.strip()))
                else:
                    result.append((line, ''))
            return result
    except Exception as e:
        print(f"[refresh_property_names] 读取文件失败: {e}")
        return []


if __name__ == '__main__':
    _setup_django()
    refresh()
