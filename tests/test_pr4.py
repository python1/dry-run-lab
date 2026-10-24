"""Global prompt notes, host version notes, cable summaries, and line identity."""

from __future__ import annotations

import socket
import uuid
from pathlib import Path

import pytest

from dryrun_lab.acls import parse_acls, shadow_sentence
from dryrun_lab.cli import _print_extra_notice
from dryrun_lab.configedit import apply_config_lines
from dryrun_lab.engine import Engine, _unreachable_warning, _with_local_warnings
from dryrun_lab.examples import load_office_lab
from dryrun_lab.ioscheck import (
    KEPT_NOTE,
    VERSION_NOTE,
    invalid_input,
    kept_note,
    version_note,
)
from dryrun_lab.probes import probes_for_interfaces
from dryrun_lab.showfmt import _diff_warnings, show_running_config
from dryrun_lab.store import Device, Lab, add_user_link, cable_change_headline, dismiss_link, public_lab

ROOT = Path(__file__).resolve().parents[1]


def _engine(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("DRYRUN_HOME", str(tmp_path))
    return Engine(network=f"dryrun-test-{uuid.uuid4().hex}")


def _router() -> Lab:
    return Lab(devices=[Device(name="R1", role="router", config="hostname R1\n!\nend\n")])


def test_global_unmodeled_lines_warn_and_junk_is_rejected(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = _router()
    entered = engine.show_result(lab, "R1", "configure terminal")
    assert entered.ok
    kept = engine.show_result(lab, "R1", "spanning-tree mode rapid-pvst")
    assert kept.ok
    assert KEPT_NOTE.strip() in kept.text
    assert "spanning-tree mode rapid-pvst" in engine._drafts["r1"]
    negated = engine.show_result(lab, "R1", "no spanning-tree portfast")
    assert negated.ok
    assert KEPT_NOTE.strip() in negated.text
    assert "no spanning-tree portfast" in engine._drafts["r1"]
    quiet = engine.show_result(lab, "R1", "logging host 10.1.1.1")
    assert quiet.ok
    assert "Not simulated" not in quiet.text
    assert "Invalid input" not in quiet.text
    assert "logging host 10.1.1.1" in engine._drafts["r1"]
    version = engine.show_result(lab, "R1", "version 17.9")
    assert version.ok
    assert "Not simulated" not in version.text
    assert "Invalid input" not in version.text
    hostname = engine.show_result(lab, "R1", "hostname R1")
    assert "Not simulated" not in hostname.text
    junk = engine.show_result(lab, "R1", "frobnicate")
    assert junk.ok is False
    assert "Invalid input detected" in junk.text
    assert not any("frobnicate" in line for line in engine._drafts["r1"])
    miss = engine.show_result(lab, "R1", "spanningtree mode rapid-pvst")
    assert miss.ok is False
    assert "Invalid input detected" in miss.text
    engine.show_result(lab, "R1", "interface GigabitEthernet0/1")
    inside = engine.show_result(lab, "R1", "spanning-tree portfast")
    assert inside.ok
    assert "Not simulated" not in inside.text
    assert "spanning-tree portfast" in engine._drafts["r1"]
    assert kept_note([], "logging host 10.1.1.1") is None
    assert kept_note([], "frobnicate") is None
    assert invalid_input([], "frobnicate")


def test_version_note_is_only_for_ios_devices() -> None:
    host = (
        "hostname PC1\n!\ninterface Ethernet0\n"
        " ip address 10.1.1.50 255.255.255.0\n!\n"
        "ip default-gateway 10.1.1.1\n!\nend\n"
    )
    router = "hostname R1\n!\nend\n"
    switch = "hostname SW1\n!\nend\n"
    assert version_note(host) == VERSION_NOTE
    assert version_note(host, role="host") is None
    assert version_note(router, role="router") == VERSION_NOTE
    assert version_note(switch, role="switch") == VERSION_NOTE
    assert version_note("version 17.9\n" + router, role="router") is None
    assert VERSION_NOTE not in show_running_config(host, [], role="host")
    assert VERSION_NOTE in show_running_config(router, [], role="router")
    payload = public_lab(
        Lab(
            devices=[
                Device(name="PC1", role="host", config=host),
                Device(name="R1", role="router", config=router),
                Device(name="SW1", role="switch", config=switch),
            ]
        )
    )
    notes = {device["name"]: device["versionNote"] for device in payload["devices"]}
    assert notes == {"PC1": "", "R1": VERSION_NOTE, "SW1": VERSION_NOTE}


def _portfast(name: str, ports: list[int]) -> str:
    lines = [f"hostname {name}", "!"]
    for port in ports:
        lines.extend(
            [
                f"interface GigabitEthernet0/{port}",
                " switchport mode access",
                " spanning-tree portfast",
                "!",
            ]
        )
    lines.append("end")
    return "\n".join(lines) + "\n"


def test_identical_lines_are_flagged_on_every_interface_and_device() -> None:
    swa = _portfast("SWA", [10, 11, 20])
    swb = _portfast("SWB", [10, 11])
    seeded = {
        "file": "configs/SWA.cfg",
        "line": 5,
        "text": "spanning-tree portfast",
        "detail": "not simulated",
        "kind": "missed",
        "device": "SWA",
    }
    rows = _with_local_warnings([seeded], {"SWA": swa, "SWB": swb})
    portfast = [row for row in rows if row["text"] == "spanning-tree portfast"]
    swa_lines = sorted(row["line"] for row in portfast if row["device"] == "SWA")
    swb_lines = sorted(row["line"] for row in portfast if row["device"] == "SWB")
    assert swa_lines == [5, 9, 13]
    assert swb_lines == [5, 9]
    assert {row["file"] for row in portfast} == {"configs/SWA.cfg", "configs/SWB.cfg"}
    assert sum(1 for row in portfast if row["device"] == "SWA" and row["line"] == 5) == 1
    office_sw2 = (ROOT / "examples" / "office-lab" / "configs" / "SW2.cfg").read_text(encoding="utf-8")
    office_sw3 = (ROOT / "examples" / "office-lab" / "configs" / "SW3.cfg").read_text(encoding="utf-8")
    office = _with_local_warnings(
        [
            {
                "file": "configs/SW2.cfg",
                "line": 24,
                "text": "spanning-tree portfast",
                "detail": "not simulated",
                "kind": "missed",
                "device": "SW2",
            }
        ],
        {"SW2": office_sw2, "SW3": office_sw3},
    )
    office_hits = [row for row in office if str(row.get("text") or "").strip() == "spanning-tree portfast"]
    assert sorted(row["line"] for row in office_hits if row["device"] == "SW2") == [24, 31, 38]
    assert sorted(row["line"] for row in office_hits if row["device"] == "SW3") == [24, 31]
    assert {row["file"] for row in office_hits} == {"configs/SW2.cfg", "configs/SW3.cfg"}


def test_warning_diff_keeps_repeated_lines() -> None:
    def row(device: str, line: int) -> dict:
        return {
            "device": device,
            "file": f"configs/{device}.cfg",
            "line": line,
            "text": "spanning-tree portfast",
            "detail": "not simulated",
            "kind": "missed",
        }

    diff = "\n".join(
        _diff_warnings(
            [],
            [row("SW2", 24), row("SW2", 31), row("SW2", 38), row("SW3", 24), row("SW3", 31)],
        )
    )
    assert diff.count("spanning-tree portfast") == 5
    assert "SW2" in diff and "SW3" in diff


def test_duplicate_ace_text_is_removed_only_by_sequence() -> None:
    deny = "deny ip 10.1.1.0 0.0.0.255 10.2.2.0 0.0.0.255"
    config = (
        "hostname R1\n!\nip access-list extended GUEST-IN\n"
        f" {deny}\n {deny}\n permit ip any any\n!\nend\n"
    )
    ambiguous = apply_config_lines(
        config,
        ["ip access-list extended GUEST-IN", f"no {deny}", "end"],
    )
    kept = [ace.text for ace in parse_acls(ambiguous)[0].aces]
    assert kept.count(deny) == 2
    removed = apply_config_lines(
        config,
        ["ip access-list extended GUEST-IN", f"no 10 {deny}", "end"],
    )
    left = [(ace.seq, ace.text) for ace in parse_acls(removed)[0].aces if deny in ace.text]
    assert left == [(20, deny)]
    tripled = (
        "hostname R1\n!\nip access-list extended GUEST-IN\n"
        f" {deny}\n {deny}\n {deny}\n!\nend\n"
    )
    acl = parse_acls(tripled)[0]
    later = next(ace for ace in acl.aces if ace.seq == 30)
    unnamed = shadow_sentence(acl, later, [deny])
    assert unnamed == "Line at sequence 30; it will never match."
    named = shadow_sentence(acl, later, [f"10 {deny}"])
    assert "after sequence 10" in named
    covered = (
        "hostname R1\n!\nip access-list extended GUEST-IN\n"
        " permit ip any any\n permit ip any any\n deny ip 10.9.9.0 0.0.0.255 any\n!\nend\n"
    )
    wide = parse_acls(covered)[0]
    shadowed = next(ace for ace in wide.aces if ace.seq == 30)
    assert shadow_sentence(wide, shadowed, []) == "Line at sequence 30; it will never match."
    one_cover = (
        "hostname R1\n!\nip access-list extended GUEST-IN\n"
        " permit ip any any\n deny ip 10.9.9.0 0.0.0.255 any\n!\nend\n"
    )
    single = parse_acls(one_cover)[0]
    denied = next(ace for ace in single.aces if ace.seq == 20)
    assert "after sequence 10 permit ip any any" in shadow_sentence(single, denied, [])
    warning = _unreachable_warning("R1", acl, later, [f"10 {deny}"])
    assert warning["file"] == "configs/R1.cfg"


def test_cli_keeps_the_cable_id_and_prints_the_summary(capsys: pytest.CaptureFixture[str]) -> None:
    _print_extra_notice({"notice": "Cabled R1 GigabitEthernet0/0 - R2 GigabitEthernet0/0.\n\nRoutes\n"})
    assert "Cabled R1" in capsys.readouterr().out
    _print_extra_notice({})
    assert capsys.readouterr().out == ""
    assert cable_change_headline("Removed", "R1", "Gi0/0", "R2", "Gi0/0") == "Removed R1 Gi0/0 - R2 Gi0/0."


def test_page_shows_a_pending_cable_state_and_keys_warnings_by_position() -> None:
    frontend = ROOT / "frontend" / "src"
    app = (frontend / "App.tsx").read_text(encoding="utf-8")
    api = (frontend / "api.ts").read_text(encoding="utf-8")
    topology = (frontend / "components" / "Topology.tsx").read_text(encoding="utf-8")
    for label in ("Confirming cable…", "Rejecting cable…", "Adding cable…", "Removing cable…"):
        assert label in app
    assert "busyRef.current" in app
    assert "deleteLink" in api
    assert "onRemove" in topology
    assert "strokeWidth={14}" in topology
    assert "warningKey" in app
    assert "${row.text}-${index}" not in app


def _engine_up() -> bool:
    probe = socket.socket()
    try:
        return probe.connect_ex(("127.0.0.1", 9996)) == 0
    finally:
        probe.close()


@pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")
def test_drawn_and_removed_cables_print_the_recompute_summary() -> None:
    lab = Lab(
        devices=[
            Device(
                name="R1",
                role="router",
                config=(
                    "hostname R1\ninterface GigabitEthernet0/0\n"
                    " ip address 10.1.1.1 255.255.255.0\n no shutdown\n"
                ),
            ),
            Device(
                name="R2",
                role="router",
                config=(
                    "hostname R2\ninterface GigabitEthernet0/0\n"
                    " ip address 10.1.1.2 255.255.255.0\n no shutdown\n"
                ),
            ),
        ]
    )
    engine = Engine(network=f"dryrun-test-{uuid.uuid4().hex[:10]}")
    try:
        engine.recompute(lab)
        assert lab.engine_error is None, lab.engine_error
        headline = cable_change_headline(
            "Cabled", "R1", "GigabitEthernet0/0", "R2", "GigabitEthernet0/0"
        )
        extra = probes_for_interfaces(lab, "R1", "GigabitEthernet0/0")
        extra += probes_for_interfaces(lab, "R2", "GigabitEthernet0/0")
        summary = engine.summarize_mutation(
            lab,
            lambda: add_user_link(lab, "R1", "Gi0/0", "R2", "Gi0/0"),
            headline,
            extra,
        )
        assert summary.startswith("Cabled R1 GigabitEthernet0/0 - R2 GigabitEthernet0/0.")
        assert "\nRoutes\n" in summary
        assert "\nWarnings\n" in summary
        assert "\nReachability\n" in summary
        link = lab.links[-1]
        removed = engine.summarize_mutation(
            lab,
            lambda: dismiss_link(lab, link.id),
            cable_change_headline(
                "Removed", link.a_device, link.a_interface, link.b_device, link.b_interface
            ),
        )
        assert removed.startswith("Removed ")
        assert "\nRoutes\n" in removed
        assert "\nWarnings\n" in removed
        assert "\nReachability\n" in removed
        assert engine.network.startswith("dryrun-test-")
        assert engine.network != "dryrun"
    finally:
        engine.close()


@pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")
def test_office_portfast_lines_are_each_flagged() -> None:
    lab = load_office_lab()
    engine = Engine(network=f"dryrun-test-{uuid.uuid4().hex[:10]}")
    try:
        engine.recompute(lab)
        assert lab.engine_error is None, lab.engine_error

        def lines_for(device: str) -> list[int]:
            found = []
            for row in lab.warnings:
                if row.get("device") != device:
                    continue
                if str(row.get("text") or "").strip().lower() != "spanning-tree portfast":
                    continue
                found.append(row.get("line"))
                file_name = str(row.get("file") or "").replace("\\", "/")
                assert file_name.endswith(f"configs/{device}.cfg")
            return sorted(found)

        assert lines_for("SW2") == [24, 31, 38]
        assert lines_for("SW3") == [24, 31]
        assert lines_for("R1") == []
        assert engine.network != "dryrun"
    finally:
        engine.close()
