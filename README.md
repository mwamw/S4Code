# S4Code

S4Code is a local-first code agent CLI built on top of EasyAgent.

Current scope:
- full-screen TUI for interactive use
- non-interactive CLI for single prompts and common workflows
- slash commands for session, model, permissions, review, commit, tasks, agents, MCP, and hooks
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
