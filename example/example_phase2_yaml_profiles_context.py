"""Manual example for YAML profiles + context management.

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

from s4code.commands import register_builtin_commands
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
        }
    },
    "context": {
        "enabled": True,
        "max_tokens": 24000,
        "history_compactor": "llm",
        "recent_turns": 4,
    },
}


def main() -> None:
    workspace = easyagent_root
    engine = S4QueryEngine(
        cwd=workspace,
        session_overrides=REAL_LLM_PROFILE,
    )
    register_builtin_commands(engine.command_registry)

    print("=== YAML Profiles + Context Example ===")
    print(f"Workspace: {workspace}")
    print()
    print("=== /model ===")
    print(engine.command_registry.execute(engine, "/model").message)
    print()
    print("=== /context ===")
    print(engine.command_registry.execute(engine, "/context").message)
    print()
    print("=== Switch by profile ===")
    print(engine.command_registry.execute(engine, "/model local-qwen").message)
    print()
    print("=== Manual compaction note ===")
    print(
        "When a long-running conversation exceeds the context budget, "
        "S4Code will emit a Context Compaction stage in the transcript. "
        "The compactor uses the current profile's EasyLLM."
    )
    print()
    print("=== Optional real run ===")
    print(
        'Use the TUI or a real prompt manually, for example:\n'
        'engine.run_prompt("Read the current repository, keep a task list, and make enough progress to force a history compaction if the context budget is exceeded.")'
    )


if __name__ == "__main__":
    main()
