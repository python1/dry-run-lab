"""Computes the office lab against a local engine. Skips if nothing is listening."""

import os
import socket
import uuid

os.environ.setdefault("DRYRUN_HOME", "/tmp/dryrun-engine-test")

import pytest

from dryrun_lab.engine import Engine
from dryrun_lab.examples import load_office_lab


def _engine_up() -> bool:
    probe = socket.socket()
    probe.settimeout(0.4)
    try:
        probe.connect(("127.0.0.1", 9996))
        return True
    except OSError:
        return False
    finally:
        probe.close()


pytestmark = pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")


def _engine() -> Engine:
    return Engine(network=f"dryrun-test-{uuid.uuid4().hex[:10]}")


def test_show_recomputes_a_cold_cache() -> None:
    lab = load_office_lab()
    engine = _engine()
    try:
        assert engine._ready is False
        route = engine.show(lab, "R1", "show ip route")
        assert engine._ready is True
        assert "[computed]" in route
        assert "10.255.1.1/32" in route
    finally:
        engine.close()


def test_office_lab_routes_interfaces_and_unparsed_lines() -> None:
    lab = load_office_lab()
    engine = _engine()
    try:
        _office_assertions(engine, lab)
    finally:
        engine.close()


def _office_assertions(engine: Engine, lab) -> None:
    engine.recompute(lab)
    assert lab.engine_error is None, lab.engine_error
    route = engine.show(lab, "R1", "show ip route")
    brief = engine.show(lab, "R1", "show ip interface brief")
    running = engine.show(lab, "R1", "show running-config")
    assert "[computed]" in route
    assert "[computed]" in brief
    assert "not proof that a live network" not in route
    assert "not proof that a live network" not in brief
    assert "10.255.1.1/32" in route
    assert "203.0.113.0/24" in route
    assert "0.0.0.0/0" in route
    assert "via 10.50.0.2" in route
    assert "sim" in brief
    assert "10.10.10.1" in brief
    assert "GUEST-IN" in running or "ip access-list extended GUEST-IN" in running
    texts = [row["text"] for row in lab.warnings]
    assert any("ip default-gateway" in text for text in texts)
    devices = {row.get("device") for row in lab.warnings}
    assert {"R1", "SW1", "SW2", "SW3"} <= devices
    details = {
        row.get("device"): row.get("detail")
        for row in lab.warnings
        if "default-gateway" in str(row.get("text") or "")
    }
    assert details["R1"] == "ignored when ip routing is enabled"
    assert details["SW1"] == "ignored when ip routing is enabled"
    assert "not currently supported" in str(details["SW2"])
    assert "not currently supported" in str(details["SW3"])
    assert details["R1"] != details["SW2"]
    joined = " ".join(texts)
    assert "Cisco" not in joined
    assert "NetSim" not in joined
    r1_warnings = engine.show(lab, "R1", "show warnings")
    sw2_warnings = engine.show(lab, "SW2", "show warnings")
    assert "ignored when ip routing is enabled" in r1_warnings
    assert "NOT simulated" not in r1_warnings
    assert "NOT simulated" in sw2_warnings
    assert "not currently supported" in sw2_warnings
