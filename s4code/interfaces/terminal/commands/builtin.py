"""Default terminal command catalog."""

from .types import CommandKind, S4Command
from .workspace import (
    HelpCommand,
    StatusCommand,
    CostCommand,
    TraceCommand,
    ToolsCommand,
    ContextCommand,
    FilesCommand,
    DiffCommand,
    ReviewCommand,
    CommitCommand,
    HooksCommand,
    SidebarCommand,
    CopyCommand,
    ExitCommand,
)
from .settings import (
    ModelCommand,
    ThemeCommand,
    ConfigCommand,
    DoctorCommand,
    PermissionsCommand,
    PlanCommand,
)
from .session import (
    ResumeCommand,
    SessionCommand,
    ClearCommand,
    CompactCommand,
    RestoreCommand,
    CheckpointCommand,
    CheckpointsCommand,
    RewindCommand,
    TimelineCommand,
)
from .runtime import (
    PendingCommand,
    TasksCommand,
    AgentsCommand,
    RuntimeCommand,
    McpCommand,
    SkillsCommand,
    WorktreeCommand,
    AgentCommand,
    TaskCommand,
    ConfirmCommand,
    DenyCommand,
    AnswerCommand,
)


def register_builtin_commands(registry) -> None:
    registry.register(
        S4Command(
            "help",
            CommandKind.LOCAL,
            "Show available slash commands.",
            HelpCommand().execute,
            aliases=("h",),
            usage="[command]",
            category="Get Started",
            keywords=("welcome", "quickstart", "commands", "workflow"),
            priority=90,
        )
    )
    registry.register(
        S4Command(
            "status",
            CommandKind.LOCAL,
            "Show the current product/runtime status.",
            StatusCommand().execute,
            category="Workspace",
            keywords=("overview", "project", "session", "runtime"),
            priority=95,
        )
    )
    registry.register(
        S4Command(
            "model",
            CommandKind.LOCAL,
            "Show model profiles or switch to a profile/literal model.",
            ModelCommand().execute,
            usage="[profile-name|literal-model]",
            category="Settings",
            keywords=("provider", "profile", "llm"),
        )
    )
    registry.register(
        S4Command(
            "theme",
            CommandKind.LOCAL,
            "List or switch the TUI theme.",
            ThemeCommand().execute,
            aliases=("themes",),
            usage="[list|theme-name|theme-json-path]",
            category="Settings",
            keywords=("appearance", "colors", "ui"),
        )
    )
    registry.register(
        S4Command(
            "config",
            CommandKind.LOCAL,
            "Show the resolved S4Code config.",
            ConfigCommand().execute,
            category="Settings",
            keywords=("yaml", "resolved"),
        )
    )
    registry.register(
        S4Command(
            "doctor",
            CommandKind.LOCAL,
            "Show an end-to-end product diagnostics payload.",
            DoctorCommand().execute,
            category="Debug",
            keywords=("raw", "diagnostics", "json"),
        )
    )
    registry.register(
        S4Command(
            "permissions",
            CommandKind.LOCAL,
            "Show mode/rules, change mode, or add/clear permission rules.",
            PermissionsCommand().execute,
            aliases=("perm",),
            usage="[show|mode <mode>|allow|deny|ask <tool> [matchers]|clear [source]|history]",
            category="Approvals",
            keywords=("confirm", "risk", "rules", "access"),
            priority=80,
        )
    )
    registry.register(
        S4Command(
            "plan",
            CommandKind.LOCAL,
            "Enter or exit plan mode.",
            PlanCommand().execute,
            usage="[on|off]",
            category="Approvals",
            keywords=("planning", "mode"),
        )
    )
    registry.register(
        S4Command(
            "resume",
            CommandKind.LOCAL,
            "Resume a saved session or list sessions.",
            ResumeCommand().execute,
            usage="[session_id]",
            category="Sessions",
            keywords=("restore", "history"),
            priority=70,
        )
    )
    registry.register(
        S4Command(
            "session",
            CommandKind.LOCAL,
            "Show, list, load, rename, fork, or inspect session timeline/checkpoints.",
            SessionCommand().execute,
            usage="[show|list|load <session_id>|rename <title>|fork [title]|timeline|checkpoints|rewind <checkpoint>|tree]",
            category="Sessions",
            keywords=("resume", "restore", "timeline", "rewind"),
            priority=75,
        )
    )
    registry.register(
        S4Command(
            "pending",
            CommandKind.LOCAL,
            "Show the current pending confirmation/question.",
            PendingCommand().execute,
            category="Approvals",
            keywords=("confirm", "question", "waiting"),
            priority=98,
        )
    )
    registry.register(
        S4Command(
            "copy",
            CommandKind.LOCAL,
            "Copy the full transcript or the latest card to the clipboard.",
            CopyCommand().execute,
            usage="[transcript|last]",
            category="Transcript",
            keywords=("clipboard", "share"),
        )
    )
    registry.register(
        S4Command(
            "clear",
            CommandKind.LOCAL,
            "Clear conversation history.",
            ClearCommand().execute,
            category="Transcript",
            keywords=("reset", "history"),
        )
    )
    registry.register(
        S4Command(
            "compact",
            CommandKind.LOCAL,
            "Compact conversation history.",
            CompactCommand().execute,
            usage="[partial <max_tokens>|<max_tokens>]",
            category="Transcript",
            keywords=("history", "tokens"),
        )
    )
    registry.register(
        S4Command(
            "context",
            CommandKind.LOCAL,
            "Show current context window usage and compaction state.",
            ContextCommand().execute,
            category="Transcript",
            keywords=("tokens", "budget", "cache", "usage"),
            priority=92,
        )
    )
    registry.register(
        S4Command(
            "cost",
            CommandKind.LOCAL,
            "Show observability and token usage summary.",
            CostCommand().execute,
            category="Transcript",
            keywords=("tokens", "cache", "spend", "usage"),
        )
    )
    registry.register(
        S4Command(
            "trace",
            CommandKind.LOCAL,
            "Show recent turn-level trace summaries.",
            TraceCommand().execute,
            category="Transcript",
            keywords=("turns", "summary", "history"),
        )
    )
    registry.register(
        S4Command(
            "restore",
            CommandKind.LOCAL,
            "Show the latest session restore report.",
            RestoreCommand().execute,
            category="Sessions",
            keywords=("resume", "continuity", "restore"),
            priority=65,
        )
    )
    registry.register(
        S4Command(
            "checkpoint",
            CommandKind.LOCAL,
            "Create or list restorable conversation checkpoints.",
            CheckpointCommand().execute,
            usage="[label|list]",
            category="Sessions",
            keywords=("save", "restore"),
        )
    )
    registry.register(
        S4Command(
            "checkpoints",
            CommandKind.LOCAL,
            "List restorable conversation checkpoints.",
            CheckpointsCommand().execute,
            category="Sessions",
            keywords=("restore", "save"),
        )
    )
    registry.register(
        S4Command(
            "rewind",
            CommandKind.LOCAL,
            "Restore conversation history to a checkpoint.",
            RewindCommand().execute,
            usage="[checkpoint_id|index|last]",
            category="Sessions",
            keywords=("restore", "checkpoint"),
        )
    )
    registry.register(
        S4Command(
            "timeline",
            CommandKind.LOCAL,
            "Show session checkpoints and recent trace timeline.",
            TimelineCommand().execute,
            category="Sessions",
            keywords=("history", "trace"),
        )
    )
    registry.register(
        S4Command(
            "tools",
            CommandKind.LOCAL,
            "List the currently registered tool surface.",
            ToolsCommand().execute,
            category="Workspace",
            keywords=("capabilities", "deferred", "available"),
            priority=60,
        )
    )
    registry.register(
        S4Command(
            "files",
            CommandKind.LOCAL,
            "List project files.",
            FilesCommand().execute,
            usage="[path]",
            category="Workspace",
            keywords=("repo", "tree"),
        )
    )
    registry.register(
        S4Command(
            "diff",
            CommandKind.LOCAL,
            "Show git diff for the current repository.",
            DiffCommand().execute,
            usage="[target]",
            category="Workspace",
            keywords=("git", "changes"),
            priority=88,
        )
    )
    registry.register(
        S4Command(
            "review",
            CommandKind.WORKFLOW,
            "Run a code review workflow against the current diff.",
            ReviewCommand().execute,
            usage="[target]",
            category="Workflows",
            keywords=("bugs", "regressions", "review"),
            priority=87,
        )
    )
    registry.register(
        S4Command(
            "commit",
            CommandKind.WORKFLOW,
            "Draft a commit proposal from the current diff.",
            CommitCommand().execute,
            category="Workflows",
            keywords=("git", "message"),
        )
    )
    registry.register(
        S4Command(
            "tasks",
            CommandKind.LOCAL,
            "List structured and background tasks.",
            TasksCommand().execute,
            category="Runtime",
            keywords=("background", "jobs", "long-running"),
            priority=94,
        )
    )
    registry.register(
        S4Command(
            "task",
            CommandKind.LOCAL,
            "Inspect a task, read background task output, or stop a background task.",
            TaskCommand().execute,
            usage="[show <task_id>|output <task_id> [timeout_ms]|stop <task_id>]",
            category="Runtime",
            keywords=("background", "logs", "stop", "jobs"),
            priority=93,
        )
    )
    registry.register(
        S4Command(
            "agents",
            CommandKind.LOCAL,
            "List runtime agents.",
            AgentsCommand().execute,
            category="Runtime",
            keywords=("workers", "handles"),
        )
    )
    registry.register(
        S4Command(
            "agent",
            CommandKind.LOCAL,
            "Inspect, wait for, or stop a runtime agent handle.",
            AgentCommand().execute,
            usage="[list|show <agent_id>|wait <agent_id> [timeout_ms]|stop <agent_id> [reason]]",
            category="Runtime",
            keywords=("workers", "handles"),
        )
    )
    registry.register(
        S4Command(
            "runtime",
            CommandKind.LOCAL,
            "Show the live worktree, agent, and task runtime panel.",
            RuntimeCommand().execute,
            aliases=("rt",),
            category="Runtime",
            keywords=("snapshot", "agents", "tasks"),
        )
    )
    registry.register(
        S4Command(
            "mcp",
            CommandKind.LOCAL,
            "Inspect MCP server status and control MCP connections.",
            McpCommand().execute,
            usage="[list|status <server>|tools <server>|resources <server>|refresh [server]|connect [server]|disconnect [server]]",
            category="Workspace",
            keywords=("mcp", "server", "connect"),
        )
    )
    registry.register(
        S4Command(
            "skills",
            CommandKind.LOCAL,
            "List discovered skills or queue one for the next turn.",
            SkillsCommand().execute,
            usage="[list|use <name>|clear]",
            category="Workspace",
            keywords=("skills", "capabilities", "turn"),
            priority=55,
        )
    )
    registry.register(
        S4Command(
            "worktree",
            CommandKind.LOCAL,
            "Inspect or control the current worktree runtime.",
            WorktreeCommand().execute,
            usage="[show|enter [name]|exit [keep|remove] [discard]]",
            category="Workspace",
            keywords=("branch", "sandbox", "git"),
        )
    )
    registry.register(
        S4Command(
            "hooks",
            CommandKind.LOCAL,
            "List installed hooks/guardrails.",
            HooksCommand().execute,
            category="Debug",
            keywords=("guardrails", "hooks"),
        )
    )
    registry.register(
        S4Command(
            "confirm",
            CommandKind.LOCAL,
            "Approve the current pending confirmation and continue execution; use 'remember' to add a session rule.",
            ConfirmCommand().execute,
            aliases=("approve",),
            usage="[note|remember]",
            category="Approvals",
            keywords=("pending", "allow", "continue"),
            priority=100,
        )
    )
    registry.register(
        S4Command(
            "deny",
            CommandKind.LOCAL,
            "Deny the current pending confirmation/question; use 'remember' to add a session deny rule.",
            DenyCommand().execute,
            usage="[reason|remember]",
            category="Approvals",
            keywords=("pending", "block", "cancel"),
            priority=99,
        )
    )
    registry.register(
        S4Command(
            "answer",
            CommandKind.LOCAL,
            "Answer the current AskUserQuestion interaction and continue execution.",
            AnswerCommand().execute,
            usage="<text>",
            category="Approvals",
            keywords=("pending", "question", "reply"),
            priority=101,
        )
    )
    registry.register(
        S4Command(
            "sidebar",
            CommandKind.LOCAL,
            "Show or hide the right-side info panel.",
            SidebarCommand().execute,
            usage="[show|hide]",
            category="Settings",
            keywords=("panel", "ui"),
        )
    )
    registry.register(
        S4Command(
            "exit",
            CommandKind.LOCAL,
            "Exit the current S4Code session.",
            ExitCommand().execute,
            aliases=("quit", "q"),
            category="General",
            keywords=("quit", "close"),
        )
    )
