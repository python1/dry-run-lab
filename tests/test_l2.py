"""Host files, confirmed-only layer 1, and the separate layer-2 note."""

import json

from dryrun_lab.engine import Engine
from dryrun_lab.hosts import host_document, host_limits
from dryrun_lab.l2path import layer2_note
from dryrun_lab.store import Device, Lab, add_user_link


def _host(name: str, address: str, gateway: str) -> Device:
    config = (
        f"hostname {name}\n!\ninterface Ethernet0\n ip address {address} 255.255.255.0\n!\n"
        f"ip default-gateway {gateway}\n!\nend\n"
    )
    return Device(name=name, role="host", config=config)


def _row(name: str, mode: str, vlan: int | None, allowed: str, up: bool = True) -> dict:
    return {
        "name": name,
        "mode": mode,
        "access_vlan": vlan,
        "allowed": allowed,
        "admin_up": up,
        "active": up,
    }


def test_host_document_uses_prefix_and_gateway() -> None:
    doc = host_document("PC40", _host("PC40", "10.40.40.50", "10.40.40.1").config)
    assert doc is not None
    assert doc["hostname"] == "pc40"
    assert doc["hostInterfaces"]["Ethernet0"]["prefix"] == "10.40.40.50/24"
    assert doc["hostInterfaces"]["Ethernet0"]["gateway"] == "10.40.40.1"


def test_unattached_host_is_labeled_not_modeled() -> None:
    lab = Lab()
    lab.devices.append(_host("PC40", "10.40.40.50", "10.40.40.1"))
    rows = host_limits(lab)
    assert rows[0]["kind"] == "limit"
    assert "Suggested links are not used" in rows[0]["detail"]


def test_snapshot_writes_hosts_and_only_confirmed_edges(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DRYRUN_HOME", str(tmp_path))
    lab = Lab()
    lab.devices.append(Device(name="SW2", role="switch", config="hostname SW2\n!\ninterface GigabitEthernet0/12\n switchport mode access\n switchport access vlan 40\n!\nend\n"))
    lab.devices.append(_host("PC40", "10.40.40.50", "10.40.40.1"))
    add_user_link(lab, "PC40", "Ethernet0", "SW2", "GigabitEthernet0/12")
    lab.links.append(
        type(lab.links[0])(
            id="suggested",
            a_device="PC40",
            a_interface="Ethernet0",
            b_device="SW2",
            b_interface="GigabitEthernet0/10",
            status="suggested",
            source="infer",
            reason="guess",
        )
    )
    root = Engine(network="dryrun-test-snapshot")._write_snapshot(lab)
    host = json.loads((root / "hosts" / "pc40.json").read_text())
    assert host["hostname"] == "pc40"
    assert not (root / "configs" / "pc40.cfg").exists()
    edges = json.loads((root / "batfish" / "layer1_topology.json").read_text())["edges"]
    assert len(edges) == 1
    assert edges[0]["node1"]["hostname"] == "pc40"
    assert edges[0]["node2"]["interfaceName"] == "GigabitEthernet0/12"


def test_layer2_note_names_switches_and_stops_on_a_down_link() -> None:
    lab = Lab()
    lab.devices.extend(
        [
            _host("PC40", "10.40.40.50", "10.40.40.1"),
            Device(
                name="SW2",
                role="switch",
                config="hostname SW2\n!\ninterface GigabitEthernet0/1\n switchport mode trunk\n!\nend\n",
            ),
            Device(
                name="SW1",
                role="switch",
                config="hostname SW1\n!\ninterface GigabitEthernet1/0/1\n switchport mode trunk\n!\nend\n",
            ),
            Device(
                name="R1",
                role="router",
                config=(
                    "hostname R1\n!\ninterface GigabitEthernet0/0.40\n"
                    " encapsulation dot1Q 40\n ip address 10.40.40.1 255.255.255.0\n!\nend\n"
                ),
            ),
        ]
    )
    add_user_link(lab, "PC40", "Ethernet0", "SW2", "GigabitEthernet0/12")
    add_user_link(lab, "SW2", "GigabitEthernet0/1", "SW1", "GigabitEthernet1/0/2")
    add_user_link(lab, "SW1", "GigabitEthernet1/0/1", "R1", "GigabitEthernet0/0")
    up = {
        "sw2": [
            _row("GigabitEthernet0/12", "ACCESS", 40, ""),
            _row("GigabitEthernet0/1", "TRUNK", None, "10,20,30,40,99"),
        ],
        "sw1": [
            _row("GigabitEthernet1/0/2", "TRUNK", None, "10,20,30,40,99"),
            _row("GigabitEthernet1/0/1", "TRUNK", None, "10,20,30,40,99"),
        ],
        "r1": [_row("GigabitEthernet0/0", "NONE", None, "")],
    }
    note = layer2_note(lab, up, "PC40", "10.20.20.50")
    assert note is not None
    assert "not hops in this computed trace" in note
    line = next(item for item in note.splitlines() if item.startswith("VLAN 40:"))
    assert line.index("SW2") < line.index("SW1") < line.index("R1")
    assert "Gi0/0.40" in line
    down = {
        **up,
        "sw1": [
            _row("GigabitEthernet1/0/2", "TRUNK", None, "10,20,30,40,99", up=False),
            _row("GigabitEthernet1/0/1", "TRUNK", None, "10,20,30,40,99"),
        ],
    }
    stopped = layer2_note(lab, down, "PC40", "10.20.20.50")
    assert stopped is not None
    assert "is down" in stopped
    assert "Gi1/0/2" in stopped
