"""Real Bridge/Ink/SDK processes with isolated configuration and no model network."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from test_core_agent import core_agent  # noqa: F401


@pytest.fixture
def client_env(core_agent, tmp_path):
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        env[key] = str(tmp_path / key)
    config = Path(env["XDG_CONFIG_HOME"]) / "s4code" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(core_agent.settings.model_dump()), encoding="utf-8")
    env["S4CODE_PYTHON"] = sys.executable
    env["S4CODE_TEST_WORKSPACE"] = str(core_agent.project.project_root)
    return env


@pytest.mark.parametrize("js_runtime", ["bun", "node"])
def test_ts_sdk_to_real_python_core(client_env, tmp_path, js_runtime):
    executable = shutil.which(js_runtime)
    if not executable:
        pytest.skip(f"{js_runtime} is required for TypeScript integration")
    package = Path(__file__).resolve().parents[1] / "ts/packages/sdk"
    sdk = package / ("src/index.ts" if js_runtime == "bun" else "dist/index.js")
    if not sdk.exists():
        pytest.skip("Run bun run build:sdk before the Node package integration test")
    script = f"""
import {{ S4Code }} from {json.dumps(str(sdk))};
const client = new S4Code({{cwd: process.env.S4CODE_TEST_WORKSPACE, python: process.env.S4CODE_PYTHON}});
try {{
  const session = await client.createSession();
  await session.save('cross-language');
  const fork = await session.fork('branch');
  const list = await client.listSessions();
  console.log(JSON.stringify({{ id: session.id, branch: fork.id, list }}));
}} finally {{ await client.close(); }}
"""
    result = subprocess.run(
        [
            executable,
            *(["--input-type=module"] if js_runtime == "node" else []),
            "-e",
            script,
        ],
        cwd=tmp_path,
        env=client_env,
        text=True,
        capture_output=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["id"] != output["branch"]
    # Restore the exact TS-created session from a separate Python SDK process.
    python = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,os; from s4code.sdk import S4Code; "
            "client=S4Code(cwd=os.environ['S4CODE_TEST_WORKSPACE']); "
            f"session=client.sessions.resume({output['id']!r}); "
            "print(json.dumps(session.info().model_dump())); client.close()",
        ],
        cwd=tmp_path,
        env=client_env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert python.returncode == 0, python.stderr
    assert json.loads(python.stdout)["title"] == "cross-language"


@pytest.mark.parametrize(
    "command",
    [
        "/status",
        "/context",
        "/help",
        "/tasks",
        "/session list",
        "/mcp",
        "/config",
        "/checkpoint safe",
    ],
)
def test_ink_headless_commands_use_real_bridge(client_env, tmp_path, command):
    bun = shutil.which("bun")
    if not bun:
        pytest.skip("Bun is required for Ink integration")
    main = Path(__file__).resolve().parents[1] / "ts/src/main.tsx"
    result = subprocess.run(
        [
            bun,
            str(main),
            "--cwd",
            client_env["S4CODE_TEST_WORKSPACE"],
            "--prompt",
            command,
        ],
        cwd=tmp_path,
        env=client_env,
        text=True,
        capture_output=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Traceback" not in result.stdout
