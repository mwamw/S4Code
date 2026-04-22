"""Manual example for palette-driven model/session selection and session forking.

This example is intentionally not executed during implementation.
It uses the real EasyLLM configuration requested by the user.
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

from s4code.query_engine import S4QueryEngine


REAL_LLM_PROFILE = {
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
}


def main() -> None:
    engine = S4QueryEngine(
        cwd=easyagent_root,
        session_overrides=REAL_LLM_PROFILE,
    )

    print("=== Palette + Session Management Example ===")
    print()
    print("Start S4Code and try these real interactions:")
    print("1. Type /model")
    print("2. Use ↑ / ↓ to choose a profile")
    print("3. Press Enter to switch the active profile")
    print()
    print("4. Type /session fork review-branch")
    print("5. Confirm the current session id changed")
    print("6. Type /resume")
    print("7. Use ↑ / ↓ to choose a saved session")
    print("8. Press Enter to load it")
    print()
    print("Clipboard actions:")
    print("- /copy transcript")
    print("- /copy last")
    print("- Ctrl+Shift+C")
    print("- Ctrl+Alt+C")
    print()
    print("Current model profiles:")
    for item in engine.get_model_choices():
        marker = "*" if item["active"] else "-"
        print(f"{marker} {item['name']}: {item['provider']} / {item['model']}")


if __name__ == "__main__":
    main()
