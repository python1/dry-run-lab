"""The default starter uses Java and does not call Docker."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _start_engine() -> str:
    text = (ROOT / "ensure-running").read_text(encoding="utf-8")
    match = re.search(r"\nstart_engine\(\) \{.*?\n\}\n", text, re.S)
    assert match is not None
    return match.group(0)


def test_default_failure_never_invokes_docker(tmp_path: Path) -> None:
    text = (ROOT / "ensure-running").read_text(encoding="utf-8")
    tail = text.split("\ninstall_packages\n", 1)[1]
    assert "start_docker" not in tail
    assert "start_engine" in tail
    assert re.search(r"^ENGINE=java$", text, re.M)
    called = tmp_path / "called"
    script = f"""
set -u
ENGINE=java
LOG={tmp_path}/ensure.log
DATA={tmp_path}
start_java() {{ echo java >> {called}; return 1; }}
start_docker() {{ echo docker >> {called}; return 0; }}
say() {{ printf '%s\\n' "$*"; }}
{_start_engine()}
start_engine
"""
    completed = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert completed.returncode == 1
    assert called.read_text(encoding="utf-8").split() == ["java"]
    assert "Docker was not started" in completed.stdout
    assert f"{tmp_path}/ensure.log" in completed.stdout
    assert "batfish.log" in completed.stdout
    assert "docker" not in called.read_text(encoding="utf-8")


def test_java_success_never_invokes_docker(tmp_path: Path) -> None:
    called = tmp_path / "called"
    script = f"""
set -u
ENGINE=java
LOG={tmp_path}/ensure.log
DATA={tmp_path}
start_java() {{ echo java >> {called}; return 0; }}
start_docker() {{ echo docker >> {called}; return 0; }}
say() {{ printf '%s\\n' "$*"; }}
{_start_engine()}
start_engine
"""
    completed = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert called.read_text(encoding="utf-8").split() == ["java"]


def test_help_describes_docker_as_opt_in_and_untested() -> None:
    completed = subprocess.run(
        ["bash", str(ROOT / "ensure-running"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "--engine docker" in completed.stdout
    assert "Untested" in completed.stdout
    assert "does not install or start Docker" in completed.stdout
    assert "installs docker.io" not in completed.stdout
    unknown = subprocess.run(
        ["bash", str(ROOT / "ensure-running"), "--engine", "podman"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert unknown.returncode == 2
    assert "Unknown engine" in unknown.stderr
