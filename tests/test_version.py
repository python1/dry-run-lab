import re
import subprocess
from pathlib import Path

import pytest

from dryrun_lab import version as version_mod
from dryrun_lab.version import version

ROOT = Path(__file__).resolve().parents[1]


def test_checkout_stamp_matches_git() -> None:
    sha = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "--short=7", "HEAD"],
        text=True,
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        text=True,
    ).strip()
    expected = f"{sha}-dirty" if dirty else sha
    assert version() == expected
    assert re.fullmatch(r"[0-9a-f]{7,40}(-dirty)?", version())


def test_embedded_stamp_is_used_when_packaging_wrote_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version_mod, "_EMBEDDED", "abc1234")
    assert version() == "abc1234"


def test_embedded_dirty_stamp_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version_mod, "_EMBEDDED", "abc1234-dirty")
    assert version() == "abc1234-dirty"


def test_placeholder_falls_back_to_git_and_can_be_dirty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(version_mod, "_EMBEDDED", "$Format:%h$")

    def fake_git(root: Path, *args: str) -> str | None:
        if args[0] == "rev-parse":
            return "def5678"
        if args[0] == "status":
            return " M src/dryrun_lab/version.py"
        return None

    monkeypatch.setattr(version_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(version_mod, "_git", fake_git)
    assert version() == "def5678-dirty"


def test_clean_git_stamp_has_no_dirty_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(version_mod, "_EMBEDDED", "$Format:%h$")

    def fake_git(root: Path, *args: str) -> str | None:
        if args[0] == "rev-parse":
            return "def5678"
        if args[0] == "status":
            return ""
        return None

    monkeypatch.setattr(version_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(version_mod, "_git", fake_git)
    assert version() == "def5678"


def test_unknown_when_there_is_no_stamp_and_no_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version_mod, "_EMBEDDED", "$Format:%h$")
    monkeypatch.setattr(version_mod, "_repo_root", lambda: None)
    assert version() == "unknown"


def test_health_reports_the_same_stamp() -> None:
    from dryrun_lab.constants import CREDIT
    from dryrun_lab.server import health

    body = health()
    assert body["credit"] == CREDIT == "Created by Paul Charydczak"
    assert body["version"] == version()
