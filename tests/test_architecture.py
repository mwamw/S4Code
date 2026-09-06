"""Enforce the boundaries that motivated the refactor."""

import ast
import os
from pathlib import Path
import subprocess
import sys

PACKAGE = Path(__file__).resolve().parents[1] / "s4code"


def test_core_has_no_interaction_or_framework_internal_imports():
    forbidden = {
        "textual",
        "rich",
        "typer",
        "Tool",
        "core",
        "agent",
        "runtime",
        "context",
        "db",
        "task",
        "Emcp",
    }
    for path in (PACKAGE / "core").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                module = node.module or ""
                assert module.split(".")[0] not in forbidden, (path, module)
                assert not module.startswith("s4code.interfaces"), (path, module)
            elif isinstance(node, ast.Import):
                for name in node.names:
                    assert name.name.split(".")[0] not in forbidden, (path, name.name)


def test_removed_assembly_layers_are_not_reintroduced():
    for name in ("easyagent_adapter.py", "query_engine.py", "_easyagent_bootstrap.py"):
        assert not (PACKAGE / name).exists()


def test_sdk_imports_without_loading_terminal_from_another_directory(tmp_path):
    # Keep the configured environment's user-site dependencies, but do not
    # let a repository PYTHONPATH hide a broken editable installation.
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, s4code; from s4code.sdk import S4Code, AsyncS4Code; "
            "assert not hasattr(s4code, 'S4CodeAgent'); "
            'assert not any(k.startswith("s4code.interfaces") for k in sys.modules); '
            'assert "textual" not in sys.modules; '
            "print(S4Code.__module__)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "s4code.sdk.client"


def test_entrypoints_and_sdk_are_peers():
    import importlib.util

    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE)
        package = "s4code." + ".".join(relative.parts[:-1])
        for node in ast.walk(ast.parse(path.read_text())):
            imports = []
            if isinstance(node, ast.ImportFrom):
                imports = [
                    importlib.util.resolve_name(
                        "." * node.level + (node.module or ""), package
                    )
                    if node.level
                    else node.module or ""
                ]
            elif isinstance(node, ast.Import):
                imports = [item.name for item in node.names]
            for module in imports:
                if relative.parts[0] == "core":
                    assert not module.startswith(("s4code.interfaces", "s4code.sdk")), (
                        path,
                        module,
                    )
                if relative.parts[:2] == ("interfaces", "bridge"):
                    assert not module.startswith(
                        (
                            "s4code.interfaces.terminal",
                            "s4code.interfaces.textual",
                            "s4code.sdk",
                            "easyagent",
                        )
                    ), (path, module)
                if relative.parts[0] == "interfaces":
                    assert not module.startswith(
                        ("s4code.sdk", "easyagent", "s4code.core.agent")
                    ), (path, module)
                if relative.parts[0] == "sdk":
                    assert not module.startswith(("s4code.interfaces", "easyagent")), (
                        path,
                        module,
                    )


def test_interfaces_do_not_reach_into_core_internals():
    forbidden_attributes = {
        "_agent",
        "tool_registry",
        "hook_manager",
        "event_bus",
        "permission_context",
        "context_manager",
        "task_service",
        "agent_runtime",
        "skill_manager",
    }
    for path in (PACKAGE / "interfaces").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_attributes, (path, node.attr)


def test_typescript_sdk_and_transport_are_ui_free():
    ts = PACKAGE.parent / "ts"
    for path in (ts / "packages").rglob("src/*.ts"):
        source = path.read_text()
        for forbidden in (
            "src/controller",
            "src/commands",
            "from 'ink'",
            "from 'react'",
            "execute_command",
            "command_palette",
        ):
            assert forbidden not in source, (path, forbidden)
    for path in (ts / "src").rglob("*.ts*"):
        assert "packages/sdk" not in path.read_text(), path
