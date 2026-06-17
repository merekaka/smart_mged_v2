from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pymysql


def _project_root() -> Path:
    # .../mged_v2/szl/test/batch_intent_sql_eval.py -> .../mged_v2
    return Path(__file__).resolve().parents[2]


def _setup_django() -> None:
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    import django  # noqa: WPS433

    django.setup()


def _safe_value_list(values: Any) -> List[Any]:
    """智能解析数值：自动展平嵌套列表/字典，整数转int，浮点数保留float，非数值保留原样"""
    out: List[Any] = []
    
    def _extract(item):
        if isinstance(item, (list, tuple, set)):
            # 如果是列表或元组，遍历其内部元素继续提取
            for i in item:
                _extract(i)
        elif isinstance(item, dict):
            # 如果是字典，提取所有的 value
            for v in item.values():
                _extract(v)
        elif item is not None and item != "":
            # 到底层标量值了，开始转换
            try:
                float_v = float(item)
                if float_v.is_integer():
                    out.append(int(float_v))
                else:
                    out.append(float_v)
            except (ValueError, TypeError):
                out.append(item)
                
    # 启动递归提取
    _extract(values)
    return out

def _recall(gold: List[Any], pred: List[Any]) -> float:
    if not gold:
        return 1.0 if not pred else 0.0
    g = set(gold)
    p = set(pred)
    return len(g & p) / len(g)


def _extract_sql_text(exec_result: Dict[str, Any]) -> str:
    mode = str(exec_result.get("query_mode") or "simple")
    if mode == "complex":
        return str(exec_result.get("final_sql_rendered") or exec_result.get("final_sql") or "")
    return str(exec_result.get("sql_rendered") or exec_result.get("sql") or "")


def _build_payload_from_intent_dict(intent_dict: Dict[str, Any], original_query: str) -> Dict[str, Any]:
    query_mode = str(intent_dict.get("query_mode") or "").lower()
    groups = intent_dict.get("groups") or []
    if query_mode not in {"simple", "complex"}:
        query_mode = "complex" if len(groups) > 1 else "simple"

    return {
        "original_query": original_query or intent_dict.get("explanation", ""),
        "intent": intent_dict,
        "structured_query": {
            "query_mode": query_mode,
            "group_logic_op": str(intent_dict.get("group_logic_op", "and")).lower(),
            "limit": intent_dict.get("limit", 0),
            "groups": groups,
        },
    }


def _prepare_executor(conn: pymysql.connections.Connection):
    from szl.intent_sql_executor import IntentSqlExecutor

    executor = IntentSqlExecutor()
    sql = "SELECT property_id, property_name FROM smart_mged.property_table"
    with conn.cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()
    executor.property_id_map = {str(r["property_name"]): int(r["property_id"]) for r in rows}
    executor.dataset_property_map = {}
    return executor


def run_eval(
    samples_path: Path,
    sql_txt_path: Path,
    result_txt_path: Path,
    intent_txt_path: Path,
    limit: int = 0,
) -> Tuple[int, int, float, float]:
    from apps.intent_engine import api as intent_api
    from szl.intent_sql_executor import IntentSqlExecutor

    parse_intent = intent_api.parse_intent

    with samples_path.open("r", encoding="utf-8") as f:
        samples = json.load(f)

    if not isinstance(samples, list):
        raise ValueError(f"样本文件格式错误，期望 list，实际: {type(samples)}")

    if limit > 0:
        samples = samples[:limit]

    sql_txt_path.parent.mkdir(parents=True, exist_ok=True)
    result_txt_path.parent.mkdir(parents=True, exist_ok=True)
    intent_txt_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(samples)
    ok = 0
    fail = 0

    macro_sum = 0.0
    micro_inter = 0
    micro_gold = 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sql_txt_path.open("w", encoding="utf-8") as sql_f, result_txt_path.open("w", encoding="utf-8") as res_f, intent_txt_path.open("w", encoding="utf-8") as intent_f:
        sql_f.write(f"batch_intent_sql_eval 生成时间: {now}\n")
        sql_f.write(f"样本文件: {samples_path}\n")
        sql_f.write("=" * 120 + "\n\n")

        res_f.write(f"batch_intent_sql_eval 生成时间: {now}\n")
        res_f.write(f"样本文件: {samples_path}\n")
        res_f.write("=" * 120 + "\n\n")

        intent_f.write(f"batch_intent_sql_eval intent_dict 生成时间: {now}\n")
        intent_f.write(f"样本文件: {samples_path}\n")
        intent_f.write("=" * 120 + "\n\n")

        db_conf = {
            "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
            "port": int(os.environ.get("MYSQL_PORT", "3306")),
            "user": os.environ.get("MYSQL_USER", "root"),
            "password": os.environ.get("MYSQL_PASSWORD", "CHANGE_ME_IN_PRODUCTION"),
            "database": os.environ.get("MYSQL_DATABASE", "smart_mged"),
            "charset": "utf8mb4",
            "autocommit": True,
            "cursorclass": pymysql.cursors.DictCursor,
        }
        with pymysql.connect(**db_conf) as conn:
            executor = _prepare_executor(conn)

            for idx, item in enumerate(samples, start=1):
                sample_id = item.get("sample_id", idx)
                nl = str(item.get("natural_language", "")).strip()
                
                # 1. 使用新的方法提取 gold，保留小数和整数
                gold = _safe_value_list(item.get("result", []))

                sql_f.write(f"[sample_id={sample_id}]\n")
                sql_f.write(f"natural_language: {nl}\n")

                try:
                    intent = parse_intent(nl)
                    if intent is None:
                        raise RuntimeError("parse_intent 返回 None")

                    intent_dict = intent.to_dict()
                    payload = _build_payload_from_intent_dict(intent_dict, nl)
                    mode = str((payload.get("structured_query") or {}).get("query_mode") or "simple").lower()
                    if mode == "complex":
                        exec_result = executor._execute_complex(conn, payload)
                    else:
                        exec_result = executor._execute_simple(conn, payload)

                    sql_text = _extract_sql_text(exec_result)
                    
# 2. 增强 pred 的提取逻辑，兼容普通检索和聚合查询
                    answer = exec_result.get("answer") or {}

                    # 聚合查询优先返回聚合值作为 pred，不返回 data_id
                    raw_pred = []
                    if isinstance(answer, dict) and answer.get("aggregations"):
                        raw_pred = [a.get("agg_value") for a in answer.get("aggregations") if a.get("agg_value") is not None]
                    elif isinstance(answer, dict) and "matched_data_ids" in answer:
                        raw_pred = answer.get("matched_data_ids") or []
                    elif isinstance(answer, (list, tuple)):
                        raw_pred = list(answer)
                    else:
                        raw_pred = [answer]

                    pred = _safe_value_list(raw_pred)

                    rec = _recall(gold, pred)
                    # 先通过集合操作获取交集，再为了稳定输出进行排序(将所有值转为str再排序防止混合类型报错)
                    inter = sorted(list(set(gold) & set(pred)), key=lambda x: (isinstance(x, str), x))

                    ok += 1
                    macro_sum += rec
                    micro_inter += len(inter)
                    micro_gold += len(set(gold))

                    sql_f.write("intent_dict:\n")
                    sql_f.write(json.dumps(intent_dict, ensure_ascii=False) + "\n")
                    sql_f.write("generated_sql:\n")
                    sql_f.write(sql_text + "\n")
                    sql_f.write("-" * 120 + "\n\n")

                    res_f.write(f"[sample_id={sample_id}]\n")
                    res_f.write(f"natural_language: {nl}\n")
                    res_f.write(f"gold: {sorted(list(set(gold)), key=lambda x: (isinstance(x, str), x))}\n")
                    res_f.write(f"pred: {sorted(list(set(pred)), key=lambda x: (isinstance(x, str), x))}\n")
                    res_f.write(f"intersection: {inter}\n")
                    res_f.write(f"recall: {rec:.6f}\n")
                    res_f.write("-" * 120 + "\n\n")

                    intent_f.write(f"[sample_id={sample_id}]\n")
                    intent_f.write(f"natural_language: {nl}\n")
                    intent_f.write("intent_dict:\n")
                    intent_f.write(json.dumps(intent_dict, ensure_ascii=False, indent=2) + "\n")
                    intent_f.write("-" * 120 + "\n\n")

                except Exception as e:
                    fail += 1
                    sql_f.write(f"ERROR: {e}\n")
                    sql_f.write(traceback.format_exc() + "\n")
                    sql_f.write("-" * 120 + "\n\n")

                    res_f.write(f"[sample_id={sample_id}]\n")
                    res_f.write(f"natural_language: {nl}\n")
                    res_f.write(f"ERROR: {e}\n")
                    res_f.write("-" * 120 + "\n\n")

                    intent_f.write(f"[sample_id={sample_id}]\n")
                    intent_f.write(f"natural_language: {nl}\n")
                    intent_f.write(f"ERROR: {e}\n")
                    intent_f.write("-" * 120 + "\n\n")

                if idx % 20 == 0 or idx == total:
                    print(f"进度: {idx}/{total}, 成功={ok}, 失败={fail}")

        macro_recall = (macro_sum / ok) if ok else 0.0
        micro_recall = (micro_inter / micro_gold) if micro_gold else 0.0

        summary = {
            "total": total,
            "success": ok,
            "failed": fail,
            "macro_recall": round(macro_recall, 6),
            "micro_recall": round(micro_recall, 6),
            "micro_intersection": micro_inter,
            "micro_gold_total": micro_gold,
        }

        res_f.write("SUMMARY\n")
        res_f.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")

    return ok, fail, macro_recall, micro_recall


def main() -> None:
    default_samples = Path(__file__).resolve().parent / "sql_nl_test_samples_500.json"
    default_sql_txt = Path(__file__).resolve().parent / "generated_sql_from_intent.txt"
    default_result_txt = Path(__file__).resolve().parent / "query_results_and_recall.txt"
    default_intent_txt = Path(__file__).resolve().parent / "intent_dict_results.txt"

    parser = argparse.ArgumentParser(description="批量调用 parse_intent + intent_sql_executor 并评估召回率")
    parser.add_argument("--samples", type=Path, default=default_samples, help="样本 JSON 路径")
    parser.add_argument("--sql-out", type=Path, default=default_sql_txt, help="SQL 输出 txt 路径")
    parser.add_argument("--result-out", type=Path, default=default_result_txt, help="结果与召回率 txt 路径")
    parser.add_argument("--intent-out", type=Path, default=default_intent_txt, help="intent_dict 输出 txt 路径")
    parser.add_argument("--limit", type=int, default=0, help="仅跑前 N 条，0 表示全部")
    args = parser.parse_args()

    _setup_django()

    ok, fail, macro_recall, micro_recall = run_eval(
        samples_path=args.samples,
        sql_txt_path=args.sql_out,
        result_txt_path=args.result_out,
        intent_txt_path=args.intent_out,
        limit=args.limit,
    )

    print("执行完成")
    print(f"成功: {ok}, 失败: {fail}")
    print(f"macro_recall: {macro_recall:.6f}")
    print(f"micro_recall: {micro_recall:.6f}")
    print(f"SQL输出: {args.sql_out}")
    print(f"结果输出: {args.result_out}")
    print(f"intent 输出: {args.intent_out}")


if __name__ == "__main__":
    main()