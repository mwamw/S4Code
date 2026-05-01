# S4Code TS

This is the TypeScript frontend for S4Code.

- Runtime: `bun`
- UI: `React + Ink`
- Backend bridge: `python -m s4code.bridge`
- Python lookup: `S4CODE_PYTHON`, then project `.venv/bin/python`, then project `venv/bin/python`, then `python`

## Start

```bash
bun install
bun run src/main.tsx
```

One-shot mode is useful for non-interactive shells:

```bash
bun src/main.tsx --cwd /path/to/project --prompt "/status"
```

Optional environment overrides:

- `S4CODE_PYTHON`: python executable used for the bridge
