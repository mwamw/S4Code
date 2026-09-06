"""Real process entrypoints using isolated local settings, with no live model calls."""

import json
import os
import subprocess
import sys

from test_core_agent import core_agent


def test_installed_cli_and_bridge_from_another_directory(core_agent, tmp_path):
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    for key, directory in [
        ("XDG_CONFIG_HOME", "config-home"),
        ("XDG_DATA_HOME", "data-home"),
        ("XDG_CACHE_HOME", "cache-home"),
    ]:
        env[key] = str(tmp_path / directory)
    config = tmp_path / "config-home" / "s4code" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(core_agent.settings.model_dump()), encoding="utf-8")
    workspace = str(core_agent.project.project_root)
    cli = subprocess.run(
        [sys.executable, "-m", "s4code", "doctor", "--cwd", workspace],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)["model"] == "test-model"
    request = {"request_id": "smoke", "method": "core.state", "params": {}}
    bridge = subprocess.run(
        [
            sys.executable,
            "-m",
            "s4code.interfaces.bridge.server",
            "--cwd",
            workspace,
            "--transient-session",
            "--request-json",
            json.dumps(request),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert bridge.returncode == 0, bridge.stderr
    envelope = json.loads(bridge.stdout)
    assert envelope["ok"]
    assert envelope["request_id"] == "smoke"
    assert envelope["result"]["model"] == "test-model"


def test_cli_pending_interaction_is_saved_and_returns_exit_two(core_agent, monkeypatch):
    from typer.testing import CliRunner
    from easyagent.errors import ToolInterruption
    from s4code.interfaces.cli import app as cli

    interruption = ToolInterruption(
        "approval needed",
        tool_name="Bash",
        tool_id="pending-cli",
        tool_args={"command": "example"},
    )

    def invoke(*args, **kwargs):
        core_agent.interrupt_controller.restore_state(
            {"last_tool_interrupt": interruption.to_payload()}
        )
        raise interruption

    monkeypatch.setattr(core_agent, "invoke", invoke)
    from s4code.core.sessions.session import CoreSession
    monkeypatch.setattr(cli.S4CodeRuntime, "open_session", lambda *a, **kw: CoreSession(core_agent))
    result = CliRunner().invoke(cli.app, ["--prompt", "request needing approval"])
    assert result.exit_code == 2, result.output
    output = json.loads(result.stdout)
    assert output["status"] == "interaction_required"
    saved = core_agent.session.store.get_session(output["session_id"], touch=False)
    assert (
        saved["snapshot"]["modules"]["interruptions"]["state"]["last_tool_interrupt"][
            "tool_id"
        ]
        == "pending-cli"
    )
