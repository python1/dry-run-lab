"""Config-mode prompt, computed tags, and refused commands. No live lab."""

import uuid

import pytest

from dryrun_lab.engine import Engine
from dryrun_lab.store import Device, Lab


def _engine(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("DRYRUN_HOME", str(tmp_path))
    return Engine(network=f"dryrun-test-{uuid.uuid4().hex}")


def _lab() -> Lab:
    lab = Lab()
    lab.devices.append(
        Device(
            name="R1",
            role="router",
            config=(
                "hostname R1\n!\n"
                "interface GigabitEthernet0/0\n"
                " ip address 10.1.1.1 255.255.255.0\n!\n"
                "end\n"
            ),
        )
    )
    return lab


def test_config_banner_prompt_and_submodes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = _lab()
    entered = engine.show_result(lab, "R1", "configure terminal")
    assert entered.prompt == "R1(config)#"
    assert entered.ok
    assert "End with CNTL/Z." in entered.text
    assert "[computed]" not in entered.text
    assert entered.text.startswith("R1# configure terminal\n")

    interface = engine.show_result(lab, "R1", "interface GigabitEthernet0/0")
    assert interface.prompt == "R1(config-if)#"
    assert interface.ok
    assert "[computed]" not in interface.text
    assert interface.text.startswith("R1(config)# interface GigabitEthernet0/0\n")

    assert engine.show_result(lab, "R1", "exit").prompt == "R1(config)#"
    extended = engine.show_result(lab, "R1", "ip access-list extended GUEST-IN")
    assert extended.prompt == "R1(config-ext-nacl)#"
    assert "[computed]" not in extended.text

    assert engine.show_result(lab, "R1", "exit").prompt == "R1(config)#"
    standard = engine.show_result(lab, "R1", "ip access-list standard STD")
    assert standard.prompt == "R1(config-std-nacl)#"
    assert "[computed]" not in standard.text

    assert engine.show_result(lab, "R1", "exit").prompt == "R1(config)#"
    vlan = engine.show_result(lab, "R1", "vlan 40")
    assert vlan.prompt == "R1(config-vlan)#"
    assert "[computed]" not in vlan.text

    assert engine.show_result(lab, "R1", "exit").prompt == "R1(config)#"
    router = engine.show_result(lab, "R1", "router ospf 1")
    assert router.prompt == "R1(config-router)#"
    assert "[computed]" not in router.text


def test_show_stays_tagged_and_an_empty_end_does_not(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = _lab()
    running = engine.show_result(lab, "R1", "show running-config")
    assert running.ok
    assert running.prompt == "R1#"
    assert "[computed]" in running.text

    engine.show_result(lab, "R1", "configure terminal")
    ended = engine.show_result(lab, "R1", "end")
    assert ended.prompt == "R1#"
    assert "No configuration changes." in ended.text
    assert "[computed]" not in ended.text


def test_end_tags_a_recompute(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = _lab()
    engine.show_result(lab, "R1", "configure terminal")
    engine.show_result(lab, "R1", "interface GigabitEthernet0/1")

    def fake_apply(lab: Lab, device: Device, lines: list[str]) -> str:
        return "Recomputed.\n  route added 10.9.9.0/24\n"

    monkeypatch.setattr(engine, "_apply", fake_apply)
    ended = engine.show_result(lab, "R1", "end")
    assert ended.prompt == "R1#"
    assert ended.ok
    assert "[computed]" in ended.text
    assert "route added 10.9.9.0/24" in ended.text


def test_abort_discards_the_draft(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = _lab()
    engine.show_result(lab, "R1", "configure terminal")
    engine.show_result(lab, "R1", "interface GigabitEthernet0/1")
    aborted = engine.show_result(lab, "R1", "abort")
    assert aborted.prompt == "R1#"
    assert aborted.ok
    assert "[computed]" not in aborted.text
    assert "Configuration aborted. Nothing was applied." in aborted.text
    running = engine.show_result(lab, "R1", "show running-config")
    assert "GigabitEthernet0/1" not in running.text
    assert running.prompt == "R1#"


def test_unknown_commands_and_pipes_are_not_ok(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = _lab()
    unknown = engine.show_result(lab, "R1", "frobnicate")
    assert unknown.ok is False
    assert unknown.prompt == "R1#"
    assert "Unrecognized command" in unknown.text
    assert "[computed]" in unknown.text

    piped = engine.show_result(lab, "R1", "show ip route | include 10")
    assert piped.ok is False
    assert "Pipes are not simulated" in piped.text

    engine.show_result(lab, "R1", "configure terminal")
    inside = engine.show_result(lab, "R1", "interface GigabitEthernet0/0 | include ip")
    assert inside.ok is False
    assert inside.prompt == "R1(config)#"
    assert "Pipes are not simulated" in inside.text
    following = engine.show_result(lab, "R1", "interface GigabitEthernet0/0")
    assert following.prompt == "R1(config-if)#"
    assert following.ok


def test_revert_with_nothing_saved_stays_ok(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = _lab()
    reverted = engine.show_result(lab, "R1", "revert")
    assert reverted.ok
    assert reverted.prompt == "R1#"
    assert "[computed]" in reverted.text
    assert "Nothing to revert on this device." in reverted.text
