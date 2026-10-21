import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _summarize(tmp_path: Path, apt_text: str) -> str:
    apt = tmp_path / "apt.txt"
    log = tmp_path / "ensure.log"
    apt.write_text(apt_text, encoding="utf-8")
    script = f"""
set -euo pipefail
source <(sed -n '/^summarize_apt()/,/^}}/p' "{ROOT}/ensure-running")
log() {{ printf '%s\\n' "$*" >>"$LOG"; }}
summarize_apt "{apt}"
"""
    subprocess.run(
        ["bash", "-c", script],
        check=True,
        env={**os.environ, "LOG": str(log)},
    )
    return log.read_text(encoding="utf-8")


def test_fresh_install_certificate_lines_collapse_to_one_summary(tmp_path: Path) -> None:
    lines = [f"Adding debian:Cert{index}.pem" for index in range(148)]
    lines.extend(
        [
            "",
            "Reading database ... 50%",
            "Failed to retrieve available kernel versions.",
            "Failed to check for processor microcode upgrades.",
            "No services need to be restarted.",
            "needrestart: pending",
            "",
            "E: Could not download a required package",
            "",
        ]
    )
    text = _summarize(tmp_path, "\n".join(lines) + "\n")
    assert text == "E: Could not download a required package\nCA certificates: 148 added\n"
    assert "Adding debian:" not in text
    assert "Reading database" not in text
    assert "needrestart" not in text
    assert "kernel versions" not in text
    assert "microcode" not in text
    assert "No services need to be restarted" not in text


def test_added_and_replaced_certificates_share_one_summary_line(tmp_path: Path) -> None:
    apt = "\n".join(
        [
            "Adding debian:One.pem",
            "Adding debian:Two.pem",
            "Replacing debian:Three.pem",
            "Preparing to unpack something.",
        ]
    )
    text = _summarize(tmp_path, apt + "\n")
    assert text == "Preparing to unpack something.\nCA certificates: 2 added, 1 replaced\n"


def test_cached_provenance_does_not_claim_the_layer_was_hashed(tmp_path: Path, capsys) -> None:
    import importlib.util

    path = ROOT / "tools" / "fetch_batfish.py"
    spec = importlib.util.spec_from_file_location("fetch_batfish_log", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "allinone-bundle.jar").write_bytes(b"not-the-real-jar")
    module._write_provenance(tmp_path, cached=True)
    cached = capsys.readouterr().out
    assert "batfish jar cached, sha256 verified" in cached
    assert "layer sha256 verified:" not in cached
    module._write_provenance(tmp_path, cached=False)
    downloaded = capsys.readouterr().out
    assert f"layer sha256 verified: {module.PINNED_LAYER}" in downloaded
    assert "batfish jar cached, sha256 verified" not in downloaded
