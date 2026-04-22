"""Manual reference example for S4Code YAML configuration.

This example is intentionally not executed during implementation.
It uses the real EasyLLM profile requested by the user.
"""

from __future__ import annotations

import sys
from pathlib import Path


example_dir = Path(__file__).resolve().parent
project_root = example_dir.parent
easyagent_root = project_root.parent / "EasyAgent"

for candidate in (project_root, easyagent_root):
    raw = str(candidate)
    if raw not in sys.path:
        sys.path.insert(0, raw)

from s4code.config import S4Settings, dump_settings_yaml


def main() -> None:
    settings = S4Settings.model_validate(
        {
            "active_model_profile": "local-qwen",
            "model_profiles": {
                "local-qwen": {
                    "provider": "openai",
                    "base_url": "http://127.0.0.1:5124/v1",
                    "api_key": "122",
                    "model": "qwen3.5-9b",
                    "temperature": 0.2,
                    "timeout": 120,
                    "reasoning_effort": "high",
                    "reasoning_summary": "auto",
                },
                "claude-local": {
                    "provider": "anthropic_native",
                    "base_url": "http://127.0.0.1:5124/v1",
                    "api_key": "122",
                    "model": "claude-sonnet-4",
                },
            },
            "context": {
                "enabled": True,
                "max_tokens": 24000,
                "history_compactor": "llm",
                "recent_turns": 4,
            },
            "product": {
                "permission_mode": "accept_edits",
                "enable_codeintel": True,
                "enable_mcp": True,
            },
        }
    )

    print("=== ~/.config/s4code/config.yaml ===")
    print(dump_settings_yaml(settings))
    print()
    print("Project-level overrides live at: <repo>/.s4code/config.yaml")
    print("Use /model to switch profile and /context to inspect context usage.")


if __name__ == "__main__":
    main()
