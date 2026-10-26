"""Sage QC: silent gaps, layer-2 wording, host cables, CLI, assets, refresh."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dryrun_lab.cli import main
from dryrun_lab.configedit import apply_config_lines
from dryrun_lab.engine import _with_local_warnings
from dryrun_lab.hosts import host_config
from dryrun_lab.infer import infer
from dryrun_lab.ioscheck import KEPT_NOTE, invalid_input, kept_note, unmodeled_lines
from dryrun_lab.l2path import layer2_note
from dryrun_lab.showfmt import format_ping
from dryrun_lab.store import Device, Lab, Store, add_user_link

ROOT = Path(__file__).resolve().parents[1]
HELPER = "ip helper-address 10.1.1.1"
FALSE_STOP = "Stops here. No confirmed link carries this VLAN to the gateway."


def _svis(name: str, vlans: list[int]) -> str:
    lines = [f"hostname {name}", "!"]
    for vlan in vlans:
        lines.extend(
            [
                f"interface Vlan{vlan}",
                f" ip address 10.16.{vlan}.1 255.255.255.0",
                f" {HELPER}",
                "!",
            ]
        )
    lines.append("end")
    return "\n".join(lines) + "\n"


def test_helper_and_other_silent_forwarding_lines_are_flagged_per_occurrence() -> None:
    sw1 = _svis("SW1", [10, 20, 30])
    sw2 = _svis("SW2", [10, 20])
    assert [text for _line, text in unmodeled_lines(sw1)].count(HELPER) == 3
    assert [text for _line, text in unmodeled_lines(sw2)].count(HELPER) == 2
    rows = _with_local_warnings([], {"SW1": sw1, "SW2": sw2})
    helpers = [row for row in rows if row["text"] == HELPER]
    assert len(helpers) == 5
    assert len({(row["device"], row["line"]) for row in helpers}) == 5
    assert {row["detail"] for row in helpers} == {"not simulated"}
    assert {row["file"] for row in helpers} == {"configs/SW1.cfg", "configs/SW2.cfg"}

    extra = "\n".join(
        [
            "hostname CORE",
            "standby 1 ip 10.16.10.1",
            "vrrp 1 ip 10.16.10.1",
            "glbp 1 ip 10.16.10.1",
            "interface Vlan10",
            " ip policy route-map PBR",
            " switchport voice vlan 20",
            " ip directed-broadcast",
            " dot1x pae authenticator",
            " mab",
            " authentication port-control auto",
            "vlan access-map BLOCK 10",
            "vlan filter BLOCK vlan-list 10",
            "logging host 10.9.9.9",
            "end",
            "",
        ]
    )
    flagged = [text for _line, text in unmodeled_lines(extra)]
    for text in (
        "standby 1 ip 10.16.10.1",
        "vrrp 1 ip 10.16.10.1",
        "glbp 1 ip 10.16.10.1",
        "ip policy route-map PBR",
        "switchport voice vlan 20",
        "ip directed-broadcast",
        "dot1x pae authenticator",
        "mab",
        "authentication port-control auto",
        "vlan access-map BLOCK 10",
        "vlan filter BLOCK vlan-list 10",
    ):
        assert text in flagged
    assert not any("logging" in text for text in flagged)
    assert invalid_input([], "logging host 10.9.9.9") is None
    assert kept_note([], "logging host 10.9.9.9") is None


def test_helper_address_is_kept_in_config_mode() -> None:
    assert invalid_input([], "ip helper-address 10.1.1.1") is None
    assert kept_note([], "ip helper-address 10.1.1.1") == KEPT_NOTE
    assert invalid_input(["interface Vlan10"], "ip helper-address 10.1.1.1") is None
    assert kept_note(["interface Vlan10"], "ip helper-address 10.1.1.1") is None
    assert invalid_input(["interface Vlan10"], "standby 1 ip 10.16.10.1") is None
    assert invalid_input(["interface GigabitEthernet0/10"], "switchport voice vlan 20") is None
    assert invalid_input([], "vlan access-map BLOCK 10") is None
    assert kept_note([], "vlan access-map BLOCK 10") == KEPT_NOTE
    assert invalid_input([], "frobnicate")
    updated = apply_config_lines(
        "hostname SW\n!\ninterface Vlan10\n ip address 10.16.10.1 255.255.255.0\n!\nend\n",
        ["interface Vlan10", "ip helper-address 10.1.1.1", "ip helper-address 10.1.1.2", "end"],
    )
    assert updated.count("ip helper-address 10.1.1.1") == 1
    assert updated.count("ip helper-address 10.1.1.2") == 1


def _row(name: str, mode: str, vlan: int | None, allowed: str, up: bool = True) -> dict:
    return {
        "name": name,
        "mode": mode,
        "access_vlan": vlan,
        "allowed": allowed,
        "admin_up": up,
        "active": up,
    }


def _svi_lab() -> Lab:
    lab = Lab()
    lab.devices.extend(
        [
            Device(
                name="POS-01",
                role="host",
                config=host_config("POS-01", "10.16.10.41/24", "10.16.10.1"),
            ),
            Device(
                name="WHSE-SCAN",
                role="host",
                config=host_config("WHSE-SCAN", "10.16.20.41/24", "10.16.20.1"),
            ),
            Device(
                name="ACC",
                role="switch",
                config=(
                    "hostname ACC\n!\n"
                    "interface GigabitEthernet0/10\n switchport mode access\n switchport access vlan 10\n!\n"
                    "interface GigabitEthernet0/1\n switchport mode trunk\n!\nend\n"
                ),
            ),
            Device(
                name="CORE",
                role="switch",
                config=(
                    "hostname CORE\n!\n"
                    "interface GigabitEthernet1/0/1\n switchport mode trunk\n!\n"
                    "interface Vlan10\n ip address 10.16.10.1 255.255.255.0\n no shutdown\n!\n"
                    "interface Vlan20\n ip address 10.16.20.1 255.255.255.0\n no shutdown\n!\nend\n"
                ),
            ),
        ]
    )
    add_user_link(lab, "POS-01", "Ethernet0", "ACC", "GigabitEthernet0/10")
    add_user_link(lab, "ACC", "GigabitEthernet0/1", "CORE", "GigabitEthernet1/0/1")
    return lab


def test_svi_gateway_is_reached_and_a_missing_vlan_still_stops() -> None:
    lab = _svi_lab()
    carried = {
        "acc": [
            _row("GigabitEthernet0/10", "ACCESS", 10, ""),
            _row("GigabitEthernet0/1", "TRUNK", None, "10,20,30"),
        ],
        "core": [
            _row("GigabitEthernet1/0/1", "TRUNK", None, "10,20,30"),
            _row("Vlan10", "NONE", None, ""),
        ],
    }
    note = layer2_note(lab, carried, "POS-01", "10.16.30.50")
    assert note is not None
    assert FALSE_STOP not in note
    assert "CORE" in note and "Vlan10" in note and "ACC" in note

    blocked = {
        "acc": [
            _row("GigabitEthernet0/10", "ACCESS", 20, ""),
            _row("GigabitEthernet0/1", "TRUNK", None, "10,30"),
        ],
        "core": [
            _row("GigabitEthernet1/0/1", "TRUNK", None, "10,30"),
            _row("Vlan20", "NONE", None, ""),
        ],
    }
    lab.devices[0].config = host_config("POS-01", "10.16.20.41/24", "10.16.20.1")
    stopped = layer2_note(lab, blocked, "POS-01", "10.16.10.1")
    assert stopped is not None
    assert FALSE_STOP in stopped
    assert "CORE" not in stopped


def test_successful_ping_never_prints_the_false_l2_stop() -> None:
    note = f"Switches are not hops in this computed trace.\nVLAN 10: POS-01 Et0 — ACC Gi0/10. {FALSE_STOP}"
    success = format_ping("10.16.10.1", None, None, {"disposition": "ACCEPTED", "steps": [], "l2": note}, None)
    assert "100 percent" in success
    assert FALSE_STOP not in success
    assert "Switches are not hops" in success
    failure = format_ping(
        "10.16.20.1",
        None,
        None,
        {"disposition": "NEIGHBOR_UNREACHABLE", "steps": [], "l2": note},
        None,
    )
    assert FALSE_STOP in failure
    assert "0 percent" in failure


def test_gateway_address_does_not_pull_in_another_hosts_vlan() -> None:
    lab = _svi_lab()
    add_user_link(lab, "WHSE-SCAN", "Ethernet0", "ACC", "GigabitEthernet0/11")
    interfaces = {
        "acc": [
            _row("GigabitEthernet0/10", "ACCESS", 10, ""),
            _row("GigabitEthernet0/11", "ACCESS", 20, ""),
            _row("GigabitEthernet0/1", "TRUNK", None, "10"),
        ],
        "core": [_row("GigabitEthernet1/0/1", "TRUNK", None, "10")],
    }
    note = layer2_note(lab, interfaces, "POS-01", "10.16.20.1")
    assert note is not None
    assert "WHSE-SCAN" not in note
    assert FALSE_STOP not in note


def test_host_cable_is_suggested_from_vlan_and_description() -> None:
    switch = """
hostname ACC-SALES
!
interface GigabitEthernet0/1
 description to CORE Gi1/0/1
 switchport mode trunk
!
interface GigabitEthernet0/10
 description POS register 1
 switchport mode access
 switchport access vlan 10
!
interface GigabitEthernet0/20
 description guest laptop
 switchport mode access
 switchport access vlan 40
!
interface Vlan10
 ip address 10.16.10.1 255.255.255.0
!
interface Vlan40
 ip address 10.16.40.1 255.255.255.0
!
end
"""
    pos = host_config("POS-01", "10.16.10.41/24", "10.16.10.1")
    guest = host_config("GUEST-LAP", "10.16.40.50/24", "10.16.40.1")
    stranger = host_config("FILE-01", "10.16.30.50/24", "10.16.30.1")
    found = infer(
        {
            "ACC-SALES": (switch, "CORE GigabitEthernet1/0/1 120 S I GigabitEthernet0/1"),
            "POS-01": (pos, ""),
            "GUEST-LAP": (guest, ""),
            "FILE-01": (stranger, ""),
        }
    )
    keys = {(item.a_device, item.a_interface, item.b_device, item.b_interface) for item in found.links}
    assert ("POS-01", "Ethernet0", "ACC-SALES", "GigabitEthernet0/10") in keys or (
        "ACC-SALES",
        "GigabitEthernet0/10",
        "POS-01",
        "Ethernet0",
    ) in keys
    assert not any("GUEST-LAP" in item.a_device or "GUEST-LAP" in item.b_device for item in found.links)
    assert not any("FILE-01" in item.a_device or "FILE-01" in item.b_device for item in found.links)
    pos_link = next(item for item in found.links if "POS-01" in {item.a_device, item.b_device})
    assert "host" in pos_link.source
    assert "VLAN 10" in pos_link.reason


def test_device_add_posts_config_and_load_help_documents_a_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemExit) as device_help:
        main(["device", "add", "--help"])
    assert device_help.value.code == 0
    device = capsys.readouterr().out
    assert "--role" in device and "--config" in device and "--neighbors" in device
    with pytest.raises(SystemExit) as load_help:
        main(["load", "--help"])
    assert load_help.value.code == 0
    load = capsys.readouterr().out
    assert "topology.json" in load
    assert "customer pack" in load
    assert "link add" in load

    config = tmp_path / "R2.cfg"
    config.write_text("hostname R2\n!\nend\n", encoding="utf-8")
    neighbors = tmp_path / "R2.txt"
    neighbors.write_text("SW1 Gig 0/1 120 S I Gig 0/1\n", encoding="utf-8")
    seen: dict = {}

    def fake_request(base: str, method: str, path: str, body: dict | None = None) -> dict:
        seen["method"] = method
        seen["path"] = path
        seen["body"] = body
        return {"devices": [{"name": "R2", "role": "router"}]}

    monkeypatch.setattr("dryrun_lab.cli._request", fake_request)
    assert (
        main(
            [
                "device",
                "add",
                "R2",
                "--role",
                "router",
                "--config",
                str(config),
                "--neighbors",
                str(neighbors),
            ]
        )
        == 0
    )
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/devices"
    assert seen["body"]["role"] == "router"
    assert "hostname R2" in seen["body"]["config"]
    assert "SW1" in seen["body"]["neighborText"]
    assert capsys.readouterr().out.strip() == "added router R2"


def test_revision_increments_and_is_in_the_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store(tmp_path / "lab.json")
    assert store.revision == 0
    store.lab.name = "pack"
    store.save()
    assert store.revision == 1
    store.save()
    assert store.revision == 2
    from dryrun_lab import server

    monkeypatch.setattr(server, "_store", store)
    assert server.lab_revision() == {"revision": 2}
    assert server._payload()["revision"] == 2


def test_missing_asset_is_404_and_other_paths_stay_the_page() -> None:
    from fastapi import HTTPException
    from dryrun_lab.server import _static_response

    with pytest.raises(HTTPException) as caught:
        _static_response("assets/not-a-real-file-pr6.js")
    assert caught.value.status_code == 404
    page = _static_response("not-a-route")
    assert Path(page.path).name == "index.html"
    html = (ROOT / "src" / "dryrun_lab" / "static" / "index.html").read_text(encoding="utf-8")
    marker = 'src="/assets/'
    start = html.index(marker) + len('src="')
    src = html[start : html.index('"', start)].lstrip("/")
    asset = _static_response(src)
    assert Path(asset.path).name.startswith("index-")


def test_docs_cover_the_customer_pack_and_the_mask() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    skill = (ROOT / "bot" / "skills" / "getting-started" / "SKILL.md").read_text(encoding="utf-8")
    instructions = (ROOT / "bot" / "instructions.md").read_text(encoding="utf-8")
    for text in (readme, skill, instructions):
        assert "device add" in text
        assert "topology.json" in text
    assert "ip helper-address" in readme
    assert "ip helper-address" in skill
    assert "Mask secrets" in readme or "on by default" in readme
    assert "confirmed" in readme and "suggested" in readme
    assert "do not suggest host cables" in readme
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "/api/lab/revision" in (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    assert "Mask secrets" in app
    assert "Red: lines not simulated" in app
    assert "maskSecretsDefault" in app


def test_frontend_mask_and_cable_labels() -> None:
    for script in ("frontend/src/mask.test.ts", "frontend/src/cables.test.ts"):
        completed = subprocess.run(
            ["node", "--experimental-strip-types", str(ROOT / script)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr + completed.stdout


def test_built_page_includes_the_qc_copy() -> None:
    html = (ROOT / "src" / "dryrun_lab" / "static" / "index.html").read_text(encoding="utf-8")
    marker = 'src="/assets/'
    start = html.index(marker) + len('src="')
    src = html[start : html.index('"', start)].lstrip("/")
    bundle = (ROOT / "src" / "dryrun_lab" / "static" / src).read_text(encoding="utf-8")
    for phrase in (
        "Mask secrets",
        "Red: lines not simulated",
        "Solid green: confirmed",
        "/api/lab/revision",
        "CDP does not suggest a host cable",
    ):
        assert phrase in bundle, phrase

