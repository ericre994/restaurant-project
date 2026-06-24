"""Single place that puts the prototype on sys.path and imports it.

`prototype/recommend.py` is the source of truth for the recommendation pipeline
and LLM calls; both `recommender` and `taste` import `proto` from here so the
path setup lives in exactly one spot (and there's no import cycle between them).
"""
import sys
from pathlib import Path

_PROTO_DIR = Path(__file__).resolve().parents[2] / "prototype"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

import recommend as proto  # noqa: E402,F401  (re-exported)
