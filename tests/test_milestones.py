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

def _warnings_section(text: str) -> str:
    return text.split("\nWarnings\n", 1)[1].split("\nReachability\n", 1)[0]


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
    running = _run(engine, lab, "R1", "show running-config")
    assert f" 25 {guest}" in running
    assert " 10 deny" not in running
    assert " 20 deny" not in running
    assert " 30 permit" not in running
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
    added_warnings = _warnings_section(warned)
    assert "Line added at sequence 40, after sequence 30 permit ip any any; it will never match." in added_warnings
    assert any(line.startswith("  + ") and "never match" in line for line in added_warnings.splitlines())
    assert "(no warning changes)" not in added_warnings
    assert any(row.get("kind") == "unreachable" and "never match" in str(row.get("text")) for row in lab.warnings)
    lists = _run(engine, lab, "R1", "show access-lists")
    assert lists.index("    30 permit ip any any") < lists.index(f"    40 {guest}")
    running = _run(engine, lab, "R1", "show running-config")
    assert guest in running
    assert " 40 deny" not in running
    assert f" 40 {guest}" not in running
    still = _run(
        engine,
        lab,
        "R1",
        "ping 10.99.0.1 source 10.30.30.50 ingress GigabitEthernet0/0.30",
    )
    assert "100 percent" in still
    assert "ACCEPTED" in still
    assert "Dropped" not in still
    cleared = _run(engine, lab, "R1", "revert")
    removed_warnings = _warnings_section(cleared)
    assert "Line added at sequence 40, after sequence 30 permit ip any any; it will never match." in removed_warnings
    assert any(line.startswith("  - ") and "never match" in line for line in removed_warnings.splitlines())
    assert "(no warning changes)" not in removed_warnings
    assert not any(row.get("kind") == "unreachable" for row in lab.warnings)
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
        sw3 = lab.device("SW3")
        srv20 = lab.device("SRV20")
        assert sw3 is not None and srv20 is not None
        assert pc40.x == sw2.x
        assert srv20.x == sw3.x
        assert srv20.y >= sw3.y + 48 + 12 + 64
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


def _never_match_lines(section: str, prefix: str) -> list[str]:
    return [line for line in section.splitlines() if line.startswith(prefix) and "never match" in line]


def test_duplicate_acl_line_warning_names_the_line_that_cannot_match() -> None:
    """A second copy of an ACE is the unreachable line, not the earlier one."""
    guest = "deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255"
    engine, lab = _engine()
    try:
        assert engine.network.startswith("dryrun-test-")
        assert engine.network != "dryrun"
        added = _run(
            engine,
            lab,
            "R1",
            "\n".join(
                [
                    "configure terminal",
                    "ip access-list extended GUEST-IN",
                    f"25 {guest}",
                    "end",
                ]
            ),
        )
        head, warnings = added.split("\nWarnings\n", 1)
        warnings = warnings.split("\nReachability\n", 1)[0]
        assert "Line added at sequence 25, after sequence 10" in head
        assert guest in head
        assert "it will never match." in head
        assert "added at sequence 10" not in added
        plus = _never_match_lines(warnings, "  + ")
        assert plus == [
            "  + R1 Line added at sequence 25, after sequence 10 "
            f"{guest}; it will never match. (ACL GUEST-IN sequence 25)"
        ]
        denied = _run(
            engine,
            lab,
            "R1",
            "ping 10.10.10.1 source 10.30.30.50 ingress GigabitEthernet0/0.30",
        )
        drop = denied.split("Dropped by ACL", 1)[1]
        assert "sequence 10:" in drop
        assert "sequence 25" not in drop
        assert "Dropped because ACL GUEST-IN sequence 10" in denied
        reverted = _run(engine, lab, "R1", "revert")
        removed = _warnings_section(reverted)
        minus = _never_match_lines(removed, "  - ")
        assert minus == [
            "  - R1 Line added at sequence 25, after sequence 10 "
            f"{guest}; it will never match. (ACL GUEST-IN sequence 25)"
        ]
        assert "added at sequence 10" not in reverted

        shadowed = _run(
            engine,
            lab,
            "R1",
            "\n".join(
                [
                    "configure terminal",
                    "ip access-list extended GUEST-IN",
                    f"5 {guest}",
                    "end",
                ]
            ),
        )
        head, warnings = shadowed.split("\nWarnings\n", 1)
        warnings = warnings.split("\nReachability\n", 1)[0]
        expected = (
            "Line at sequence 10, after sequence 5 "
            f"{guest}; it will never match."
        )
        assert expected in head
        assert "Line added" not in head
        assert "added at sequence 10" not in shadowed
        assert "added at sequence 5" not in shadowed
        plus = _never_match_lines(warnings, "  + ")
        assert plus == [f"  + R1 {expected} (ACL GUEST-IN sequence 10)"]
        denied = _run(
            engine,
            lab,
            "R1",
            "ping 10.10.10.1 source 10.30.30.50 ingress GigabitEthernet0/0.30",
        )
        drop = denied.split("Dropped by ACL", 1)[1]
        assert "sequence 5:" in drop
        assert "sequence 10" not in drop
        assert "Dropped because ACL GUEST-IN sequence 5" in denied
        reverted = _run(engine, lab, "R1", "revert")
        removed = _warnings_section(reverted)
        minus = _never_match_lines(removed, "  - ")
        assert minus == [f"  - R1 {expected} (ACL GUEST-IN sequence 10)"]
        assert "added" not in removed
        assert lab.device("R1").config == load_office_lab().device("R1").config
    finally:
        engine.close()
