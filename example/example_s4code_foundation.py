"""Manual S4Code foundation example.

This example is intentionally not executed by the implementation step.
It uses the real EasyLLM config requested by the user.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


example_dir = Path(__file__).resolve().parent
project_root = example_dir.parent
easyagent_root = project_root.parent / "EasyAgent"

for candidate in (project_root, easyagent_root):
    raw = str(candidate)
    if raw not in sys.path:
        sys.path.insert(0, raw)

from s4code.commands import register_builtin_commands
from s4code.query_engine import S4QueryEngine


REAL_LLM_OVERRIDES = {
    "llm": {
        "provider": "openai",
        "base_url": "http://127.0.0.1:5124/v1",
        "api_key": "122",
        "model": "qwen3.5-9b",
    }
}


def main() -> None:
    workspace = easyagent_root
    engine = S4QueryEngine(
        cwd=workspace,
        session_overrides=REAL_LLM_OVERRIDES,
    )
    register_builtin_commands(engine.command_registry)

    print("=== S4Code Foundation Example ===")
    print(f"Workspace: {workspace}")
    print()
    print("=== Status ===")
    print(engine.format_status())
    print()
    print("=== /files example ===")
    print(engine.command_registry.execute(engine, "/files example").message)
    print()
    print("=== /tasks example ===")
    print(engine.command_registry.execute(engine, "/tasks").message)
    print()
    print("=== /agents example ===")
    print(engine.command_registry.execute(engine, "/agents").message)
    print()
    print("=== /review workflow expansion ===")
    result = engine.command_registry.execute(engine, "/review")
    print(result.message)
    print(result.query)
    print()
    print("=== Optional real prompt ===")
    print(
        'You can manually debug a real run with:\n'
        'engine.run_prompt("Inspect the current repository, summarize its structure, and tell me where to start if I want to improve the CLI product layer.")'
    )


if __name__ == "__main__":
    main()

