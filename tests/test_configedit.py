from dryrun_lab.configedit import apply_config_lines
from dryrun_lab.nsort import interface_key
from dryrun_lab.showfmt import normalize_command, parse_flow, show_ip_interface_brief, show_vlan_brief


def test_natural_interface_order() -> None:
    assert interface_key("GigabitEthernet1/0/2") < interface_key("GigabitEthernet1/0/10")
    text = show_ip_interface_brief(
        [
            {"name": "GigabitEthernet1/0/10", "address": None, "active": True, "admin_up": True},
            {"name": "GigabitEthernet1/0/2", "address": None, "active": True, "admin_up": True},
        ]
    )
    assert text.index("GigabitEthernet1/0/2") < text.index("GigabitEthernet1/0/10")
    vlan = show_vlan_brief(
        [{"vlan": 10, "ports": ["GigabitEthernet1/0/10", "GigabitEthernet1/0/2"]}],
        {10: "OFFICE"},
    )
    assert vlan.index("Gi1/0/2") < vlan.index("Gi1/0/10")


def test_unnumbered_acl_line_appends_after_permit() -> None:
    config = "ip access-list extended GUEST-IN\n permit ip any any\n!\nend\n"
    updated = apply_config_lines(
        config,
        [
            "ip access-list extended GUEST-IN",
            "deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255",
            "end",
        ],
    )
    assert updated.index("permit ip any any") < updated.index("deny ip 10.30.30.0")
    assert " 10 permit ip any any" in updated
    assert " 20 deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255" in updated


def test_trunk_add_keeps_existing_vlans() -> None:
    config = (
        "interface GigabitEthernet1/0/1\n"
        " switchport trunk allowed vlan 10,20,30,99\n"
        "!\nend\n"
    )
    updated = apply_config_lines(
        config,
        ["interface GigabitEthernet1/0/1", "switchport trunk allowed vlan add 40", "end"],
    )
    assert "switchport trunk allowed vlan 10,20,30,99,40" in updated
    assert updated.count("switchport trunk allowed vlan") == 1


def test_shutdown_replaces_no_shutdown_and_revert_text_round_trips() -> None:
    original = "interface GigabitEthernet0/0\n no shutdown\n!\nend\n"
    shut = apply_config_lines(original, ["interface GigabitEthernet0/0", "shutdown", "end"])
    assert "\nshutdown\n" in shut
    assert "no shutdown" not in shut
    restored = apply_config_lines(shut, ["interface GigabitEthernet0/0", "no shutdown", "end"])
    assert "no shutdown" in restored
    assert "\nshutdown\n" not in restored


def test_flow_and_show_commands_parse() -> None:
    assert normalize_command("show vlan brief") == "vlan"
    assert normalize_command("sh int trunk") == "trunk"
    assert normalize_command("show access-lists") == "acl"
    flow = parse_flow("ping 10.40.40.1 source 10.40.40.50 ingress GigabitEthernet0/0.40")
    assert flow is not None
    assert flow["dst"] == "10.40.40.1"
    assert flow["src"] == "10.40.40.50"
    assert flow["ingress"] == "GigabitEthernet0/0.40"
    assert parse_flow("traceroute 10.255.1.1") is not None
