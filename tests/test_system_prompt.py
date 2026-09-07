from pathlib import Path
from dataclasses import replace
import re
from types import SimpleNamespace
import pytest



from easyagent.config import Config
from core.request_compiler import compile_prompt_blocks
from core.request_input import ReplayRequestInput
from easyagent.runtime import ExecutionContext
from s4code.core.paths import S4Paths
from s4code.core.project import ProjectContext
from s4code.core.prompting import (
    S4PromptComposer,
    build_s4_system_prompt,
    discover_s4_prompt_sources,
)
from easyagent.prompting import PromptBuildContext


def _paths(tmp_path: Path) -> S4Paths:
    return S4Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        global_config_path=tmp_path / "config" / "config.yaml",
        session_db_path=tmp_path / "data" / "sessions.db",
        task_db_path=tmp_path / "data" / "tasks.db",
        agent_storage_dir=tmp_path / "data" / "agents",
        logs_dir=tmp_path / "data" / "logs",
    ).ensure()


def _project(root: Path) -> ProjectContext:
    return ProjectContext(
        cwd=root / "src",
        project_root=root,
        git_root=root,
        git_available=True,
        is_git_repo=True,
        branch="main",
    )


def _context(*, root: Path, system_prompt: str, skill_listing: str = "") -> PromptBuildContext:
    return PromptBuildContext(
        agent_name="S4Code",
        description="test",
        system_prompt=system_prompt,
        query="hello",
        config=Config(workspace_root=str(root), allowed_roots=[str(root)]),
        execution_context=ExecutionContext(workspace_root=str(root), allowed_roots=(str(root),)),
        tool_registry=None,
        skill_manager=(
            SimpleNamespace(build_skill_listing_prompt=lambda: skill_listing)
            if skill_listing
            else None
        ),
    )


def test_build_s4_system_prompt_contains_code_agent_rules(tmp_path) -> None:
    project_root = tmp_path / "repo"
    (project_root / "src").mkdir(parents=True)
    prompt = build_s4_system_prompt(paths=_paths(tmp_path), project=_project(project_root))

    assert prompt.startswith("You are S4Code, an interactive agent")
    for section in ("System", "Doing tasks", "Executing actions with care", "Using your tools", "Tone and style", "Output efficiency"):
        assert f"# {section}" in prompt
    assert "You can call multiple tools in a single response." in prompt
    assert "You must NEVER generate or guess URLs" in prompt
    assert "<system-reminder>" in prompt
    assert "FileRead instead of cat" in prompt
    assert "Respond in Chinese by default" in prompt
    assert not re.search(r"[\u4e00-\u9fff]", prompt)


def test_discover_s4_prompt_sources_loads_global_and_project_files(tmp_path) -> None:
    project_root = tmp_path / "repo"
    (project_root / ".s4code").mkdir(parents=True)
    paths = _paths(tmp_path)
    global_prompt = paths.config_dir / "S4.md"
    root_prompt = project_root / "S4.md"
    local_prompt = project_root / ".s4code" / "S4.md"
    global_prompt.write_text("# Global\nUse terse answers.\n", encoding="utf-8")
    root_prompt.write_text("# Project\nPrefer pytest.\n", encoding="utf-8")
    local_prompt.write_text("# Local\nDo not edit generated files.\n", encoding="utf-8")

    sources = discover_s4_prompt_sources(paths, _project(project_root))

    assert [source.path for source in sources] == [
        global_prompt.resolve(),
        root_prompt.resolve(),
        local_prompt.resolve(),
    ]


def test_s4_prompt_composer_uses_context_identity(tmp_path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    composer = S4PromptComposer(paths=_paths(tmp_path), project=_project(root))

    prompt = composer.get_enhanced_prompt(_context(root=root, system_prompt="custom s4 prompt"))

    assert prompt == "custom s4 prompt"


@pytest.mark.parametrize("provider", ["anthropic_native", "openai", "openai_responses"])
def test_s4_request_context_uses_system_reminder_messages(tmp_path, provider) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "S4.md").write_text("Prefer focused diffs.\n", encoding="utf-8")
    composer = S4PromptComposer(paths=_paths(tmp_path), project=_project(root))
    blocks = composer.compose(
        _context(
            root=root,
            system_prompt="custom s4 prompt",
            skill_listing="<available_skills>\n- `review`\n</available_skills>",
        )
    )
    compiled = compile_prompt_blocks(blocks)
    request = ReplayRequestInput(
        provider_name=provider,
        replay_history=[{"role": "user", "content": "hello"}],
        persistent_replay_history=[{"role": "user", "content": "hello"}],
        system_prompt=compiled.system_prompt,
        system_prompt_blocks=compiled.system_prompt_blocks,
        system_reminder_blocks=compiled.system_reminder_blocks,
        dynamic_tail_blocks=compiled.dynamic_tail_blocks,
        on_demand_expansion_blocks=compiled.on_demand_expansion_blocks,
        cache_policy=compiled.cache_policy,
    )

    request.apply_runtime_layers()

    assert {block.name for block in compiled.system_reminder_blocks} >= {
        "skill_listing",
        "s4_md",
        "s4_environment",
        "current_date",
    }
    assert request.replay_history[0]["role"] == "user"
    assert "<system-reminder" in str(request.replay_history[0]["content"])
    assert compiled.system_prompt == "custom s4 prompt"
    assert {block.name for block in blocks}.isdisjoint({
        "visibility", "task_execution", "safety", "tool_policy", "tone_style", "output_efficiency",
    })


def test_legacy_snapshot_cannot_reenable_framework_defaults(tmp_path):
    composer = S4PromptComposer()
    composer.restore_state({"includeDefaults": True, "blocks": []})
    assert composer.include_defaults is False
    context = _context(root=tmp_path, system_prompt="product prompt")
    assert composer.get_enhanced_prompt(context) == "product prompt"


def test_product_capability_reminders_survive_full_prompt_override(tmp_path):
    from easyagent.memory import LayeredMemory
    composer = S4PromptComposer()
    context = replace(
        _context(root=tmp_path, system_prompt="product prompt", skill_listing="技能正文保持原样"),
        memory=LayeredMemory(),
        plan=SimpleNamespace(mode="plan"),
        context_manager=object(),
    )
    blocks = {block.name: block for block in composer.compose(context)}
    assert blocks["identity"].content == "product prompt"
    assert blocks["skill_listing"].content == "技能正文保持原样"
    for name in ("memory.layered.rules", "plan_mode", "compaction", "current_date"):
        assert blocks[name].placement == "system_reminder"
        assert not re.search(r"[\u4e00-\u9fff]", blocks[name].content)
    assert "`working`" in blocks["memory.layered.rules"].content
    assert "unlimited context" not in blocks["compaction"].content
    inactive = replace(context, plan=SimpleNamespace(mode="execute"), context_manager=None)
    inactive_names = {block.name for block in composer.compose(inactive)}
    assert "plan_mode" not in inactive_names
    assert "compaction" not in inactive_names


def test_project_instructions_preserve_user_language(tmp_path):
    (tmp_path / "S4.md").write_text("请保留项目已有约定。", encoding="utf-8")
    composer = S4PromptComposer(paths=_paths(tmp_path), project=_project(tmp_path))
    blocks = {block.name: block for block in composer.compose(_context(root=tmp_path, system_prompt=""))}
    assert "请保留项目已有约定。" in blocks["s4_md"].content
    assert "persistent instructions" in blocks["s4_md"].content
