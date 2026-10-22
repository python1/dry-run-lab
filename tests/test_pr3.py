"""Checks for rejected edits, reachability, versions, and computed show output."""

import asyncio
import hashlib
import json
import socket
import uuid

import pytest

from dryrun_lab.configedit import apply_config_lines
from dryrun_lab.engine import Engine, EngineUnavailable, _with_local_warnings
from dryrun_lab.examples import load_office_lab
from dryrun_lab.ioscheck import (
    VERSION_NOTE,
    display_config,
    fold_line,
    invalid_input,
    is_harmless,
    sequences_nvgen,
    unmodeled_lines,
    version_note,
)
from dryrun_lab.probes import probes_for_commands
from dryrun_lab.showfmt import command_disposition, explain_disposition, show_running_config
from dryrun_lab.store import Device, Lab, Store, add_user_link, confirm_link, dismiss_link, place_host, public_lab


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _engine(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("DRYRUN_HOME", str(tmp_path))
    return Engine(network=f"dryrun-test-{uuid.uuid4().hex}")


def _router(config: str | None = None) -> Lab:
    lab = Lab()
    lab.devices.append(
        Device(
            name="R1",
            role="router",
            config=config
            or (
                "version 17.9\n"
                "hostname R1\n"
                "!\n"
                "ip access-list extended GUEST-IN\n"
                " deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255\n"
                " permit ip any any\n"
                "!\n"
                "end\n"
            ),
        )
    )
    return lab


def _quiet(engine: Engine, monkeypatch: pytest.MonkeyPatch, recompute=None) -> None:
    monkeypatch.setattr(engine, "_ensure_ready", lambda lab: None)
    monkeypatch.setattr("dryrun_lab.engine.probes_for_lab", lambda lab: [])
    monkeypatch.setattr("dryrun_lab.engine.probes_for_acl", lambda *args, **kwargs: [])
    monkeypatch.setattr("dryrun_lab.engine.probes_for_commands", lambda *args, **kwargs: [])
    monkeypatch.setattr(engine, "recompute", recompute or (lambda lab: None))


def test_bad_lines_are_rejected_and_the_saved_file_stays(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = _router()
    device = lab.device("R1")
    assert device is not None
    original = device.config
    store = Store(tmp_path / "lab.json")
    store.lab = lab
    store.save()
    before = (tmp_path / "lab.json").read_bytes()
    engine.show_result(lab, "R1", "configure terminal")
    lines = [
        "25 deny ip 10.30.30.0 0.0.0.255 10.10.10.300 0.0.0.255",
        "ip access-list extended GUEST-INno 15",
        "40 permt ip any any",
    ]
    for line in lines:
        result = engine.show_result(lab, "R1", line)
        assert result.ok is False
        assert result.changed is False
        assert "% Invalid input detected at '^' marker." in result.text
        assert result.prompt == "R1(config)#"
    ended = engine.show_result(lab, "R1", "end")
    assert ended.changed is False
    assert device.config == original
    assert _sha(device.config) == _sha(original)
    assert "GUEST-INno" not in device.config
    assert "10.10.10.300" not in device.config
    assert "permt" not in device.config
    assert (tmp_path / "lab.json").read_bytes() == before
    assert not (tmp_path / "lab.json.tmp").exists()


def test_acl_mode_rejects_a_bad_address_and_a_typo(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = _router()
    device = lab.device("R1")
    assert device is not None
    original = device.config
    engine.show_result(lab, "R1", "configure terminal")
    engine.show_result(lab, "R1", "ip access-list extended GUEST-IN")
    bad_ip = engine.show_result(
        lab,
        "R1",
        "25 deny ip 10.30.30.0 0.0.0.255 10.10.10.300 0.0.0.255",
    )
    typo = engine.show_result(lab, "R1", "40 permt ip any any")
    assert bad_ip.ok is False and "10.10.10.300" in bad_ip.text
    assert "Invalid input detected" in bad_ip.text
    assert typo.ok is False and "permt" in typo.text
    caret = bad_ip.text.splitlines()
    mark = next(index for index, line in enumerate(caret) if "^" in line and "300" not in line)
    assert caret[mark - 1].index("300") == caret[mark].index("^")
    ended = engine.show_result(lab, "R1", "end")
    assert ended.changed is False
    assert device.config == original


def test_exception_during_apply_leaves_the_file_byte_identical(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path, monkeypatch)

    def explode(*_args, **_kwargs):
        raise RuntimeError("probe failed")

    def forbid(_lab):
        raise AssertionError("recompute ran after a failed probe")

    _quiet(engine, monkeypatch, recompute=forbid)
    monkeypatch.setattr("dryrun_lab.engine.probes_for_acl", explode)
    lab = _router()
    device = lab.device("R1")
    assert device is not None
    original = device.config
    store = Store(tmp_path / "lab.json")
    store.lab = lab
    store.save()
    before = (tmp_path / "lab.json").read_bytes()
    result = engine.show_result(
        lab,
        "R1",
        "configure terminal\nip access-list extended GUEST-IN\n15 permit ip host 10.1.1.1 any\nend",
    )
    assert result.ok is False
    assert result.changed is False
    assert "Change was not kept" in result.text
    assert device.config == original
    assert _sha(device.config) == _sha(original)
    assert device.config_history == []
    assert (tmp_path / "lab.json").read_bytes() == before


def test_revert_restores_the_config_bytes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    _quiet(engine, monkeypatch)
    lab = _router()
    device = lab.device("R1")
    assert device is not None
    original = device.config
    store = Store(tmp_path / "lab.json")
    store.lab = lab
    store.save()
    edited = engine.show_result(
        lab,
        "R1",
        "configure terminal\ninterface GigabitEthernet0/0\n description Kept\nend",
    )
    assert edited.ok
    assert edited.changed
    assert "description Kept" in device.config
    assert device.config != original
    store.save()
    reverted = engine.show_result(lab, "R1", "revert")
    assert "Reverted one edit. Recomputed." in reverted.text
    assert device.config == original
    assert _sha(device.config) == _sha(original)
    store.save()
    saved = json.loads((tmp_path / "lab.json").read_text(encoding="utf-8"))
    assert saved["devices"][0]["config"] == original


def test_errors_are_json(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("DRYRUN_HOME", str(tmp_path))
    from dryrun_lab.server import _json_error

    failed = asyncio.run(_json_error(None, RuntimeError("boom")))  # type: ignore[arg-type]
    assert failed.status_code == 500
    body = json.loads(failed.body)
    assert body == {"detail": "The change was not saved."}
    assert b"Internal Server Error" not in failed.body
    down = asyncio.run(_json_error(None, EngineUnavailable("engine down")))  # type: ignore[arg-type]
    assert down.status_code == 503
    assert json.loads(down.body)["detail"] == "engine down"


def test_keywords_fold_and_names_keep_their_case() -> None:
    updated = apply_config_lines(
        "hostname R1\n!\nend\n",
        [
            "IP ACCESS-LIST EXTENDED Guest-In",
            "15 PERMIT IP ANY ANY",
            "exit",
        ],
    )
    assert "ip access-list extended Guest-In" in updated
    assert "15 permit ip any any" in updated
    assert "PERMIT" not in updated
    assert "GUEST-IN" not in updated
    assert fold_line("hostname Core-R1") == "hostname Core-R1"


def test_version_controls_acl_sequence_display() -> None:
    body = (
        "hostname R1\n"
        "!\n"
        "ip access-list extended IN\n"
        " remark guests\n"
        " deny ip any any\n"
        " 25 permit ip any any\n"
        "!\n"
        "end\n"
    )
    old = "version 16.11\n" + body
    current = "version 16.12\n" + body
    newer = "version 17.9\n" + body
    assert sequences_nvgen(old) is False
    assert sequences_nvgen(current) is True
    assert sequences_nvgen(newer) is True
    assert sequences_nvgen(body) is True
    old_view = display_config(old)
    assert "remark guests" in old_view
    assert "deny ip any any" in old_view
    assert "permit ip any any" in old_view
    assert " 10 remark" not in old_view
    assert " 20 deny" not in old_view
    assert " 25 permit" not in old_view
    for source in (current, newer, body):
        view = display_config(source)
        assert " 10 remark guests" in view
        assert " 20 deny ip any any" in view
        assert " 25 permit ip any any" in view
    assert version_note(body) == VERSION_NOTE
    assert version_note(current) is None
    shown = show_running_config(body, [])
    assert VERSION_NOTE in shown
    assert " 10 remark guests" in shown
    lab = Lab(devices=[Device(name="R1", role="router", config=body)])
    payload = public_lab(lab)
    assert payload["devices"][0]["versionNote"] == VERSION_NOTE
    assert " 10 remark guests" in payload["devices"][0]["config"]
    assert " 10 remark" not in lab.devices[0].config


def test_unmodeled_forwarding_lines_are_flagged_and_logging_is_not() -> None:
    config = "hostname R1\nspanning-tree mode rapid-pvst\nlogging host 10.1.1.1\n"
    flagged = unmodeled_lines(config)
    assert any(text == "spanning-tree mode rapid-pvst" for _line, text in flagged)
    assert is_harmless("logging host 10.1.1.1")
    assert not any("logging" in text for _line, text in flagged)
    rows = _with_local_warnings(
        [{"text": "logging host 10.1.1.1", "kind": "missed", "detail": "parse", "device": "R1"}],
        {"R1": config},
    )
    assert any(row["text"] == "spanning-tree mode rapid-pvst" and row["detail"] == "not simulated" for row in rows)
    assert any(row["kind"] == "missed" for row in rows)
    assert not any("logging" in str(row.get("text")) for row in rows)


def test_office_configs_pass_the_line_check() -> None:
    lab = load_office_lab()
    for device in lab.devices:
        draft: list[str] = []
        for line in device.config.splitlines():
            rejected = invalid_input(draft, line)
            assert rejected is None, (device.name, line, rejected)
            stripped = line.strip()
            if stripped and not stripped.startswith("!"):
                draft.append(fold_line(stripped))


def test_show_commands_that_are_not_modeled_say_so(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = _router("hostname R1\n!\nend\n")
    version = engine.show_result(lab, "R1", "show version")
    spanning = engine.show_result(lab, "R1", "show spanning-tree")
    garbage = engine.show_result(lab, "R1", "frobnicate")
    assert version.ok is False
    assert "not simulated in this version" in version.text.lower()
    assert "Unrecognized command" not in version.text
    assert spanning.ok is False
    assert "not simulated in this version" in spanning.text.lower()
    assert garbage.ok is False
    assert "Invalid input detected" in garbage.text
    assert command_disposition("show ip ospf neighbor") == "modeled"
    assert command_disposition("show version") == "unmodeled"
    assert command_disposition("frobnicate") == "invalid"


def test_reach_summary_uses_the_ping_sentence(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = _router("hostname R1\n!\nend\n")
    monkeypatch.setattr(
        engine,
        "_trace",
        lambda *_args, **_kwargs: {"ok": False, "disposition": "NO_ROUTE", "steps": [], "error": None},
    )
    from dryrun_lab.probes import Probe

    probe = Probe(device="R1", ingress=None, src="10.1.1.1", dst="10.9.9.9", note="vlan 50")
    summary = engine._reach_summary(lab, probe)
    sentence = explain_disposition({"disposition": "NO_ROUTE", "steps": []}, None, probe.dst)
    assert summary == f"NO_ROUTE — {sentence}"
    assert "No route" in summary
    info = explain_disposition({"disposition": "INSUFFICIENT_INFO", "steps": []}, None, probe.dst)
    assert "enough information" in info


def test_vlan_command_adds_a_probe_for_the_host_on_that_vlan() -> None:
    lab = Lab()
    lab.devices.append(
        Device(
            name="R1",
            role="router",
            config=(
                "hostname R1\n"
                "interface GigabitEthernet0/0.10\n"
                " encapsulation dot1q 10\n"
                " ip address 10.10.10.1 255.255.255.0\n"
                "interface GigabitEthernet0/0.50\n"
                " encapsulation dot1q 50\n"
                " ip address 10.50.50.1 255.255.255.0\n"
            ),
        )
    )
    lab.devices.append(
        Device(
            name="SW2",
            role="switch",
            config=(
                "hostname SW2\n"
                "interface GigabitEthernet0/12\n"
                " switchport mode access\n"
                " switchport access vlan 50\n"
            ),
        )
    )
    lab.devices.append(
        Device(
            name="PC50",
            role="host",
            config=(
                "hostname PC50\n"
                "interface Ethernet0\n"
                " ip address 10.50.50.50 255.255.255.0\n"
                "ip default-gateway 10.50.50.1\n"
            ),
        )
    )
    add_user_link(lab, "PC50", "Ethernet0", "SW2", "GigabitEthernet0/12")
    probes = probes_for_commands(lab, ["switchport trunk allowed vlan add 50"])
    labels = [probe.label() for probe in probes]
    assert any("PC50" in label and "10.10.10.1" in label for label in labels)
    assert probes_for_commands(lab, ["logging host 10.1.1.1"]) == []


def _engine_up() -> bool:
    probe = socket.socket()
    try:
        return probe.connect_ex(("127.0.0.1", 9996)) == 0
    finally:
        probe.close()


@pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")
def test_trunk_vlan_edit_reports_the_host_reachability_change() -> None:
    lab = load_office_lab()
    engine = Engine(network=f"dryrun-test-{uuid.uuid4().hex[:10]}")
    try:
        engine.recompute(lab)
        assert lab.engine_error is None, lab.engine_error
        _apply(
            engine,
            lab,
            "R1",
            [
                "interface GigabitEthernet0/0.50",
                "encapsulation dot1Q 50",
                "ip address 10.50.50.1 255.255.255.0",
                "no shutdown",
            ],
        )
        _apply(
            engine,
            lab,
            "SW2",
            [
                "vlan 50",
                "name LAB50",
                "interface GigabitEthernet0/1",
                "switchport trunk allowed vlan add 50",
                "interface GigabitEthernet0/12",
                "switchport mode access",
                "switchport access vlan 50",
                "no shutdown",
            ],
        )
        _apply(engine, lab, "SW1", ["vlan 50", "name LAB50"])
        x, y = place_host(lab)
        lab.devices.append(
            Device(
                name="PC50",
                role="host",
                x=x,
                y=y,
                config=(
                    "hostname PC50\n!\ninterface Ethernet0\n"
                    " ip address 10.50.50.50 255.255.255.0\n!\n"
                    "ip default-gateway 10.50.50.1\n!\nend\n"
                ),
            )
        )
        for left, right in (("R1", "SW1"), ("SW1", "SW2")):
            for link in lab.links:
                if {link.a_device, link.b_device} == {left, right}:
                    link.status = "confirmed"
        add_user_link(lab, "PC50", "Ethernet0", "SW2", "GigabitEthernet0/12")
        engine.recompute(lab)
        assert lab.engine_error is None, lab.engine_error
        blocked = engine.show(lab, "PC50", "ping 10.10.10.1")
        assert "100 percent" not in blocked
        summary = _apply(
            engine,
            lab,
            "SW1",
            [
                "interface GigabitEthernet1/0/1",
                "switchport trunk allowed vlan add 50",
                "interface GigabitEthernet1/0/2",
                "switchport trunk allowed vlan add 50",
            ],
        )
        reach = summary.split("Reachability", 1)[1]
        assert "PC50" in reach
        assert "10.10.10.1" in reach
        assert "(no reachability changes)" not in reach
        reached = engine.show(lab, "PC50", "ping 10.10.10.1")
        assert "100 percent" in reached
        assert engine.network.startswith("dryrun-test-")
        assert engine.network != "dryrun"
    finally:
        engine.close()


@pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")
def test_ospf_neighbors_and_cable_summary_are_computed() -> None:
    lab = load_office_lab()
    engine = Engine(network=f"dryrun-test-{uuid.uuid4().hex[:10]}")
    try:
        engine.recompute(lab)
        assert lab.engine_error is None, lab.engine_error
        neighbors = engine.show(lab, "R1", "show ip ospf neighbor")
        assert "Computed OSPF neighbors" in neighbors
        assert "10.255.1.1" in neighbors
        assert "10.50.0.2" in neighbors
        assert "FULL" in neighbors
        assert "Priority and dead time are not part of the computed session." in neighbors
        link = next(item for item in lab.links if item.status == "suggested")
        headline = (
            f"Confirmed {link.a_device} {link.a_interface} - "
            f"{link.b_device} {link.b_interface}."
        )
        summary = engine.summarize_mutation(lab, lambda: confirm_link(lab, link.id), headline)
        assert summary.startswith("Confirmed ")
        assert "\nRoutes\n" in summary
        assert "\nWarnings\n" in summary
        assert "\nReachability\n" in summary
        other = next(item for item in lab.links if item.status == "suggested")
        rejected = (
            f"Rejected {other.a_device} {other.a_interface} - "
            f"{other.b_device} {other.b_interface}."
        )
        dismissed = engine.summarize_mutation(lab, lambda: dismiss_link(lab, other.id), rejected)
        assert dismissed.startswith("Rejected ")
        assert "\nReachability\n" in dismissed
        assert engine.network != "dryrun"
    finally:
        engine.close()


def _apply(engine: Engine, lab, device: str, lines: list[str]) -> str:
    text = engine.show(lab, device, "\n".join(["configure terminal", *lines, "end"]))
    assert "Change was not kept" not in text
    return text
