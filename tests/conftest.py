from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
raw = str(project_root)
if raw not in sys.path:
    sys.path.insert(0, raw)

test_home = Path(tempfile.mkdtemp(prefix="s4code-test-home-"))
config_home = test_home / "config"
data_home = test_home / "data"
cache_home = test_home / "cache"
os.environ["XDG_CONFIG_HOME"] = str(config_home)
os.environ["XDG_DATA_HOME"] = str(data_home)
os.environ["XDG_CACHE_HOME"] = str(cache_home)
os.environ.setdefault("LLM_API_KEY", "test-key")

s4_config_dir = config_home / "s4code"
s4_config_dir.mkdir(parents=True, exist_ok=True)
(s4_config_dir / "models.yaml").write_text(
    "model_profiles:\n"
    "  default:\n"
    "    provider: openai\n"
    "    model: gpt-4.1\n"
    "    temperature: 0.7\n"
    "active_model_profile: default\n",
    encoding="utf-8",
)
