"""Office-lab edits. Each engine uses its own network, not the live lab."""

import os
import socket
import uuid

os.environ.setdefault("DRYRUN_HOME", "/tmp/dryrun-milestone-test")

import pytest

from dryrun_lab.configparse import canonical_interface
from dryrun_lab.engine import Engine
from dryrun_lab.examples import load_office_lab
from dryrun_lab.store import Device, add_user_link, place_host

def _engine_up() -> bool:
    probe = socket.socket()
    try:
        return probe.connect_ex(("127.0.0.1", 9996)) == 0
    finally:
        probe.close()


pytestmark = pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")


def _engine() -> tuple[Engine, object]:
    lab = load_office_lab()
    engine = Engine(network=f"dryrun-test-{uuid.uuid4().hex[:10]}")
    engine.recompute(lab)
    assert lab.engine_error is None, lab.engine_error
    return engine, lab


def _run(engine: Engine, lab, device: str, command: str) -> str:
    text = engine.show(lab, device, command)
    assert "[computed]" in text
    return text


def test_vlan_acl_and_trunk_milestones_revert() -> None:
    engine, lab = _engine()
    try:
        _vlan_acl_and_trunk(engine, lab)
    finally:
        engine.close()


def _vlan_acl_and_trunk(engine: Engine, lab) -> None:
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
                "25 deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255",
                "end",
            ]
        ),
    )
    assert "never match" not in blocked
    denied = _run(
        engine,
        lab,
        "R1",
        "ping 10.99.0.1 source 10.30.30.50 ingress GigabitEthernet0/0.30",
    )
    assert "0 percent" in denied
    assert "Dropped by ACL GUEST-IN" in denied
    assert (
        "Dropped because ACL GUEST-IN sequence 25 on R1 Gi0/0.30 denies 10.30.30.0/24 to 10.99.0.0/24."
        in denied
    )
    assert "deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255" in denied
    lists = _run(engine, lab, "R1", "show access-lists")
    guest = "deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255"
    assert lists.index("    10 deny") < lists.index("    20 deny") < lists.index(f"    25 {guest}")
    assert lists.index(f"    25 {guest}") < lists.index("    30 permit ip any any")
    assert "line " not in lists
    reverted = _run(engine, lab, "R1", "revert")
    assert "Reverted one edit. Recomputed." in reverted
    assert "Applied 1 line" not in reverted
    assert "10.30.30.50 -> 10.99.0.50" in reverted
    assert "sequence 25" in reverted
    assert "DENIED" in reverted
    assert "DELIVERED_TO_SUBNET" in reverted or "ACCEPTED" in reverted
    restored = _run(
        engine,
        lab,
        "R1",
        "ping 10.99.0.1 source 10.30.30.50 ingress GigabitEthernet0/0.30",
    )
    assert "100 percent" in restored
    assert lab.device("R1").config == baseline["R1"]

    warned = _run(
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
    assert "Line added at sequence 40, after sequence 30 permit ip any any; it will never match." in warned
    lists = _run(engine, lab, "R1", "show access-lists")
    assert lists.index("    30 permit ip any any") < lists.index(f"    40 {guest}")
    still = _run(
        engine,
        lab,
        "R1",
        "ping 10.99.0.1 source 10.30.30.50 ingress GigabitEthernet0/0.30",
    )
    assert "100 percent" in still
    assert "ACCEPTED" in still
    assert "Dropped" not in still
    _run(engine, lab, "R1", "revert")
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


def _host(name: str, address: str, gateway: str, x: float, y: float) -> Device:
    return Device(
        name=name,
        role="host",
        x=x,
        y=y,
        config=(
            f"hostname {name}\n!\ninterface Ethernet0\n ip address {address} 255.255.255.0\n!\n"
            f"ip default-gateway {gateway}\n!\nend\n"
        ),
    )


def _confirm_pair(lab, left: str, right: str) -> None:
    for link in lab.links:
        if {link.a_device, link.b_device} == {left, right}:
            link.status = "confirmed"


def test_host_on_vlan_40_reaches_server_until_the_sw1_sw2_trunk_is_down() -> None:
    engine, lab = _engine()
    try:
        _run(
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
        _run(
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
        _run(
            engine,
            lab,
            "SW2",
            "\n".join(
                [
                    "configure terminal",
                    "vlan 40",
                    "name LAB",
                    "interface GigabitEthernet0/1",
                    "switchport trunk allowed vlan add 40",
                    "interface GigabitEthernet0/12",
                    "switchport mode access",
                    "switchport access vlan 40",
                    "no shutdown",
                    "end",
                ]
            ),
        )
        x, y = place_host(lab)
        lab.devices.append(_host("PC40", "10.40.40.50", "10.40.40.1", x, y))
        x, y = place_host(lab)
        lab.devices.append(_host("SRV20", "10.20.20.50", "10.20.20.1", x, y))
        sw2 = lab.device("SW2")
        pc40 = lab.device("PC40")
        assert sw2 is not None and pc40 is not None
        assert pc40.y >= sw2.y + 48 + 4 * 26 + 12 + 64
        _confirm_pair(lab, "R1", "SW1")
        _confirm_pair(lab, "SW1", "SW2")
        _confirm_pair(lab, "SW1", "SW3")
        add_user_link(lab, "PC40", "Ethernet0", "SW2", "GigabitEthernet0/12")
        add_user_link(lab, "SRV20", "Ethernet0", "SW3", "GigabitEthernet0/10")
        engine.recompute(lab)
        assert lab.engine_error is None, lab.engine_error
        reached = _run(engine, lab, "PC40", "ping 10.20.20.50")
        assert "100 percent" in reached
        assert "Disposition: ACCEPTED" in reached
        assert "Delivered to SRV20 on Ethernet0." in reached
        assert "not hops in this computed trace" in reached
        vlan40 = next(line for line in reached.splitlines() if line.startswith("VLAN 40:"))
        assert vlan40.index("SW2") < vlan40.index("SW1") < vlan40.index("R1")
        assert "Gi0/0.40" in vlan40
        traced = _run(engine, lab, "PC40", "traceroute 10.20.20.50")
        assert "ACCEPTED" in traced
        assert "SW2" in traced and "SW1" in traced and "R1" in traced
        shut = _run(
            engine,
            lab,
            "SW1",
            "\n".join(
                ["configure terminal", "interface GigabitEthernet1/0/2", "shutdown", "end"]
            ),
        )
        assert "PC40" in shut and "10.20.20.50" in shut
        assert "NEIGHBOR_UNREACHABLE" in shut
        assert "(no reachability changes)" not in shut
        lost = _run(engine, lab, "PC40", "ping 10.20.20.50")
        assert "0 percent" in lost
        assert "NEIGHBOR_UNREACHABLE" in lost
        assert "No neighbor answered for 10.40.40.1 on PC40 Ethernet0." in lost
        assert "is down" in lost
        trunk = next(
            link
            for link in lab.links
            if {canonical_interface(link.a_interface), canonical_interface(link.b_interface)}
            == {"GigabitEthernet1/0/2", "GigabitEthernet0/1"}
        )
        assert trunk.down is True
        assert engine.network.startswith("dryrun-test-")
        assert engine.network != "dryrun"
    finally:
        engine.close()
