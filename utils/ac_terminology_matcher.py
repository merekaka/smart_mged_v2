"""Re-export ac_terminology_matcher from its canonical root-level location."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ac_terminology_matcher import (  # noqa: F401
    ACNode,
    ACAutomaton,
    get_terminology_matcher,
    highlight_terms,
    search_terms,
    get_term_explanation,
)
