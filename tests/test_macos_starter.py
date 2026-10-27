"""macOS starter: Homebrew and a keg-only JDK, never apt or sudo."""

import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _block() -> str:
    text = (ROOT / "ensure-running").read_text(encoding="utf-8")
    start = text.index("# darwin-host:begin\n")
    end = text.index("# darwin-host:end\n")
    return text[start:end]


def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _java(path: Path, major: int) -> None:
    _exe(
        path,
        "#!/bin/sh\n" f"echo 'openjdk version \"{major}.0.2\" 2024-01-16' >&2\n",
    )


def _uname(path: Path, name: str) -> None:
    _exe(path, f"#!/bin/sh\nprintf '%s\\n' {name}\n")


def _brew(path: Path) -> None:
    _exe(
        path,
        """#!/bin/sh
if [ "$1" = "install" ]; then
  printf '%s\\n' "$2" >> "$BREW_RECORD"
  if [ "$2" = "openjdk@21" ] && [ -n "${BREW_JAVA_ON_INSTALL:-}" ]; then
    mkdir -p "$(dirname "$BREW_JAVA_ON_INSTALL")"
    cat > "$BREW_JAVA_ON_INSTALL" <<'EOF'
#!/bin/sh
echo 'openjdk version "21.0.2" 2024-01-16' >&2
EOF
    chmod +x "$BREW_JAVA_ON_INSTALL"
  fi
  if [ "$2" = "python" ] && [ -n "${BREW_PYTHON_ON_INSTALL:-}" ]; then
    mkdir -p "$(dirname "$BREW_PYTHON_ON_INSTALL")"
    cat > "$BREW_PYTHON_ON_INSTALL" <<'EOF'
#!/bin/sh
exit 0
EOF
    chmod +x "$BREW_PYTHON_ON_INSTALL"
  fi
  exit 0
fi
if [ "$1" = "--prefix" ] && [ "${2:-}" = "openjdk@21" ]; then
  printf '%s\\n' "${BREW_OPENJDK_PREFIX:-}"
  exit 0
fi
if [ "$1" = "--prefix" ]; then
  printf '%s\\n' "${BREW_ROOT:-}"
  exit 0
fi
exit 1
""",
    )


def _tool_bin(tmp_path: Path) -> Path:
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    for name in (
        "sed",
        "head",
        "dirname",
        "grep",
        "awk",
        "mktemp",
        "cat",
        "chmod",
        "mkdir",
        "tr",
        "cp",
        "rm",
        "touch",
        "uname",
        "basename",
    ):
        source = shutil.which(name)
        if source and not (tools / name).exists():
            os.symlink(source, tools / name)
    return tools


def _run_packages(tmp_path: Path, fake: Path, env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    block = tmp_path / "host.sh"
    block.write_text(_block(), encoding="utf-8")
    log = tmp_path / "ensure.log"
    record = tmp_path / "apt.txt"
    script = f"""
set -euo pipefail
say() {{ printf '%s\\n' "$*"; }}
log() {{ printf '%s\\n' "$*" >>"$LOG"; }}
apt_logged() {{ printf 'apt %s\\n' "$*" >>"$RECORD"; return 0; }}
as_root() {{ printf 'sudo %s\\n' "$*" >>"$RECORD"; "$@"; }}
unset BREW || true
source <(sed -n '/^java_major()/,/^}}/p' "{ROOT}/ensure-running")
source "{block}"
install_packages
printf 'JAVA_BIN=%s\\n' "${{JAVA_BIN-}}"
"""
    env = os.environ.copy()
    # Keep host java, brew, and python off PATH so discovery is the fixtures.
    env["PATH"] = f"{fake}:{_tool_bin(tmp_path)}"
    env["LOG"] = str(log)
    env["RECORD"] = str(record)
    env.pop("JAVA_HOME", None)
    env.pop("BREW", None)
    env.update(env_extra)
    return subprocess.run(
        ["/bin/bash", "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _darwin_bin(tmp_path: Path, *, java: Path | None = None, python_ok: bool = True) -> Path:
    fake = tmp_path / "bin"
    _uname(fake / "uname", "Darwin")
    _exe(fake / "curl", "#!/bin/sh\nexit 0\n")
    if python_ok:
        _exe(fake / "python3", "#!/bin/sh\nexit 0\n")
    else:
        _exe(fake / "python3", "#!/bin/sh\nexit 1\n")
    if java is not None:
        _java(java, 21)
    return fake


def test_darwin_package_block_never_mentions_apt() -> None:
    block = _block()
    darwin = block.split("install_packages_darwin()", 1)[1].split("\ninstall_packages()", 1)[0]
    linux = block.split("\ninstall_packages()", 1)[1]
    assert "apt-get" not in darwin
    assert "sudo" not in darwin
    assert "ca-certificates" not in darwin
    assert "openjdk@21" in darwin
    assert "/opt/homebrew" in block
    assert "/usr/local" in block
    assert "JAVA_HOME" in block
    assert "Cellar/openjdk@21" in block
    assert "apt-get" in linux
    assert "openjdk-21-jre-headless" in linux
    starter = (ROOT / "ensure-running").read_text(encoding="utf-8")
    assert "local need=()" not in starter
    assert "local wheels=(" not in starter


def test_path_java_21_does_not_call_brew_or_apt(tmp_path: Path) -> None:
    fake = _darwin_bin(tmp_path, java=tmp_path / "bin" / "java")
    completed = _run_packages(tmp_path, fake, {})
    assert completed.returncode == 0, completed.stderr
    assert f"JAVA_BIN={fake / 'java'}" in completed.stdout
    assert not (tmp_path / "apt.txt").exists()
    assert "apt" not in completed.stdout
    assert "sudo" not in completed.stdout
    assert "brew install" not in (tmp_path / "ensure.log").read_text(encoding="utf-8")


def test_keg_only_opt_java_is_found_without_brew_install(tmp_path: Path) -> None:
    fake = _darwin_bin(tmp_path)
    root = tmp_path / "homebrew"
    opt = root / "opt" / "openjdk@21"
    _java(opt / "bin" / "java", 21)
    (root / "bin").mkdir(parents=True)
    _brew(fake / "brew")
    record = tmp_path / "brew.txt"
    completed = _run_packages(
        tmp_path,
        fake,
        {
            "BREW_RECORD": str(record),
            "BREW_ROOT": str(root),
            "BREW_OPENJDK_PREFIX": str(opt),
        },
    )
    assert completed.returncode == 0, completed.stderr
    assert f"JAVA_BIN={opt / 'bin' / 'java'}" in completed.stdout
    assert not record.exists()
    assert not (tmp_path / "apt.txt").exists()


def test_cellar_java_is_found_when_opt_is_missing(tmp_path: Path) -> None:
    fake = _darwin_bin(tmp_path)
    root = tmp_path / "homebrew"
    java = root / "Cellar" / "openjdk@21" / "21.0.2" / "libexec" / "openjdk.jdk" / "Contents" / "Home" / "bin" / "java"
    _java(java, 21)
    (root / "bin").mkdir(parents=True)
    _brew(fake / "brew")
    record = tmp_path / "brew.txt"
    completed = _run_packages(
        tmp_path,
        fake,
        {
            "BREW_RECORD": str(record),
            "BREW_ROOT": str(root),
            "BREW_OPENJDK_PREFIX": str(root / "opt" / "openjdk@21"),
        },
    )
    assert completed.returncode == 0, completed.stderr
    assert f"JAVA_BIN={java}" in completed.stdout
    assert not record.exists()


def test_java_home_is_used_when_path_java_is_missing(tmp_path: Path) -> None:
    fake = _darwin_bin(tmp_path)
    home = tmp_path / "jdk"
    _java(home / "bin" / "java", 21)
    completed = _run_packages(tmp_path, fake, {"JAVA_HOME": str(home)})
    assert completed.returncode == 0, completed.stderr
    assert f"JAVA_BIN={home / 'bin' / 'java'}" in completed.stdout


def test_old_path_java_loses_to_keg_only_21(tmp_path: Path) -> None:
    fake = _darwin_bin(tmp_path)
    _java(fake / "java", 17)
    root = tmp_path / "homebrew"
    opt = root / "opt" / "openjdk@21"
    _java(opt / "bin" / "java", 21)
    (root / "bin").mkdir(parents=True)
    _brew(fake / "brew")
    record = tmp_path / "brew.txt"
    completed = _run_packages(
        tmp_path,
        fake,
        {
            "BREW_RECORD": str(record),
            "BREW_ROOT": str(root),
            "BREW_OPENJDK_PREFIX": str(opt),
        },
    )
    assert completed.returncode == 0, completed.stderr
    assert f"JAVA_BIN={opt / 'bin' / 'java'}" in completed.stdout
    assert f"JAVA_BIN={fake / 'java'}" not in completed.stdout
    assert not record.exists()


def test_missing_java_uses_brew_install_not_apt(tmp_path: Path) -> None:
    fake = _darwin_bin(tmp_path)
    root = tmp_path / "homebrew"
    opt = root / "opt" / "openjdk@21"
    java = opt / "bin" / "java"
    (root / "bin").mkdir(parents=True)
    _brew(fake / "brew")
    record = tmp_path / "brew.txt"
    completed = _run_packages(
        tmp_path,
        fake,
        {
            "BREW_RECORD": str(record),
            "BREW_ROOT": str(root),
            "BREW_OPENJDK_PREFIX": str(opt),
            "BREW_JAVA_ON_INSTALL": str(java),
        },
    )
    assert completed.returncode == 0, completed.stderr
    assert record.read_text(encoding="utf-8").split() == ["openjdk@21"]
    assert f"JAVA_BIN={java}" in completed.stdout
    assert "Installing openjdk@21 with Homebrew" in completed.stdout
    assert not (tmp_path / "apt.txt").exists()
    assert "apt" not in completed.stdout
    assert "sudo" not in completed.stdout


def test_missing_python_uses_brew_install_python(tmp_path: Path) -> None:
    fake = _darwin_bin(tmp_path, java=tmp_path / "bin" / "java", python_ok=False)
    root = tmp_path / "homebrew"
    (root / "bin").mkdir(parents=True)
    _brew(fake / "brew")
    record = tmp_path / "brew.txt"
    completed = _run_packages(
        tmp_path,
        fake,
        {
            "BREW_RECORD": str(record),
            "BREW_ROOT": str(root),
            "BREW_PYTHON_ON_INSTALL": str(root / "bin" / "python3"),
        },
    )
    assert completed.returncode == 0, completed.stderr
    assert record.read_text(encoding="utf-8").split() == ["python"]
    assert not (tmp_path / "apt.txt").exists()


def test_missing_brew_and_java_does_not_call_apt(tmp_path: Path) -> None:
    fake = _darwin_bin(tmp_path)
    completed = _run_packages(tmp_path, fake, {})
    assert completed.returncode != 0
    assert "Homebrew is not installed" in completed.stdout
    assert "does not use apt or sudo" in completed.stdout
    assert "apt-get" not in completed.stdout
    assert not (tmp_path / "apt.txt").exists()


def test_linux_old_java_still_calls_apt(tmp_path: Path) -> None:
    fake = tmp_path / "bin"
    _java(fake / "java", 11)
    completed = _run_packages(tmp_path, fake, {})
    assert completed.returncode == 0, completed.stderr
    record = (tmp_path / "apt.txt").read_text(encoding="utf-8")
    assert "apt-get" in record
    assert "openjdk-21-jre-headless" in record
    assert "sudo" not in completed.stdout


def test_runner_embeds_the_discovered_java(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "batfish").mkdir(parents=True)
    java = "/opt/homebrew/opt/openjdk@21/bin/java"
    script = f"""
set -euo pipefail
JAVA_BIN={java}
DATA={data}
source <(sed -n '/^write_runner()/,/^}}/p' "{ROOT}/ensure-running")
write_runner
"""
    subprocess.run(["bash", "-c", script], check=True)
    text = (data / "batfish" / "run.sh").read_text(encoding="utf-8")
    assert f"exec {java} " in text


def test_scripts_pass_bash_n() -> None:
    for relative in (
        "ensure-running",
        "bin/install-launchers",
        "bin/open-lab",
        "bin/start-dryrun-lab",
        "bin/dryrun-home.sh",
        "bin/dryrun-lab",
    ):
        subprocess.run(["bash", "-n", str(ROOT / relative)], check=True)


def test_help_mentions_homebrew_and_keeps_docker_untested() -> None:
    completed = subprocess.run(
        ["bash", str(ROOT / "ensure-running"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "Homebrew" in completed.stdout
    assert "openjdk@21" in completed.stdout
    assert "does not use apt or sudo" in completed.stdout
    assert "Untested" in completed.stdout
    assert "does not install or start Docker" in completed.stdout
    assert "tested on macOS" not in completed.stdout.lower()


def test_readme_and_changelog_mark_macos_apple_silicon_tested() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    tested = (
        "Tested on Debian 13 (Grok Bot), Windows via WSL2 (Ubuntu 24.04), "
        "and macOS (Apple Silicon, Homebrew)."
    )
    assert "brew install openjdk@21" in readme
    assert "https://brew.sh" in readme
    assert "Clone into a normal folder" in readme
    assert "./ensure-running" in readme
    assert "http://127.0.0.1:8742" in readme
    assert tested in readme
    assert "## Unreleased" in changelog
    assert "keg-only" in changelog
    assert tested in changelog


def test_darwin_launchers_edit_zshrc_and_skip_desktop(tmp_path: Path) -> None:
    fake = tmp_path / "bin"
    _uname(fake / "uname", "Darwin")
    home = tmp_path / "home"
    env = os.environ.copy()
    env["PATH"] = f"{fake}:{env['PATH']}"
    env["HOME"] = str(home)
    env["SHELL"] = "/bin/zsh"
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env.pop("DRYRUN_HOME", None)
    completed = subprocess.run(
        ["bash", str(ROOT / "bin" / "install-launchers")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Added ~/.local/bin to PATH in ~/.zshrc" in completed.stdout
    zshrc = (home / ".zshrc").read_text(encoding="utf-8")
    assert zshrc.count("# dryrun-lab path") == 1
    assert not (home / ".bashrc").exists()
    assert not (home / ".config" / "autostart" / "start-dryrun-lab.desktop").exists()
    assert not (home / ".local" / "share" / "applications" / "start-dryrun-lab.desktop").exists()
    assert (home / ".local" / "bin" / "start-dryrun-lab").is_file()
    again = subprocess.run(
        ["bash", str(ROOT / "bin" / "install-launchers")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert again.returncode == 0, again.stderr
    assert "Added ~/.local/bin" not in again.stdout
    assert (home / ".zshrc").read_text(encoding="utf-8").count("# dryrun-lab path") == 1


def test_darwin_non_zsh_prints_path_instructions(tmp_path: Path) -> None:
    fake = tmp_path / "bin"
    _uname(fake / "uname", "Darwin")
    home = tmp_path / "home"
    env = os.environ.copy()
    env["PATH"] = f"{fake}:/usr/bin:/bin"
    env["HOME"] = str(home)
    env["SHELL"] = "/bin/bash"
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env.pop("DRYRUN_HOME", None)
    completed = subprocess.run(
        ["bash", str(ROOT / "bin" / "install-launchers")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert 'export PATH="$HOME/.local/bin:$PATH"' in completed.stdout
    assert "~/.zshrc" in completed.stdout
    assert not (home / ".bashrc").exists()
    assert not (home / ".zshrc").exists()
    assert not (home / ".config" / "autostart").exists()


def test_open_lab_on_darwin_uses_open(tmp_path: Path) -> None:
    fake = tmp_path / "bin"
    _uname(fake / "uname", "Darwin")
    opened = tmp_path / "opened"
    _exe(fake / "open", f"#!/bin/sh\nprintf '%s\\n' \"$1\" > {opened}\n")
    env = os.environ.copy()
    env["PATH"] = f"{fake}:{env['PATH']}"
    env["HOME"] = str(tmp_path / "home")
    env["DRYRUN_HOME"] = str(tmp_path / "data")
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    completed = subprocess.run(
        ["bash", str(ROOT / "bin" / "open-lab"), "http://127.0.0.1:8742"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    for _ in range(40):
        if opened.exists():
            break
        time.sleep(0.05)
    assert opened.read_text(encoding="utf-8").strip() == "http://127.0.0.1:8742"


def test_python_home_falls_back_when_readlink_has_no_f() -> None:
    script = f"""
set -euo pipefail
readlink() {{
  if [ "$1" = "-f" ]; then
    echo 'readlink: illegal option -- f' >&2
    return 1
  fi
  command readlink "$@"
}}
source <(sed -n '/^python_home()/,/^}}/p' "{ROOT}/ensure-running")
python_home
"""
    completed = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    expected = subprocess.run(
        [
            "python3",
            "-c",
            "import os, sys; exe = getattr(sys, '_base_executable', '') or sys.executable; print(os.path.dirname(os.path.abspath(exe)))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == expected.stdout.strip()
