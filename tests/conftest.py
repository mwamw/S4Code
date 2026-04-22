from __future__ import annotations

import sys
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
raw = str(project_root)
if raw not in sys.path:
    sys.path.insert(0, raw)
