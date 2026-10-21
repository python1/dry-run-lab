import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _fetch():
    path = ROOT / "tools" / "fetch_batfish.py"
    spec = importlib.util.spec_from_file_location("fetch_batfish", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_batfish_pins_fail_closed() -> None:
    module = _fetch()
    assert module.PINNED_LAYER == (
        "sha256:53a5a598343f477bae7c97f39174d545529d2d080ed30ec3652c6e3e7ae0ac70"
    )
    assert module.PINNED_JAR == "7552e1380e79379b17e200b80d84c1671f689cb63a0d338678c1c4675157310f"
    source = (ROOT / "tools" / "fetch_batfish.py").read_text(encoding="utf-8")
    assert ":latest" not in source
    assert "_download_by_scanning" not in source
    assert "layer sha256 verified: {PINNED_LAYER}" in source
    assert "batfish jar cached, sha256 verified" in source
    assert source.index("if cached:") < source.index("layer sha256 verified:")
    with pytest.raises(module.BatfishPinError, match="layer sha256 mismatch"):
        module._check_blob(b"not the layer")
    with pytest.raises(module.BatfishPinError, match="jar sha256 mismatch"):
        module._check_jar(b"not the jar")
    starter = (ROOT / "ensure-running").read_text(encoding="utf-8")
    assert "batfish/allinone:latest" not in starter
    assert "batfish/allinone:v2026.08.27" in starter
    assert "summarize_apt" in starter
    assert "reap_pid" in starter
    assert "Reading database" in starter
    assert "Adding debian:" in starter
    assert "CA certificates:" in starter
    assert "Failed to retrieve available kernel versions" in starter
    assert "No services need to be restarted" in starter
    assert 'log "dryrun-lab ${stamp}"' in starter
    body = starter.split("summarize_apt()", 1)[1].split("apt_logged()", 1)[0]
    assert body.index(">>\"$LOG\"") < body.index("CA certificates:")
    call = starter.split("log() {", 1)[1]
    assert call.index("dryrun-lab ${stamp}") < call.index("\ninstall_packages\n")


def test_sweep_removes_test_networks_and_keeps_dryrun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dryrun_lab.engine import _sweep_test_directories

    monkeypatch.setenv("DRYRUN_HOME", str(tmp_path))
    live = tmp_path / "batfish" / "data" / "networks" / "live-id" / "original" / "snap"
    live.mkdir(parents=True)
    _zip(live / "snapshot.zip", "dryrun/configs/R1.cfg")
    test = tmp_path / "batfish" / "data" / "networks" / "test-id" / "original" / "snap"
    test.mkdir(parents=True)
    _zip(test / "snapshot.zip", "dryrun-test-abc/configs/R1.cfg")
    ids = tmp_path / "batfish" / "data" / "ids" / "NetworkId" / "test-id"
    ids.mkdir(parents=True)
    (ids / "marker").write_text("x", encoding="utf-8")
    snap = tmp_path / "snapshots" / "dryrun-test-abc"
    snap.mkdir(parents=True)
    keep = tmp_path / "snapshots" / "dryrun"
    keep.mkdir(parents=True)
    _sweep_test_directories(set())
    assert (live / "snapshot.zip").is_file()
    assert not test.exists()
    assert not ids.exists()
    assert not snap.exists()
    assert keep.is_dir()


def _zip(path: Path, name: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "hostname R1\n")
