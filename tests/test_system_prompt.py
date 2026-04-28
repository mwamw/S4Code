from pathlib import Path

from s4code.paths import S4Paths
from s4code.project import ProjectContext
from s4code.system_prompt import S4PromptComposer, build_s4_system_prompt, discover_s4_prompt_sources


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
    assert "你在工具调用之外输出的所有文本都会直接展示给用户" in prompt
    assert "一般不要对没读过的代码提出修改方案。先读相关代码，再理解，再修改。" in prompt
    assert "如果用户要求 review，先给出 findings" in prompt
    assert "除非某个 URL 明显来自用户输入、仓库内容、工具结果" in prompt
    assert f"- 项目根目录: `{project_root}`" in prompt
    assert "- 当前分支: `main`" in prompt


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


def test_build_s4_system_prompt_appends_markdown_instructions(tmp_path) -> None:
    project_root = tmp_path / "repo"
    (project_root / ".s4code").mkdir(parents=True)
    paths = _paths(tmp_path)
    (project_root / "S4.md").write_text("# Project\nPrefer focused diffs.\n", encoding="utf-8")
    (project_root / ".s4code" / "S4.md").write_text("# Local\nKeep generated files untouched.\n", encoding="utf-8")

    prompt = build_s4_system_prompt(paths=paths, project=_project(project_root))

    assert "# S4.md 持久指令" in prompt
    assert "## 已加载的 `S4.md` 指令" in prompt
    assert "Prefer focused diffs." in prompt
    assert "Keep generated files untouched." in prompt


class _FakeSkillManager:
    def build_skill_policy_prompt(self) -> str:
        return ""

    def build_skill_listing_prompt(self) -> str:
        return ""


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

    def _build_skills_prompt(self, exclude_names=None) -> str:
        return ""


def test_s4_prompt_composer_uses_system_prompt_as_identity_block() -> None:
    composer = S4PromptComposer()
    blocks = composer.get_enhanced_prompt(_FakeAgent("custom s4 prompt"))

    print(blocks)

if __name__ == "__main__":
    test_s4_prompt_composer_uses_system_prompt_as_identity_block()