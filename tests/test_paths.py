"""Install location: DRYRUN_HOME overrides the path ensure-running recorded."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_data_home_prefers_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dryrun_lab.paths import data_home

    override = tmp_path / "override"
    monkeypatch.setenv("DRYRUN_HOME", str(override))
    assert data_home() == override.resolve()


def test_data_home_reads_the_checkout_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dryrun_lab.paths import data_home

    monkeypatch.delenv("DRYRUN_HOME", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    recorded = tmp_path / "recorded"
    (root / ".dryrun-home").write_text(str(recorded) + "\n", encoding="utf-8")
    monkeypatch.setattr("dryrun_lab.paths.repo_root", lambda: root)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert data_home() == recorded.resolve()


def test_data_home_reads_the_user_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dryrun_lab.paths import data_home

    monkeypatch.delenv("DRYRUN_HOME", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr("dryrun_lab.paths.repo_root", lambda: root)
    recorded = tmp_path / "user-install"
    xdg = tmp_path / "xdg"
    (xdg / "dryrun-lab").mkdir(parents=True)
    (xdg / "dryrun-lab" / "install-path").write_text(str(recorded) + "\r\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    assert data_home() == recorded.resolve()


def test_data_home_defaults_under_the_home_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dryrun_lab import paths

    monkeypatch.delenv("DRYRUN_HOME", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(paths, "repo_root", lambda: root)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-xdg"))
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path / "home")
    assert paths.data_home() == tmp_path / "home" / ".local" / "share" / "dryrun-lab"


def test_wrapper_uses_the_recorded_install_without_the_environment(tmp_path: Path) -> None:
    root, data = _fake_install(tmp_path, "recorded")
    (root / ".dryrun-home").write_text(str(data) + "\n", encoding="utf-8")
    completed = _run_wrapper(root, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert f"HOME={data}" in completed.stdout
    assert f"REPO={root}" in completed.stdout


def test_wrapper_environment_overrides_the_record(tmp_path: Path) -> None:
    root, recorded = _fake_install(tmp_path, "recorded")
    (root / ".dryrun-home").write_text(str(recorded) + "\n", encoding="utf-8")
    other = tmp_path / "other"
    _venv(other)
    env = _clean_env(tmp_path)
    env["DRYRUN_HOME"] = str(other)
    completed = subprocess.run(
        [str(root / "bin" / "dryrun-lab")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert f"HOME={other}" in completed.stdout


def test_wrapper_exits_nonzero_when_nothing_is_installed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "bin").mkdir(parents=True)
    shutil.copy(ROOT / "bin" / "dryrun-lab", root / "bin" / "dryrun-lab")
    shutil.copy(ROOT / "bin" / "dryrun-home.sh", root / "bin" / "dryrun-home.sh")
    completed = _run_wrapper(root, tmp_path)
    assert completed.returncode == 1
    assert "not installed" in completed.stderr


def test_ensure_running_records_the_resolved_home() -> None:
    starter = (ROOT / "ensure-running").read_text(encoding="utf-8")
    assert "source \"$ROOT/bin/dryrun-home.sh\"" in starter
    assert 'export DRYRUN_HOME="$(dryrun_resolve_home "$ROOT")"' in starter
    assert 'dryrun_record_home "$ROOT" "$DATA"' in starter
    assert starter.index("dryrun_record_home") < starter.index('log "dryrun-lab ${stamp}"')


def _fake_install(tmp_path: Path, name: str) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    (root / "bin").mkdir(parents=True)
    shutil.copy(ROOT / "bin" / "dryrun-lab", root / "bin" / "dryrun-lab")
    shutil.copy(ROOT / "bin" / "dryrun-home.sh", root / "bin" / "dryrun-home.sh")
    data = tmp_path / name
    _venv(data)
    return root, data


def _venv(data: Path) -> None:
    entry = data / "venv" / "bin" / "dryrun-lab"
    entry.parent.mkdir(parents=True)
    entry.write_text(
        "#!/bin/sh\nprintf 'HOME=%s\\nREPO=%s\\n' \"$DRYRUN_HOME\" \"$DRYRUN_REPO\"\n",
        encoding="utf-8",
    )
    entry.chmod(0o755)


def _clean_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("DRYRUN_HOME", None)
    env.pop("XDG_CONFIG_HOME", None)
    env["HOME"] = str(tmp_path / "home")
    return env


def _run_wrapper(root: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(root / "bin" / "dryrun-lab")],
        env=_clean_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
