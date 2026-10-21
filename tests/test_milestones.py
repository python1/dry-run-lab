"""Three office-lab edits. Each one is reverted before the next."""

import os
import socket

os.environ.setdefault("DRYRUN_HOME", "/tmp/dryrun-milestone-test")

import pytest

from dryrun_lab.engine import Engine
from dryrun_lab.examples import load_office_lab

def _engine_up() -> bool:
    probe = socket.socket()
    try:
        return probe.connect_ex(("127.0.0.1", 9996)) == 0
    finally:
        probe.close()


pytestmark = pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")


def _engine() -> tuple[Engine, object]:
    lab = load_office_lab()
    engine = Engine()
    engine.recompute(lab)
    assert lab.engine_error is None, lab.engine_error
    return engine, lab


def _run(engine: Engine, lab, device: str, command: str) -> str:
    text = engine.show(lab, device, command)
    assert "[computed]" in text
    return text


def test_vlan_acl_and_trunk_milestones_revert() -> None:
    engine, lab = _engine()
    baseline = {device.name: device.config for device in lab.devices}

    vlan = _run(
        engine,
        lab,
        "R1",
        "\n".join(
            [
                "configure terminal",
                "interface GigabitEthernet0/0.40",
                "encapsulation dot1Q 40",
                "ip address 10.40.40.1 255.255.255.0",
                "no shutdown",
                "end",
            ]
        ),
    )
    assert "10.40.40.0/24" in vlan
    sw1 = _run(
        engine,
        lab,
        "SW1",
        "\n".join(
            [
                "configure terminal",
                "vlan 40",
                "name LAB",
                "interface GigabitEthernet1/0/1",
                "switchport trunk allowed vlan add 40",
                "interface GigabitEthernet1/0/2",
                "switchport trunk allowed vlan add 40",
                "end",
            ]
        ),
    )
    assert "no route changes" in sw1 or "Routes" in sw1
    _run(
        engine,
        lab,
        "SW2",
        "\n".join(
            [
                "configure terminal",
                "vlan 40",
                "name LAB",
                "interface GigabitEthernet0/12",
                "switchport mode access",
                "switchport access vlan 40",
                "no shutdown",
                "end",
            ]
        ),
    )
    brief = _run(engine, lab, "SW2", "show vlan brief")
    assert "40" in brief and "Gi0/12" in brief
    assert brief.index("Gi0/1") < brief.index("Gi0/12")
    trunk = _run(engine, lab, "SW1", "show interfaces trunk")
    assert "40" in trunk
    ping = _run(
        engine,
        lab,
        "R1",
        "ping 10.10.10.1 source 10.40.40.50 ingress GigabitEthernet0/0.40",
    )
    assert "100 percent" in ping
    assert "ACCEPTED" in ping
    trace = _run(
        engine,
        lab,
        "R1",
        "traceroute 10.10.10.1 source 10.40.40.50 ingress GigabitEthernet0/0.40",
    )
    assert "Computed traceroute" in trace
    for name in ("R1", "SW1", "SW2"):
        reverted = _run(engine, lab, name, "revert")
        assert "Nothing to revert" not in reverted
    assert {device.name: device.config for device in lab.devices} == baseline

    before = _run(
        engine,
        lab,
        "R1",
        "ping 10.99.0.1 source 10.30.30.50 ingress GigabitEthernet0/0.30",
    )
    assert "100 percent" in before
    blocked = _run(
        engine,
        lab,
        "R1",
        "\n".join(
            [
                "configure terminal",
                "ip access-list extended GUEST-IN",
                "deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255",
                "end",
            ]
        ),
    )
    assert "DENIED" in blocked or "Dropped by ACL GUEST-IN" in blocked
    denied = _run(
        engine,
        lab,
        "R1",
        "ping 10.99.0.1 source 10.30.30.50 ingress GigabitEthernet0/0.30",
    )
    assert "0 percent" in denied
    assert "Dropped by ACL GUEST-IN" in denied
    assert "deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255" in denied
    lists = _run(engine, lab, "R1", "show access-lists")
    assert lists.index("deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255") < lists.index("permit ip any any")
    _run(engine, lab, "R1", "revert")
    restored = _run(
        engine,
        lab,
        "R1",
        "ping 10.99.0.1 source 10.30.30.50 ingress GigabitEthernet0/0.30",
    )
    assert "100 percent" in restored
    assert lab.device("R1").config == baseline["R1"]

    ospf = _run(engine, lab, "R1", "traceroute 10.255.1.1 source 10.50.0.1")
    assert "ACCEPTED" in ospf
    office = _run(
        engine,
        lab,
        "R1",
        "ping 10.20.20.1 source 10.10.10.50 ingress GigabitEthernet0/0.10",
    )
    assert "100 percent" in office
    diff = _run(
        engine,
        lab,
        "R1",
        "\n".join(
            [
                "configure terminal",
                "interface GigabitEthernet0/0",
                "shutdown",
                "end",
            ]
        ),
    )
    _run(
        engine,
        lab,
        "SW1",
        "\n".join(["configure terminal", "interface GigabitEthernet1/0/1", "shutdown", "end"]),
    )
    assert "10.10.10.0/24" in diff
    lost = _run(
        engine,
        lab,
        "R1",
        "ping 10.20.20.1 source 10.10.10.50 ingress GigabitEthernet0/0.10",
    )
    assert "0 percent" in lost or "NO_ACTIVE_LOCATION" in lost or "no active location" in lost
    still = _run(engine, lab, "R1", "traceroute 10.255.1.1 source 10.50.0.1")
    assert "ACCEPTED" in still
    routes = _run(engine, lab, "R1", "show ip route")
    assert "10.10.10.0/24" not in routes
    assert "10.20.20.0/24" not in routes
    assert "10.30.30.0/24" not in routes
    assert "10.99.0.0/24" not in routes
    assert "10.255.1.1/32" in routes
    _run(engine, lab, "R1", "revert")
    _run(engine, lab, "SW1", "revert")
    back = _run(
        engine,
        lab,
        "R1",
        "ping 10.20.20.1 source 10.10.10.50 ingress GigabitEthernet0/0.10",
    )
    assert "100 percent" in back
    assert {device.name: device.config for device in lab.devices} == baseline
