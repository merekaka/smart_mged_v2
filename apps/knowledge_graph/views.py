"""
apps/knowledge_graph/views.py
------------------------------
Django views for:
  POST /api/graph/recommend   → RecommendView
  GET  /api/graph/term_graph  → TermGraphView
"""
import logging
import json

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from core.data_utils import get_processed_data
from utils.ac_terminology_matcher import highlight_terms
from .neo4j_client import get_graph

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class RecommendView(View):
    """POST /api/graph/recommend"""

    def post(self, request):
        try:
            body = json.loads(request.body)
            if not body or "id" not in body or "title" not in body:
                return JsonResponse({"error": "Missing required parameters"}, status=400)

            current_id = body["id"]
            current_title = body["title"]
            graph, matcher = get_graph()
            results = []

            # 1. Get term name
            try:
                query_term = """
                MATCH (term)-[:hasDataSet]->(ds:DataSet {name: $ds_name})
                RETURN term
                """
                result_term = graph.run(query_term, ds_name=current_title)
                term_name = None
                for record in result_term:
                    term_node = record["term"]
                    term_name = term_node.get("name")
                    break
                if not term_name:
                    return JsonResponse({"results": []})
            except Exception as e:
                logger.error(f"获取术语失败: {e}")
                return JsonResponse({"results": []})

            # 2.1 Same-term recommendations
            try:
                q = """
                MATCH (targetDs:DataSet {name: $ds_name})<-[:hasDataSet]-(term:Term)-[:hasDataSet]->(otherDs:DataSet)
                WHERE otherDs <> targetDs
                RETURN otherDs
                """
                for record in graph.run(q, ds_name=current_title):
                    ds = record["otherDs"]
                    ds_id = ds.get("_id") or ds.get("name")
                    if ds_id != current_id:
                        results.append({"id": ds_id, "title": ds.get("name"), "source": "同术语"})
            except Exception as e:
                logger.warning(f"同术语推荐失败: {e}")

            # 2.2 Term-relationship recommendations
            try:
                q = """
                MATCH (targetTerm:Term {name: $term_name})-[r]->(otherTerm:Term)-[:hasDataSet]->(ds:DataSet)
                RETURN ds
                """
                for record in graph.run(q, term_name=term_name):
                    ds = record["ds"]
                    ds_id = ds.get("_id") or ds.get("name")
                    if ds_id != current_id:
                        results.append({"id": ds_id, "title": ds.get("name"), "source": "术语关系"})
            except Exception as e:
                logger.warning(f"术语关系推荐失败: {e}")

            # 2.3 Same-classification recommendations
            try:
                q_cls = """
                MATCH path = (term:Term {name: $term_name})-[:isAKindOf]->(classification:Classification)
                    -[:subclassOf*]->(head:Head {name: 'Classification'})
                RETURN [node IN nodes(path) WHERE node:Classification] AS classificationNodes
                """
                classification_name = None
                for record in graph.run(q_cls, term_name=term_name):
                    nodes = record["classificationNodes"]
                    if nodes:
                        classification_name = nodes[0].get("name")
                        break
                if classification_name:
                    q2 = """
                    MATCH (classification:Classification {name: $cls_name})<-[:isAKindOf]-(term:Term)
                        -[:hasDataSet]->(ds:DataSet)
                    WHERE term.name <> $term_name
                    RETURN ds
                    """
                    for record in graph.run(q2, cls_name=classification_name, term_name=term_name):
                        ds = record["ds"]
                        ds_id = ds.get("_id") or ds.get("name")
                        if ds_id != current_id:
                            results.append({"id": ds_id, "title": ds.get("name"), "source": "同分类"})
            except Exception as e:
                logger.warning(f"同分类推荐失败: {e}")

            # De-duplicate and enrich
            seen, final = set(), []
            for item in results:
                iid = item["id"]
                if iid in seen:
                    continue
                seen.add(iid)
                processed = get_processed_data(iid)
                item["abstract"] = processed.get("abstract", "") if processed else ""
                try:
                    item["highlight_title"] = highlight_terms(item["title"])
                    item["highlight_abstract"] = highlight_terms(item["abstract"])
                except Exception:
                    pass
                final.append(item)

            return JsonResponse({"results": final})

        except Exception as e:
            logger.error(f"RecommendView error: {e}")
            return JsonResponse({"error": str(e)}, status=500)


class TermGraphView(View):
    """GET /api/graph/term_graph?term=<term>"""

    def get(self, request):
        term = request.GET.get("term")
        if not term:
            return JsonResponse({"error": "Missing term"}, status=400)

        graph, matcher = get_graph()
        node = set()
        relation = []
        node2type = {}

        result = list(matcher.match().where(f"_.name = '{term}'"))
        if not result and term:
            alt = (term[0].lower() + term[1:]) if term[0].isupper() else (term[0].upper() + term[1:])
            result = list(matcher.match().where(f"_.name = '{alt}'"))
            if result:
                term = alt
        if not result:
            return JsonResponse({"error": f"Term '{term}' not found"}, status=404)

        main_node = result[0]
        node.add(main_node["name"])
        node2type[main_node["name"]] = list(main_node.labels)[0]

        query = f"""
        MATCH (start {{name: "{term}"}})-[r]->(end)
        RETURN type(r) as rel, end.name as name, labels(end) as labels
        """
        for record in graph.run(query):
            node.add(record["name"])
            relation.append([term, record["name"], record["rel"]])
            node2type[record["name"]] = record["labels"][0]

        node = list(node)
        trans = {n: i for i, n in enumerate(node)}
        edges = [[trans[re[0]], trans[re[1]], re[2]] for re in relation]
        colors = {
            "Term": "#82B29A",
            "Classification": "#90BEE0",
            "Head": "#FFA07A",
            "Other": "#F4F1DE",
        }

        return JsonResponse({
            "nodes": [
                {
                    "id": i,
                    "label": node[i],
                    "color": colors.get(node2type.get(node[i], "Other"), "#CCCCCC"),
                    "size": 40 if node2type.get(node[i], "") in ["Head", "Classification"] else 20,
                    "title": node2type.get(node[i], ""),
                }
                for i in range(len(node))
            ],
            "edges": [
                {"from": e[0], "to": e[1], "label": e[2], "arrows": "to"}
                for e in edges
            ],
        })
