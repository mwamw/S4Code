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

    assert "You are S4Code, a local code agent for real software engineering work." in prompt
    assert "All text you produce outside tool use is shown directly to the user." in prompt
    assert "Read relevant code before proposing or making changes." in prompt
    assert "If the user asks for review, produce findings first" in prompt
    assert "Do not guess or invent URLs unless they are clearly provided" in prompt
    assert f"Project root: `{project_root}`" in prompt
    assert "Active branch: `main`" in prompt


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

    assert "## Durable Markdown Instructions" in prompt
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
    blocks = composer.get_system_prompt_blocks(_FakeAgent("custom s4 prompt"))

    assert blocks[0].name == "s4_identity"
    assert blocks[0].content == "custom s4 prompt"
    assert all(block.name != "custom_instructions" for block in blocks)
