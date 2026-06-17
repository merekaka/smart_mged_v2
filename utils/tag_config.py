"""Re-export TAG_ID_MAPPING from its canonical root-level location."""
import sys, os

# Add thesis/ directory to path so `tag_config` is importable
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_THESIS_DIR = os.path.join(_PROJECT_ROOT, "thesis")
if _THESIS_DIR not in sys.path:
    sys.path.insert(0, _THESIS_DIR)

from tag_config import TAG_ID_MAPPING  # noqa: F401
