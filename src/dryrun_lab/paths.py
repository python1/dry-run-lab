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
    env = os.environ.get("DRYRUN_HOME")
    if env:
        return Path(env).resolve()
    return Path.home() / ".local" / "share" / "dryrun-lab"


def static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"
