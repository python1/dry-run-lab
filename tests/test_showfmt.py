from pathlib import Path

from dryrun_lab.showfmt import (
    format_change_diff,
    format_ping,
    normalize_command,
    show_access_lists,
    show_ip_interface_brief,
    show_ip_route,
)


def test_command_aliases() -> None:
    assert normalize_command("sh ip int br") == "interfaces"
    assert normalize_command("show ip route") == "routes"
    assert normalize_command("show running-config") == "running-config"
    assert normalize_command("show ip route | include 0.0.0.0") is None
    assert normalize_command("configure terminal") is None


def test_interface_brief_marks_simulated_method() -> None:
    text = show_ip_interface_brief(
        [
            {
                "name": "GigabitEthernet0/0.10",
                "address": "10.10.10.1/24",
                "active": True,
                "admin_up": True,
            },
            {
                "name": "GigabitEthernet0/1",
                "address": None,
                "active": False,
                "admin_up": False,
            },
        ]
    )
    assert "COMPUTED" not in text  # banner is added by the engine
    assert "sim" in text
    assert "10.10.10.1" in text
    assert "unassigned" in text
    assert "administratively down" in text


def test_route_table_uses_computed_hops() -> None:
    text = show_ip_route(
        [
            {
                "network": "0.0.0.0/0",
                "next_hop": "ip 192.0.2.2",
                "protocol": "static",
                "metric": 0,
                "admin_distance": 1,
            },
            {
                "network": "10.10.10.0/24",
                "next_hop": "interface GigabitEthernet0/0.10",
                "protocol": "connected",
                "metric": 0,
                "admin_distance": 0,
            },
            {
                "network": "10.255.1.1/32",
                "next_hop": {
                    "interface": "GigabitEthernet0/2",
                    "ip": "10.50.0.2",
                    "type": "interface",
                },
                "protocol": "ospf",
                "metric": 2,
                "admin_distance": 110,
            },
        ]
    )
    assert "Gateway of last resort is 192.0.2.2" in text
    assert "S*    0.0.0.0/0 [1/0] via 192.0.2.2" in text
    assert "C     10.10.10.0/24 is directly connected, GigabitEthernet0/0.10" in text
    assert "O     10.255.1.1/32 [110/2] via 10.50.0.2, GigabitEthernet0/2" in text


def test_disposition_sentence_names_the_acl_line() -> None:
    text = format_ping(
        "10.99.0.1",
        "10.30.30.50",
        "GigabitEthernet0/0.30",
        {
            "disposition": "DENIED_IN",
            "steps": [
                {
                    "node": "R1",
                    "action": "DENIED",
                    "detail": {
                        "inputInterface": "GigabitEthernet0/0.30",
                        "filter": "GUEST-IN",
                        "filterType": "INGRESS_FILTER",
                    },
                }
            ],
        },
        "Dropped by ACL GUEST-IN\n  sequence 25: deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255\n",
    )
    assert (
        "Dropped because ACL GUEST-IN sequence 25 on R1 Gi0/0.30 denies 10.30.30.0/24 to 10.99.0.0/24."
        in text
    )
    assert "line 10" not in text


def test_show_access_lists_uses_sequence_numbers() -> None:
    config = (Path(__file__).resolve().parents[1] / "examples" / "office-lab" / "configs" / "R1.cfg").read_text(
        encoding="utf-8"
    )
    text = show_access_lists(config, [])
    assert "    10 deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255" in text
    assert "    20 deny ip 10.30.30.0 0.0.0.255 10.20.20.0 0.0.0.255" in text
    assert "    30 permit ip any any" in text
    assert text.index("    10 deny") < text.index("    20 deny") < text.index("    30 permit")
    assert "line " not in text


def test_change_summary_prints_the_revert_headline_and_acl_notice() -> None:
    text = format_change_diff(
        {},
        {},
        [],
        [],
        {},
        {},
        1,
        headline="Reverted one edit. Recomputed.",
        notices=["Line added at sequence 40, after sequence 30 permit ip any any; it will never match."],
    )
    assert text.startswith("Reverted one edit. Recomputed.\n")
    assert "Applied 1 line" not in text
    assert text.index("it will never match") < text.index("Routes")


def test_neighbor_unreachable_names_the_interface() -> None:
    text = format_ping(
        "10.20.20.50",
        None,
        None,
        {
            "disposition": "NEIGHBOR_UNREACHABLE",
            "steps": [
                {
                    "node": "PC40",
                    "action": "NEIGHBOR_UNREACHABLE",
                    "detail": {"outputInterface": "Ethernet0", "resolvedNexthopIp": "10.40.40.1"},
                }
            ],
        },
        None,
    )
    assert "No neighbor answered for 10.40.40.1 on PC40 Ethernet0." in text
