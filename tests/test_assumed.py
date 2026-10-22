"""A suggested /30 is named only when a computed result uses it."""

from dryrun_lab.engine import _assumed_links
from dryrun_lab.infer import endpoint_key
from dryrun_lab.showfmt import (
    assumed_lines_for_route_changes,
    assumed_lines_for_routes,
    assumed_lines_for_trace,
    format_change_diff,
)
from dryrun_lab.store import Device, Lab, Link

NOTE = "assumed link from shared /30: R1 Gi0/2 - SW1 Gi1/0/24 (not confirmed)"


def _link(status: str = "suggested") -> Link:
    return Link(
        id="p2p",
        a_device="R1",
        a_interface="GigabitEthernet0/2",
        b_device="SW1",
        b_interface="GigabitEthernet1/0/24",
        status=status,
        source="subnet",
        reason="shared subnet 10.50.0.0/30",
    )


def _ospf() -> dict:
    return {
        "network": "10.255.1.1/32",
        "protocol": "ospf",
        "next_hop": {"interface": "GigabitEthernet0/2", "ip": "10.50.0.2"},
    }


def test_ospf_route_names_the_unconfirmed_link() -> None:
    assert assumed_lines_for_routes("R1", [_ospf()], [_link()]) == [NOTE]


def test_connected_route_on_the_same_interface_is_not_an_assumed_hop() -> None:
    connected = {
        "network": "10.50.0.0/30",
        "protocol": "connected",
        "next_hop": {"interface": "GigabitEthernet0/2", "ip": None},
    }
    assert assumed_lines_for_routes("r1", [connected], [_link()]) == []


def test_trace_across_the_link_is_named_and_a_same_device_trace_is_not() -> None:
    crossed = {
        "steps": [
            {"node": "R1", "detail": {"outputInterface": "GigabitEthernet0/2"}},
            {"node": "sw1", "detail": {"inputInterface": "GigabitEthernet1/0/24"}},
        ]
    }
    local = {"steps": [{"node": "r1", "detail": {"inputInterface": "GigabitEthernet0/0.10"}}]}
    assert assumed_lines_for_trace(crossed, [_link()]) == [NOTE]
    assert assumed_lines_for_trace(local, [_link()]) == []


def test_route_change_summary_names_the_link_and_a_connected_change_does_not() -> None:
    removed = assumed_lines_for_route_changes({"r1": [_ospf()]}, {"r1": []}, [_link()])
    text = format_change_diff({"r1": [_ospf()]}, {"r1": []}, [], [], {}, {}, 1, assumed=removed)
    assert NOTE in text
    assert text.rstrip().endswith("(not confirmed)")
    connected = {
        "network": "10.10.10.0/24",
        "protocol": "connected",
        "next_hop": {"interface": "GigabitEthernet0/0.10", "ip": None},
    }
    assert assumed_lines_for_route_changes({"r1": [connected]}, {"r1": []}, [_link()]) == []


def test_only_an_unconfirmed_subnet_edge_is_assumed() -> None:
    lab = Lab()
    lab.devices = [Device(name="R1", role="router"), Device(name="SW1", role="switch")]
    lab.links = [_link("confirmed")]
    assert _assumed_links(lab) == []
    lab.links = [
        _link(),
        Link(
            id="trunk",
            a_device="R1",
            a_interface="GigabitEthernet0/0",
            b_device="SW1",
            b_interface="GigabitEthernet1/0/1",
            status="suggested",
            source="description",
            reason="description on R1 GigabitEthernet0/0",
        ),
    ]
    assumed = _assumed_links(lab)
    assert [link.id for link in assumed] == ["p2p"]
    lab.withdrawn = [endpoint_key("R1", "GigabitEthernet0/2", "SW1", "GigabitEthernet1/0/24")]
    assert _assumed_links(lab) == []
