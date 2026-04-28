"""Runtime bootstrap for local EasyAgent development checkouts.

S4Code is often developed next to an EasyAgent checkout. In that setup the
environment may also have a third-party `mcp` package installed, which can win
module resolution before EasyAgent's bundled `mcp` package and break imports.

This helper opportunistically prepends a sibling EasyAgent repo root when the
active `mcp` module does not expose EasyAgent's expected symbols.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


_BOOTSTRAPPED = False


def _active_mcp_is_compatible() -> bool:
    try:
        module = importlib.import_module("Emcp")
    except Exception:
        return False
    return hasattr(module, "MCPClient") and hasattr(module, "MCPHub")


def _clear_incompatible_mcp_module() -> None:
    module = sys.modules.get("Emcp")
    if module is None:
        return
    if hasattr(module, "MCPClient") and hasattr(module, "MCPHub"):
        return
    sys.modules.pop("Emcp", None)


def _is_easyagent_root(path: Path) -> bool:
    return (
        (path / "easyagent" / "__init__.py").exists()
        and (path / "Tool" / "__init__.py").exists()
        and (path / "Emcp" / "__init__.py").exists()
    )


def _candidate_roots() -> list[Path]:
    candidates: list[Path] = []
    env_root = os.getenv("S4CODE_EASYAGENT_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())

    here = Path(__file__).resolve()
    for parent in here.parents:
        sibling = parent / "EasyAgent"
        if sibling not in candidates:
            candidates.append(sibling)
    return candidates


def ensure_easyagent_environment() -> Path | None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return None

    if _active_mcp_is_compatible():
        _BOOTSTRAPPED = True
        return None

    _clear_incompatible_mcp_module()
    for candidate in _candidate_roots():
        resolved = candidate.resolve()
        if not _is_easyagent_root(resolved):
            continue
        raw = str(resolved)
        if raw not in sys.path:
            sys.path.insert(0, raw)
        _clear_incompatible_mcp_module()
        if _active_mcp_is_compatible():
            _BOOTSTRAPPED = True
            return resolved

    _BOOTSTRAPPED = True
    return None
