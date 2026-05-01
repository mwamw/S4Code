from pathlib import Path
from types import SimpleNamespace

from s4code._easyagent_bootstrap import ensure_easyagent_environment

ensure_easyagent_environment()

from core.request_compiler import compile_prompt_blocks
from core.request_input import ReplayRequestInput
from s4code.paths import S4Paths
from s4code.project import ProjectContext
from s4code.system_prompt import (
    S4PromptComposer,
    build_s4_runtime_reminder_sources,
    build_s4_system_prompt,
    discover_s4_prompt_sources,
)


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


def test_build_s4_system_prompt_contains_code_agent_rules(tmp_path) -> None:
    project_root = tmp_path / "repo"
    (project_root / "src").mkdir(parents=True)
    paths = _paths(tmp_path)
    prompt = build_s4_system_prompt(paths=paths, project=_project(project_root))

    assert "你是 S4Code，一个交互式本地代码智能体" in prompt
    assert "当前运行环境可能带有权限模式、审批、hook、运行时控制和中断机制" in prompt
    assert "如果用户要求 review，先给出 findings" in prompt
    assert "除非某个 URL 明显来自用户输入、仓库内容、工具结果" in prompt
    assert "# 当前环境" not in prompt
    assert "# S4.md 持久指令" not in prompt


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
    assert [source.content for source in sources] == [
        "# Global\nUse terse answers.",
        "# Project\nPrefer pytest.",
        "# Local\nDo not edit generated files.",
    ]


def test_runtime_reminder_sources_include_s4_md_environment_skills_and_deferred_tools(tmp_path) -> None:
    project_root = tmp_path / "repo"
    (project_root / ".s4code").mkdir(parents=True)
    paths = _paths(tmp_path)
    (project_root / "S4.md").write_text("# Project\nPrefer focused diffs.\n", encoding="utf-8")
    (project_root / ".s4code" / "S4.md").write_text("# Local\nKeep generated files untouched.\n", encoding="utf-8")
    project = _project(project_root)
    sources = build_s4_runtime_reminder_sources(paths=paths, project=project)
    fake_agent = SimpleNamespace(
        tool_registry=SimpleNamespace(
            list_tool_specs=lambda stable=True: [
                SimpleNamespace(name="Bash", expose_in_deferred=True, metadata={}),
                SimpleNamespace(name="WebFetch", expose_in_deferred=False, metadata={}),
            ]
        ),
        config=SimpleNamespace(tool_schema_mode="deferred"),
        skill_manager=SimpleNamespace(
            build_resident_skills_prompt=lambda exclude_names=None: "## 动态技能管理工具\n直接调用 `skill_tool`。",
            build_skill_policy_prompt=lambda: "## Skill 使用规则\n直接用 `skill_tool`。",
            build_skill_listing_prompt=lambda: "## 可用 Skills\n- `review_skill`",
        ),
    )

    rendered = "\n\n".join(
        reminder.render()
        for source in sources
        for reminder in source.build_runtime_reminders(fake_agent)
    )

    assert "Prefer focused diffs." in rendered
    assert "Keep generated files untouched." in rendered
    assert f"- 项目根目录: `{project_root}`" in rendered
    assert "Today's date is" in rendered
    assert "WebFetch" in rendered
    assert "tool_schema_tool" in rendered
    assert "## 动态技能管理工具" in rendered
    assert "## Skill 使用规则" in rendered
    assert "## 可用 Skills" in rendered


class _FakeSkillManager:
    def build_resident_skills_prompt(self, exclude_names=None) -> str:
        return "## 动态技能管理工具\n直接调用 `skill_tool`。"

    def build_skill_policy_prompt(self) -> str:
        return "## Skill 使用规则\n直接调用 `skill_tool`。"

    def build_skill_listing_prompt(self) -> str:
        return "## 可用 Skills\n- `crypto_skill`"


class _FakeAgent:
    def __init__(self, system_prompt: str) -> None:
        self.enable_tool = True
        self.tool_registry = object()
        self.system_prompt = system_prompt
        self.skill_manager = _FakeSkillManager()

    def _should_include_tool_inventory_block(self) -> bool:
        return False

    def _build_memory_prompt(self) -> str:
        return ""

    def _build_mailbox_prompt(self) -> str:
        return ""

    def get_system_prompt_blocks(self):
        return self.prompt_composer.get_system_prompt_blocks(self)  # pragma: no cover

    def build_runtime_reminder_prompt_blocks(self, start_order: int):
        from prompt import PromptBlock

        return [
            PromptBlock(
                name="skills",
                content="## 可用 Skills\n- `crypto_skill`",
                order=start_order,
                metadata={"request_layer": "reminder"},
            )
        ]


def test_s4_prompt_composer_uses_system_prompt_as_identity_block() -> None:
    composer = S4PromptComposer()
    prompt = composer.get_enhanced_prompt(_FakeAgent("custom s4 prompt"))
    assert "custom s4 prompt" in prompt
    assert "## 可用 Skills" not in prompt


def test_s4_runtime_reminders_are_prepended_as_system_reminder_tags() -> None:
    agent = _FakeAgent("custom s4 prompt")
    composer = S4PromptComposer()
    compiled = compile_prompt_blocks(composer.get_system_prompt_blocks(agent))

    request = ReplayRequestInput(
        provider_name="anthropic_native",
        replay_history=[{"role": "user", "content": "hello"}],
        persistent_replay_history=[{"role": "user", "content": "hello"}],
        system_prompt=compiled.system_prompt,
        system_prompt_blocks=compiled.system_prompt_blocks,
        runtime_reminder_blocks=compiled.runtime_reminder_blocks,
        dynamic_tail_blocks=compiled.dynamic_tail_blocks,
        on_demand_expansion_blocks=compiled.on_demand_expansion_blocks,
        cache_policy=compiled.cache_policy,
    )
    request.apply_runtime_layers()

    assert request.runtime_reminder_blocks
    assert request.replay_history[0]["role"] == "user"
    assert "<system-reminder" in str(request.replay_history[0]["content"])
