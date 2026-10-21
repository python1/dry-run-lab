from dryrun_lab.showfmt import normalize_command, show_ip_interface_brief, show_ip_route


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
