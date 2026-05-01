# S4Code TS

This is the TypeScript frontend for S4Code.

- Runtime: `bun`
- UI: `React + Ink`
- Backend bridge: `python -m s4code.bridge`
- Python lookup: `S4CODE_PYTHON`, then project `.venv/bin/python`, then project `venv/bin/python`, then `python`

## Start

```bash
bun install
bun run dev
```

One-shot mode is useful for non-interactive shells:

```bash
bun run src/main.tsx --cwd /path/to/project --prompt "/status"
```

When `--prompt` is used without `--resume`, S4Code creates a transient session for that one-shot command so `/session list` is not polluted by smoke tests and scripts.

## Checks

```bash
bun run typecheck
bun test
bun run smoke
```

Optional environment overrides:

- `S4CODE_PYTHON`: python executable used for the bridge
- `S4CODE_BUN`: bun executable used by the `s4code-ts` wrapper
- Python lookup order is `S4CODE_PYTHON`, project `.venv/bin/python`, project `venv/bin/python`, then `python`.

## Global Command

The repo includes [`ts/bin/s4code-ts`](/home/wxd/LLM/S4Code/ts/bin/s4code-ts), a wrapper that:

- runs the TS frontend from any directory
- defaults `--cwd` to your current shell directory
- respects an explicit `--cwd` or `-C`
