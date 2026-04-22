"""Manual example for pending confirmations and AskUserQuestion.

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
}


def main() -> None:
    workspace = easyagent_root
    engine = S4QueryEngine(
        cwd=workspace,
        session_overrides=REAL_LLM_PROFILE,
    )
    register_builtin_commands(engine.command_registry)

    print("=== Pending Interactions Example ===")
    print(f"Workspace: {workspace}")
    print()
    print("=== Pending interaction inspection ===")
    print(engine.command_registry.execute(engine, "/pending").message)
    print()
    print("=== Available control commands ===")
    print("/confirm [note]")
    print("/deny [reason]")
    print("/answer <text>")
    print()
    print("=== Manual real-flow example ===")
    print(
        "1. Run a prompt that is likely to trigger a confirmation-required tool.\n"
        "2. If transcript shows Pending Confirmation, type /confirm.\n"
        "3. If transcript shows Ask User Question, type /answer <text>.\n"
        "4. S4Code will resume from the pending step instead of sending a brand-new user query."
    )
    print()
    print("=== Optional real prompt ===")
    print(
        'Try manually in TUI:\n'
        '"Review the current repository, then propose and apply a non-trivial file edit that requires confirmation if needed, and continue after I approve it."'
    )


if __name__ == "__main__":
    main()
