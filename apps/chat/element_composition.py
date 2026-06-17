"""
元素组成分析器
自动从单条材料数据中提取元素组成信息，用于饼图展示。

识别规则：
- 元素属性名：C, Si, Mn, P, S, Cr, Ni, Mo, V, Ti, Al, Cu, W, Co, Nb, B, N, Fe, Mg, Zn, Zr
- 这些属性通常出现在 object 属性组中
- 值格式：数值（如 "0.08"）、范围（如 "0.2~0.4"）、余量（如 "余量"）
"""
import logging
import re
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# 已知化学元素属性名列表
ELEMENT_PROPERTIES = {
    'C', 'Si', 'Mn', 'P', 'S', 'Cr', 'Ni', 'Mo', 'V', 'Ti',
    'Al', 'Cu', 'W', 'Co', 'Nb', 'B', 'N', 'Fe', 'Mg', 'Zn', 'Zr',
    'H', 'O', 'Ca', 'Sn', 'Pb', 'Sb', 'Bi', 'Be', 'Cd', 'Ag',
    'Au', 'Pt', 'Pd', 'Rh', 'Ru', 'Ir', 'Os', 'Re', 'Ta', 'Hf',
    'Sc', 'Y', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd',
    'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Th', 'U',
}


def _parse_element_value(val: Any) -> Any:
    """
    解析元素含量值。
    
    返回：
    - float: 成功解析的数值
    - 'remainder': 表示"余量"
    - None: 无法解析
    """
    if val is None:
        return None
    
    val_str = str(val).strip()
    if not val_str:
        return None
    
    # 处理"余量"（可能是 Unicode 或 GBK 编码）
    if '余' in val_str or val_str == '\u4f59\u91cf':
        return 'remainder'
    
    # 范围格式: 0.2~0.4 或 1.8-2.5 或 0.15~0.40
    if '~' in val_str or ('-' in val_str and val_str.replace('-', '').replace('.', '').isdigit()):
        # 区分负数和范围：范围中 '-' 前后都是数字
        parts = re.split(r'[~\-]', val_str)
        if len(parts) == 2:
            try:
                left = float(parts[0])
                right = float(parts[1])
                return (left + right) / 2
            except (ValueError, TypeError):
                pass
    
    # 尝试直接转数字
    try:
        return float(val_str)
    except (ValueError, TypeError):
        pass
    
    # 提取第一个数字（如 "≤0.12" → 0.12）
    match = re.search(r'\d+\.?\d*', val_str)
    if match:
        try:
            return float(match.group())
        except (ValueError, TypeError):
            pass
    
    return None


def build_element_composition(classified_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    从分类格式的单条数据中构建元素组成信息。
    
    :param classified_data: {"object": {...}, "operate": {...}, "result": {...}}
    :return: {
        "has_composition": bool,
        "elements": [{"name": "Ti", "value": 99.14, "raw": "余量"}, ...],
        "total_known": float,  # 已知元素总和
        "remainder": float,    # 余量值（100 - total_known）
    }
    """
    # 从 object 和 result 中查找元素属性
    all_props = {}
    for group in ('object', 'operate', 'result'):
        group_data = classified_data.get(group, {})
        if isinstance(group_data, dict):
            all_props.update(group_data)
    
    elements = []
    known_sum = 0.0
    remainder_elements = []
    
    for prop_name, raw_value in all_props.items():
        if prop_name not in ELEMENT_PROPERTIES:
            continue
        
        parsed = _parse_element_value(raw_value)
        
        if parsed == 'remainder':
            remainder_elements.append({
                "name": prop_name,
                "value": 0,  # 占位，后续计算
                "raw": str(raw_value),
                "is_remainder": True,
            })
        elif isinstance(parsed, (int, float)):
            elements.append({
                "name": prop_name,
                "value": round(parsed, 4),
                "raw": str(raw_value),
                "is_remainder": False,
            })
            known_sum += parsed
        else:
            # 无法解析，跳过
            logger.debug(f"build_element_composition: cannot parse {prop_name}={raw_value}")
            continue
    
    if not elements and not remainder_elements:
        return {
            "has_composition": False,
            "elements": [],
            "total_known": 0,
            "remainder": 0,
        }
    
    # 计算余量
    remainder = max(0, 100 - known_sum)
    
    # 如果有标记为"余量"的元素，将余量值分配给它
    for rem_elem in remainder_elements:
        rem_elem["value"] = round(remainder, 4)
        elements.append(rem_elem)
    
    # 按含量排序（从大到小）
    elements.sort(key=lambda x: x["value"], reverse=True)
    
    return {
        "has_composition": True,
        "elements": elements,
        "total_known": round(known_sum, 4),
        "remainder": round(remainder, 4),
    }
