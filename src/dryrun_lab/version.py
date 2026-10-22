"""Which commit this tree was built from.

A packaged tarball has no .git. `git archive` writes the short commit into
`_EMBEDDED` below. A checkout leaves that placeholder in place and the stamp
comes from `git rev-parse`, with `-dirty` when the work tree has changes.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# git archive (export-subst) replaces this. A normal checkout does not.
_EMBEDDED = "$Format:%h$"
_STAMP = re.compile(r"^[0-9a-f]{7,40}(-dirty)?$")


def version() -> str:
    """Short commit, plus `-dirty` when a git work tree has changes."""
    stamped = _embedded_stamp()
    if stamped:
        return stamped
    return _git_version()


def _embedded_stamp() -> str | None:
    text = _EMBEDDED.strip()
    if not text or "$Format" in text:
        return None
    if _STAMP.fullmatch(text):
        return text
    return None


def _git_version() -> str:
    root = _repo_root()
    if root is None:
        return "unknown"
    sha = _git(root, "rev-parse", "--short=7", "HEAD")
    if not sha or not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        return "unknown"
    if _git_dirty(root):
        return f"{sha}-dirty"
    return sha


def _repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        git = parent / ".git"
        if git.exists():
            return parent
    return None


def _git_dirty(root: Path) -> bool:
    status = _git(root, "status", "--porcelain")
    return bool(status and status.strip())


def _git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = completed.stdout.strip()
    return text or None
