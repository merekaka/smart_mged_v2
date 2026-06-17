"""Re-export prompt templates from their canonical root-level location."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from prompt_template import *  # noqa: F401,F403
