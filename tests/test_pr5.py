"""Prompt matching, hostname identity, uncabled hosts, and the page bundle."""

from __future__ import annotations

import os
import socket
import subprocess
import uuid
from pathlib import Path

import pytest

from dryrun_lab.acls import parse_acls
from dryrun_lab.configedit import apply_config_lines, prompt_for
from dryrun_lab.engine import Engine
from dryrun_lab.examples import load_office_lab
from dryrun_lab.hosts import host_config
from dryrun_lab.ioscheck import (
    KEPT_NOTE,
    canonical_line,
    invalid_input,
    kept_note,
    unmodeled_lines,
)
from dryrun_lab.l2path import unattached_host
from dryrun_lab.probes import Probe
from dryrun_lab.showfmt import command_help, normalize_command, show_ip_route, show_vlan_brief
from dryrun_lab.store import Device, Lab

ROOT = Path(__file__).resolve().parents[1]


def _engine(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("DRYRUN_HOME", str(tmp_path))
    return Engine(network=f"dryrun-test-{uuid.uuid4().hex}")


def _engine_up() -> bool:
    probe = socket.socket()
    try:
        return probe.connect_ex(("127.0.0.1", 9996)) == 0
    finally:
        probe.close()


def test_interface_abbreviations_enter_interface_mode(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = Lab(
        devices=[
            Device(
                name="SW1",
                role="switch",
                config=(
                    "hostname SW1\n!\ninterface GigabitEthernet1/0/10\n"
                    " switchport mode access\n switchport access vlan 10\n!\nend\n"
                ),
            )
        ]
    )
    engine.show_result(lab, "SW1", "configure terminal")
    for typed in ("int gi1/0/10", "int Gi1/0/10", "in gi1/0/10"):
        engine._drafts.pop("sw1", None)
        engine.show_result(lab, "SW1", "configure terminal")
        entered = engine.show_result(lab, "SW1", typed)
        assert entered.ok, entered.text
        assert entered.prompt == "SW1(config-if)#"
        assert "Invalid input" not in entered.text
        engine.show_result(lab, "SW1", "abort")
    engine.show_result(lab, "SW1", "configure terminal")
    engine.show_result(lab, "SW1", "int gi1/0/10")
    moved = engine.show_result(lab, "SW1", "sw acc vlan 20")
    assert moved.ok
    assert "switchport access vlan 20" in engine._drafts["sw1"]
    word = engine.show_result(lab, "SW1", "switch access vlan 20")
    assert word.ok
    ended = engine.show_result(lab, "SW1", "end")
    assert ended.ok
    stored = lab.device("SW1").config
    assert stored.count("switchport access vlan 20") == 1
    assert "switchport access vlan 10" not in stored


def test_glued_lines_are_rejected_and_do_not_replace_a_good_line(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = Lab(
        devices=[
            Device(
                name="SW1",
                role="switch",
                config=(
                    "hostname SW1\n!\ninterface GigabitEthernet1/0/10\n"
                    " switchport mode access\n!\nend\n"
                ),
            )
        ]
    )
    original = lab.device("SW1").config
    engine.show_result(lab, "SW1", "configure terminal")
    engine.show_result(lab, "SW1", "interface GigabitEthernet1/0/10")
    glued = engine.show_result(lab, "SW1", "switchport mode access switchport access vlan 20")
    assert glued.ok is False
    assert "Invalid input" in glued.text
    assert glued.text.splitlines()[2].startswith(" " * glued.text.splitlines()[1].index("switchport", 1))
    assert "switchport mode access switchport" not in engine._drafts["sw1"]
    ended = engine.show_result(lab, "SW1", "end")
    assert "No configuration changes" in ended.text
    assert lab.device("SW1").config == original
    kept = apply_config_lines(
        original,
        ["interface GigabitEthernet1/0/10", "switchport mode access switchport access vlan 20", "end"],
    )
    assert " switchport mode access\n" in kept


def test_glued_acl_is_rejected_at_the_second_command(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    config = (
        "hostname R1\n!\nip access-list extended GUEST-IN\n"
        " permit ip any any\n!\nend\n"
    )
    lab = Lab(devices=[Device(name="R1", role="router", config=config)])
    engine.show_result(lab, "R1", "configure terminal")
    engine.show_result(lab, "R1", "ip access-list extended GUEST-IN")
    glued = engine.show_result(lab, "R1", "15 deny tcp any any eq www 16 deny ip any any")
    assert glued.ok is False
    rows = glued.text.splitlines()
    command = rows[1]
    caret = rows[2]
    assert command.index("16") == caret.index("^")
    other = engine.show_result(lab, "R1", "permit ip any any deny ip any any")
    assert other.ok is False
    assert other.text.splitlines()[1].index("deny") == other.text.splitlines()[2].index("^")
    assert lab.device("R1").config == config


def test_typos_are_rejected_in_interface_mode(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = Lab(devices=[Device(name="R1", role="router", config="hostname R1\n!\nend\n")])
    engine.show_result(lab, "R1", "configure terminal")
    engine.show_result(lab, "R1", "interface GigabitEthernet0/1")
    for line in (
        "ip adress 192.0.2.5 255.255.255.252",
        "shutdwon",
        "descriptoin typo",
        "shutdown no shutdown",
        "switchport acess vlan 20",
    ):
        result = engine.show_result(lab, "R1", line)
        assert result.ok is False, line
        assert result.prompt == "R1(config-if)#"
        assert line not in "\n".join(engine._drafts["r1"])


def test_ip_rout_is_the_route_command() -> None:
    line = "ip rout 10.9.9.0 255.255.255.0 192.0.2.2"
    assert invalid_input([], line) is None
    assert canonical_line([], line) == "ip route 10.9.9.0 255.255.255.0 192.0.2.2"
    assert kept_note([], line) is None
    updated = apply_config_lines("hostname R1\n!\nend\n", [line, "end"])
    assert "ip route 10.9.9.0 255.255.255.0 192.0.2.2" in updated


def test_show_abbreviations_run_the_command() -> None:
    assert normalize_command("sh vl br") == "vlan"
    assert normalize_command("sh access-l") == "acl"
    assert normalize_command("sh ip ospf nei") == "ospf-neighbor"
    assert normalize_command("sh ip int br") == "interfaces"
    assert normalize_command("show version") is None


def test_hostname_replaces_the_line_and_the_prompt(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    lab = Lab(devices=[Device(name="R1", role="router", config="hostname R1\n!\nend\n")])
    engine.show_result(lab, "R1", "configure terminal")
    renamed = engine.show_result(lab, "R1", "hostname R1-QC")
    assert renamed.ok
    assert renamed.prompt == "R1-QC(config)#"
    assert engine._drafts["r1"] == ["hostname R1-QC"]


def test_duplicate_acl_sequence_and_duplicate_text(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = (
        "hostname R1\n!\nip access-list extended GUEST-IN\n"
        " deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255\n"
        " permit ip any any\n!\nend\n"
    )
    engine = _engine(tmp_path, monkeypatch)
    lab = Lab(devices=[Device(name="R1", role="router", config=config)])
    engine.show_result(lab, "R1", "configure terminal")
    engine.show_result(lab, "R1", "ip access-list extended GUEST-IN")
    duplicate = engine.show_result(
        lab,
        "R1",
        "10 deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255",
    )
    assert duplicate.ok is False
    assert "Duplicate sequence number" in duplicate.text
    same = engine.show_result(lab, "R1", "deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255")
    assert same.ok
    ended = engine.show_result(lab, "R1", "end")
    assert "No configuration changes" in ended.text
    assert [ace.seq for ace in parse_acls(lab.device("R1").config)[0].aces] == [10, 20]
    fresh = apply_config_lines(
        config,
        ["ip access-list extended GUEST-IN", "40 deny ip 1.1.1.1 0.0.0.0 2.2.2.2 0.0.0.0", "end"],
    )
    assert [ace.seq for ace in parse_acls(fresh)[0].aces] == [10, 20, 40]


def test_merged_interface_lines_are_indented() -> None:
    updated = apply_config_lines(
        "interface GigabitEthernet0/1\n description old\n!\nend\n",
        ["interface GigabitEthernet0/1", "description EDIT2", "end"],
    )
    assert "\n description EDIT2\n" in updated
    assert "\ndescription EDIT2\n" not in updated


def test_nat_is_in_the_warning_list() -> None:
    config = "hostname R1\nip nat inside source list 1 interface GigabitEthernet0/1 overload\n"
    assert kept_note([], config.splitlines()[1]) == KEPT_NOTE
    assert any("ip nat" in text for _line, text in unmodeled_lines(config))


def test_hosts_do_not_get_switch_show_commands() -> None:
    host = command_help("host")
    router = command_help("router")
    assert "show vlan brief" not in host
    assert "show interfaces trunk" not in host
    assert "show vlan brief" in router
    assert "show ip route" in host


def test_uncabled_host_is_not_attached() -> None:
    lab = load_office_lab()
    lab.devices.append(
        Device(
            name="PCX",
            role="host",
            config=host_config("PCX", "10.10.10.50/24", "10.10.10.1"),
        )
    )
    reason = unattached_host(lab, "PCX")
    assert reason is not None
    assert "no confirmed link" in reason
    engine = Engine(network=f"dryrun-test-{uuid.uuid4().hex}")
    summary = engine._reach_summary(
        lab,
        Probe(device="PCX", ingress=None, src="10.10.10.50", dst="10.10.10.1", note="host"),
    )
    assert "ACCEPTED" not in summary
    assert "NOT_ATTACHED" in summary
    assert "no confirmed link" in summary


def test_l2_show_ip_route_prints_the_gateway() -> None:
    config = "hostname SW2\nip default-gateway 10.99.0.1\n"
    text = show_ip_route(
        [{"network": "10.99.0.0/24", "next_hop": "interface Vlan99", "protocol": "connected"}],
        config=config,
        role="switch",
    )
    assert "Default gateway is 10.99.0.1" in text
    assert "ICMP redirect cache is empty" in text
    assert "Gateway of last resort" not in text


def test_vlan_brief_hides_trunks_and_svis() -> None:
    text = show_vlan_brief(
        [{"vlan": 10, "ports": ["GigabitEthernet1/0/1", "GigabitEthernet1/0/10", "Vlan99"]}],
        {10: "OFFICE"},
        [
            {"name": "GigabitEthernet1/0/1", "mode": "TRUNK"},
            {"name": "GigabitEthernet1/0/10", "mode": "ACCESS"},
            {"name": "Vlan99", "mode": "NONE"},
        ],
    )
    assert "Gi1/0/10" in text
    assert "Gi1/0/1," not in text and "Gi1/0/1 " not in text
    assert "Vl99" not in text and "Vlan99" not in text


def test_prompt_uses_the_expanded_interface() -> None:
    assert prompt_for("SW1", ["int gi1/0/10"]) == "SW1(config-if)#"


def test_start_command_runs_from_another_directory(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    stub = repo / "ensure-running"
    stub.write_text("#!/bin/sh\nprintf 'ok %s\\n' \"$1\"\n", encoding="utf-8")
    stub.chmod(0o755)
    launcher = repo / "bin" / "start-dryrun-lab"
    launcher.write_text((ROOT / "bin" / "start-dryrun-lab").read_text(encoding="utf-8"), encoding="utf-8")
    launcher.chmod(0o755)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("DRYRUN_HOME", None)
    completed = subprocess.run(
        [str(launcher), "--open"],
        cwd=elsewhere,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok --open"


def test_autostart_entry_names_start_dry_run_lab(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env.pop("DRYRUN_HOME", None)
    subprocess.run(["bash", str(ROOT / "bin" / "install-launchers")], cwd=ROOT, env=env, check=True)
    desktop = (home / ".config" / "autostart" / "start-dryrun-lab.desktop").read_text(encoding="utf-8")
    menu = (home / ".local" / "share" / "applications" / "start-dryrun-lab.desktop").read_text(encoding="utf-8")
    recorded = (home / ".config" / "dryrun-lab" / "repo-path").read_text(encoding="utf-8").strip()
    assert recorded == str(ROOT)
    for text in (desktop, menu):
        assert "Name=Start Dry Run Lab" in text
        assert f"Exec={ROOT}/bin/start-dryrun-lab" in text
    installed = home / ".local" / "bin" / "start-dryrun-lab"
    assert installed.is_file()
    assert os.access(installed, os.X_OK)


def test_page_script_parses() -> None:
    html = (ROOT / "src" / "dryrun_lab" / "static" / "index.html").read_text(encoding="utf-8")
    marker = 'src="/assets/'
    start = html.index(marker) + len('src="')
    src = html[start : html.index('"', start)]
    bundle = ROOT / "src" / "dryrun_lab" / "static" / src.lstrip("/")
    subprocess.check_call(["node", "--check", str(bundle)])
    text = bundle.read_text(encoding="utf-8", errors="strict")
    assert "Confirming cable…" in text
    assert "Not affiliated with or endorsed by Cisco" in text
    assert "Created by Paul Charydczak" in text


@pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")
def test_hostname_keeps_routes_on_the_lab_device() -> None:
    lab = load_office_lab()
    engine = Engine(network=f"dryrun-test-{uuid.uuid4().hex[:10]}")
    try:
        engine.recompute(lab)
        before = engine.show(lab, "R1", "show ip route")
        assert "10.255.1.1/32" in before
        engine.show_result(lab, "R1", "configure terminal")
        renamed = engine.show_result(lab, "R1", "hostname R1-QC")
        assert renamed.prompt == "R1-QC(config)#"
        ended = engine.show_result(lab, "R1", "end")
        assert ended.prompt == "R1-QC#"
        assert "NO_ACTIVE_LOCATION" not in ended.text
        assert "all routes removed" not in ended.text.lower()
        running = lab.device("R1").config
        assert running.count("hostname ") == 1
        assert "hostname R1-QC" in running
        assert lab.device("R1").name == "R1"
        route = engine.show(lab, "R1", "show ip route")
        assert "10.255.1.1/32" in route
        assert "No routes were computed" not in route
    finally:
        engine.close()


@pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")
def test_uncabled_host_ping_fails() -> None:
    lab = load_office_lab()
    lab.devices.append(
        Device(name="PCX", role="host", config=host_config("PCX", "10.10.10.50/24", "10.10.10.1"))
    )
    engine = Engine(network=f"dryrun-test-{uuid.uuid4().hex[:10]}")
    try:
        engine.recompute(lab)
        ping = engine.show(lab, "PCX", "ping 10.10.10.1")
        assert "0 percent" in ping
        assert "100 percent" not in ping
        assert "no confirmed link" in ping
        assert "ACCEPTED" not in ping
    finally:
        engine.close()


@pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")
def test_l2_switch_uses_its_default_gateway() -> None:
    lab = load_office_lab()
    engine = Engine(network=f"dryrun-test-{uuid.uuid4().hex[:10]}")
    try:
        engine.recompute(lab)
        route = engine.show(lab, "SW2", "show ip route")
        assert "Default gateway is 10.99.0.1" in route
        assert "Gateway of last resort is not set" not in route
        ping = engine.show(lab, "SW2", "ping 10.10.10.1")
        assert "100 percent" in ping
        assert "NO_ROUTE" not in ping
        warnings = engine.show(lab, "SW2", "show warnings")
        assert "ip default-gateway" not in warnings
    finally:
        engine.close()


@pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")
def test_show_vlan_brief_omits_trunks() -> None:
    lab = load_office_lab()
    engine = Engine(network=f"dryrun-test-{uuid.uuid4().hex[:10]}")
    try:
        engine.recompute(lab)
        brief = engine.show(lab, "SW1", "show vlan brief")
        assert "Gi1/0/10" in brief
        for trunk in ("Gi1/0/1", "Gi1/0/2", "Gi1/0/3", "Gi1/0/24"):
            assert f"{trunk}," not in brief and f"{trunk} " not in brief and not brief.rstrip().endswith(trunk)
        assert "Vl99" not in brief
    finally:
        engine.close()


@pytest.mark.skipif(not _engine_up(), reason="analysis engine is not listening")
def test_abbreviations_change_the_forwarding(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRYRUN_HOME", str(tmp_path))
    lab = load_office_lab()
    engine = Engine(network=f"dryrun-test-{uuid.uuid4().hex[:10]}")
    try:
        engine.recompute(lab)
        engine.show_result(lab, "SW1", "configure terminal")
        entered = engine.show_result(lab, "SW1", "int gi1/0/10")
        assert entered.prompt == "SW1(config-if)#"
        engine.show_result(lab, "SW1", "sw acc vlan 20")
        engine.show_result(lab, "SW1", "end")
        text = lab.device("SW1").config
        assert "switchport access vlan 20" in text
        assert "switchport access vlan 10" not in text
        brief = engine.show(lab, "SW1", "sh vl br")
        assert "Gi1/0/10" in brief
        engine.show_result(lab, "R1", "configure terminal")
        engine.show_result(lab, "R1", "ip rout 10.9.9.0 255.255.255.0 192.0.2.2")
        summary = engine.show_result(lab, "R1", "end")
        assert "10.9.9.0" in summary.text or "10.9.9.0/24" in engine.show(lab, "R1", "sh ip ro")
        listed = engine.show(lab, "R1", "sh access-l")
        assert "GUEST-IN" in listed
        neighbors = engine.show(lab, "SW1", "sh ip ospf nei")
        assert "not simulated" not in neighbors.lower()
    finally:
        engine.close()
