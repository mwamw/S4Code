"""Project and git discovery helpers."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
}


@dataclass(slots=True)
class ProjectContext:
    cwd: Path
    project_root: Path
    git_root: Optional[Path]
    git_available: bool
    is_git_repo: bool
    branch: Optional[str]
    git_binary: str = "git"

    @property
    def allowed_roots(self) -> tuple[str, ...]:
        return (str(self.project_root),)

    @property
    def project_name(self) -> str:
        return self.project_root.name or "workspace"

    @classmethod
    def detect(
        cls, cwd: str | Path | None = None, *, git_binary: str = "git"
    ) -> "ProjectContext":
        current = Path(cwd or os.getcwd()).expanduser().resolve()
        git_root = None
        git_available = True
        branch = None
        try:
            root_out = subprocess.run(
                [git_binary, "rev-parse", "--show-toplevel"],
                cwd=str(current),
                capture_output=True,
                text=True,
                check=True,
            )
            git_root = Path(root_out.stdout.strip()).resolve()
            branch_out = subprocess.run(
                [git_binary, "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                check=True,
            )
            branch = branch_out.stdout.strip() or None
        except FileNotFoundError:
            git_available = False
        except subprocess.CalledProcessError:
            git_root = None
            branch = None

        project_root = git_root or current
        return cls(
            cwd=current,
            project_root=project_root,
            git_root=git_root,
            git_available=git_available,
            is_git_repo=git_root is not None,
            branch=branch,
            git_binary=git_binary,
        )

    def run_git(
        self, args: list[str], *, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        if not self.git_available:
            raise RuntimeError("git 不可用。")
        if not self.is_git_repo or self.git_root is None:
            raise RuntimeError("当前目录不是 git 仓库。")
        return subprocess.run(
            [self.git_binary, *args],
            cwd=str(self.git_root),
            capture_output=True,
            text=True,
            check=check,
        )

    def get_git_status(self) -> str:
        if not self.is_git_repo:
            return "Not a git repository."
        completed = self.run_git(["status", "--short"], check=False)
        return completed.stdout.strip() or "Working tree clean."

    def get_diff(self, target: Optional[str] = None, *, max_lines: int = 400) -> str:
        if not self.is_git_repo:
            return "Not a git repository."
        args = ["diff"]
        if target:
            args.append(target)
        completed = self.run_git(args, check=False)
        lines = completed.stdout.splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines] + ["", f"... truncated to {max_lines} lines ..."]
        return "\n".join(lines).strip() or "No diff."

    def list_files(self, relative_path: str = ".", *, limit: int = 200) -> list[str]:
        base = (self.project_root / relative_path).resolve()
        if not base.exists():
            return []
        if base.is_file():
            return [str(base.relative_to(self.project_root))]
        files: list[str] = []
        for root, dirnames, filenames in os.walk(base):
            dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS]
            for filename in sorted(filenames):
                path = Path(root) / filename
                files.append(str(path.relative_to(self.project_root)))
                if len(files) >= limit:
                    return files
        return files

    def to_status_dict(self) -> dict[str, object]:
        return {
            "cwd": str(self.cwd),
            "projectRoot": str(self.project_root),
            "gitRoot": str(self.git_root) if self.git_root else None,
            "gitAvailable": self.git_available,
            "isGitRepo": self.is_git_repo,
            "branch": self.branch,
        }
