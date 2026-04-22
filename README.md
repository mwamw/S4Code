# S4Code

S4Code is a local-first code agent CLI built on top of EasyAgent.

Current scope:
- full-screen TUI for interactive use
- non-interactive CLI for single prompts and common workflows
- slash commands for session, model, permissions, review, commit, tasks, agents, MCP, and hooks
- YAML config with model profiles and context management
- pending confirmation / AskUserQuestion / plan-mode interaction handling
- EasyAgent-backed tools for files, shell, code intelligence, worktrees, tasks, multi-agent collaboration, and session resume

Install locally:

```bash
pip install -e /home/wxd/LLM/EasyAgent
pip install -e /home/wxd/LLM/S4Code
```

Run:

```bash
s4code
s4code -p "Summarize the current repository"
s4code review
s4code session list
```

The detailed stage implementation note is in [docs/phase1_s4code_foundation.md](docs/phase1_s4code_foundation.md).
The YAML profiles + context stage note is in [docs/phase2_yaml_profiles_context.md](docs/phase2_yaml_profiles_context.md).
The pending interaction stage note is in [docs/phase3_pending_interactions.md](docs/phase3_pending_interactions.md).
YAML configuration reference is in [docs/configuration_yaml.md](docs/configuration_yaml.md).
The palette/session/clipboard stage note is in [docs/phase4_palette_sessions_clipboard.md](docs/phase4_palette_sessions_clipboard.md).
