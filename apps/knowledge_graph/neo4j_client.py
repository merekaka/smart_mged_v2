"""
apps/knowledge_graph/neo4j_client.py
-------------------------------------
Lazy singleton for the Neo4j connection.
"""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

_graph = None
_matcher = None


def get_graph():
    global _graph, _matcher
    if _graph is None:
        from py2neo import Graph, NodeMatcher
        _graph = Graph(settings.NEO4J_URL, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD))
        _matcher = NodeMatcher(_graph)
        logger.info("Neo4j 连接已建立")
    return _graph, _matcher
