"""Locations for the repo, the example lab, and per-user state."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("DRYRUN_REPO")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "examples" / "office-lab" / "topology.json").is_file():
            return parent
    return here.parents[2]


def example_lab() -> Path:
    return repo_root() / "examples" / "office-lab"


def data_home() -> Path:
    """Directory that holds the jar, virtualenv, logs, and saved lab.

    `DRYRUN_HOME` overrides. Otherwise the path last recorded by
    `./ensure-running` is used: `.dryrun-home` in the checkout, then
    `$XDG_CONFIG_HOME/dryrun-lab/install-path` (or `~/.config/dryrun-lab/`).
    The default is `~/.local/share/dryrun-lab`.
    """
    env = os.environ.get("DRYRUN_HOME")
    if env:
        return Path(env).expanduser().resolve()
    recorded = _read_record(repo_root() / ".dryrun-home")
    if recorded is not None:
        return recorded
    config_root = os.environ.get("XDG_CONFIG_HOME")
    if config_root:
        config = Path(config_root) / "dryrun-lab" / "install-path"
    else:
        config = Path.home() / ".config" / "dryrun-lab" / "install-path"
    recorded = _read_record(config)
    if recorded is not None:
        return recorded
    return Path.home() / ".local" / "share" / "dryrun-lab"


def _read_record(path: Path) -> Path | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    return Path(lines[0]).expanduser().resolve()


def static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"
