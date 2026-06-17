"""
Follow-up 查询编排引擎
整合"取当前结果 → 意图解析 → SQL 生成 → 执行 → 格式化回答"完整流程。
"""
import logging
from typing import List, Dict, Any

from apps.follow_up.intent_engine.parser import IntentParser
from apps.follow_up.result_store import ResultStore
from apps.follow_up.filter.sql_builder import IntentSQLBuilder

logger = logging.getLogger(__name__)


class FollowUpQueryEngine:
    """
    多轮对话中的 follow-up 查询引擎。

    使用方式：
        engine = FollowUpQueryEngine()
        result = engine.query("密度小于5的", current_results)
        # result -> {"answer": "...", "results": [...], "total": 5, "sql": "...", "intent": {...}}
    """

    def __init__(self):
        self.parser = IntentParser()

    def query(
        self,
        user_text: str,
        current_results: List[Dict[str, Any]],
        store: "ResultStore" = None,
        intent_dict: dict = None,
    ) -> Dict[str, Any]:
        """
        执行一次 follow-up 查询。

        :param user_text: 用户的 follow-up 问题文本
        :param current_results: 当前有效结果集（上一轮结果或首轮缓存），用于获取列名和兜底
        :param store: 外部传入的 ResultStore（持久化表），优先使用；为 None 时回退到内存模式
        :param intent_dict: 已解析的 intent dict（若已在外部解析好）
        :return: 包含 answer / results / total / sql / intent 的字典
        """
        logger.info(f"FollowUpQueryEngine.query: user_text={user_text[:100]!r}, current_results={len(current_results)}")
        if not current_results:
            logger.warning("FollowUpQueryEngine.query: no current results available")
            return {
                "error": "当前对话没有可查询的结果集",
                "answer": "当前对话没有关联的查询数据，无法回答。",
                "results": [],
                "total": 0,
                "sql": None,
                "intent": {},
            }

        # 1) 意图解析（如果外部未传入）
        if intent_dict is None:
            intent = self.parser.parse(user_text)
            if not intent:
                logger.warning(f"FollowUpQueryEngine.query: intent parsing failed for user_text={user_text[:100]!r}")
                return {
                    "error": "意图解析失败",
                    "answer": "无法理解您的问题，请尝试更具体的描述。",
                    "results": [],
                    "total": 0,
                    "sql": None,
                    "intent": {},
                }
            intent_dict = intent.to_dict()
        logger.info(f"FollowUpQueryEngine.query: intent mode={intent_dict.get('query_mode')}, groups={len(intent_dict.get('groups', []))}, scope={intent_dict.get('follow_up_scope', 'current')}")

        # 2) 加载结果到 SQLite
        if store is None:
            store = ResultStore(current_results)
            logger.info(f"FollowUpQueryEngine.query: ResultStore (:memory:) loaded with {len(current_results)} rows")
        else:
            logger.info(f"FollowUpQueryEngine.query: using external ResultStore, table={store.table_name}")

        try:
            # 3) 生成 SQL（传入可用列名，支持带前缀列名解析）
            columns = list(current_results[0].keys()) if current_results else []
            builder = IntentSQLBuilder(intent_dict, columns=columns, table_name=store.table_name)
            sql, params = builder.build()
            logger.info(f"FollowUpQueryEngine.query: SQL built, sql_length={len(sql)}, params={len(params)}")

            # 4) 执行查询
            rows = store.query(sql, params)
            logger.info(f"FollowUpQueryEngine.query: SQL executed, rows returned={len(rows)}")

            # 5) 格式化回答
            answer = self._format_answer(rows, intent_dict, sql)

            return {
                "answer": answer,
                "sql": sql,
                "params": params,
                "results": rows,
                "total": len(rows),
                "intent": intent_dict,
            }

        except Exception as e:
            logger.error(f"FollowUpQueryEngine.query failed: {e}", exc_info=True)
            return {
                "error": f"查询执行失败: {str(e)}",
                "answer": f"查询执行出错：{str(e)}",
                "results": [],
                "total": 0,
                "sql": sql if 'sql' in dir() else None,
                "intent": intent_dict,
            }
        finally:
            store.close()

    def _format_answer(self, rows: List[Dict[str, Any]], intent: Dict[str, Any], sql: str) -> str:
        """根据查询结果生成回答文本（规则化描述，非 LLM 润色）。"""
        total = len(rows)

        if total == 0:
            return "在当前结果中未找到符合条件的数据。"

        # 判断是否为聚合查询（非 max/min 的聚合会返回单行聚合值）
        groups = intent.get("groups", [])
        conditions = groups[0].get("conditions", []) if groups else []
        agg_conds = [c for c in conditions if c.get("agg_func")]

        if agg_conds:
            agg = agg_conds[0]
            field = agg.get("field", "")
            agg_func = agg.get("agg_func", "").lower()

            # max / min：返回的是完整记录（单条），按常规方式描述
            if agg_func in ("max", "min") and total > 0:
                titles = [r.get("title", r.get("id", "未命名")) for r in rows[:3]]
                title_str = "、".join(titles)
                suffix = f"等共 {total} 条结果" if total > 1 else ""
                agg_label = "最大" if agg_func == "max" else "最小"
                return f"在当前结果中，{title_str}{suffix}的{field}为{agg_label}值。"

            # max_n / min_n：返回排序后的前 N 条记录
            if agg_func in ("max_n", "min_n") and total > 0:
                titles = [r.get("title", r.get("id", "未命名")) for r in rows[:3]]
                title_str = "、".join(titles)
                agg_label = "最大" if agg_func == "max_n" else "最小"
                return f"在当前结果中，按{field}的{agg_label}值排序，前 {total} 条结果为：{title_str}等。"

            # avg / sum / count / variance：返回的是聚合数值
            if total == 1 and rows[0]:
                # 聚合结果通常只有一行一列
                key = list(rows[0].keys())[0] if rows[0] else "result"
                val = rows[0].get(key)
                return f"在当前结果中，{field} 的 {agg_func} 值为 {val}。"

        # 普通条件过滤
        titles = [r.get("title", r.get("id", "未命名")) for r in rows[:3]]
        title_str = "、".join(titles)
        suffix = f"等共 {total} 条结果" if total > 3 else f"共 {total} 条结果"
        return f"在当前结果中筛选出：{title_str}{suffix}。"
