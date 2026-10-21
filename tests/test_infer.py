from pathlib import Path

from dryrun_lab.configparse import canonical_interface, parse_config
from dryrun_lab.examples import load_lab_dir
from dryrun_lab.infer import endpoint_key

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "examples" / "office-lab"


def test_canonical_names() -> None:
    assert canonical_interface("Gi0/0") == "GigabitEthernet0/0"
    assert canonical_interface("Gig 1/0/1") == "GigabitEthernet1/0/1"
    assert canonical_interface("Te1/0/1") == "TenGigabitEthernet1/0/1"
    assert canonical_interface("Vlan99") == "Vlan99"


def test_office_lab_inference() -> None:
    lab = load_lab_dir(LAB)
    keys = {
        endpoint_key(link.a_device, link.a_interface, link.b_device, link.b_interface): link
        for link in lab.links
    }
    assert len(keys) == 4
    trunk = keys[endpoint_key("R1", "Gi0/0", "SW1", "Gi1/0/1")]
    assert "description" in trunk.source and "cdp" in trunk.source
    access = keys[endpoint_key("SW1", "Gi1/0/2", "SW2", "Gi0/1")]
    assert "lldp" in access.source and "description" in access.source
    cdp_only = keys[endpoint_key("SW1", "Gi1/0/3", "SW3", "Gi0/1")]
    assert cdp_only.source == "cdp"
    p2p = keys[endpoint_key("R1", "Gi0/2", "SW1", "Gi1/0/24")]
    assert p2p.source == "subnet"
    assert all(link.status == "suggested" for link in lab.links)
    assert any("10.99.0.0/24" in note for note in lab.notes)
    assert not any("10.50.0.0/30" in note for note in lab.notes)


def test_subinterface_is_not_a_cable() -> None:
    text = """
hostname R1
interface GigabitEthernet0/0.10
 ip address 10.10.10.1 255.255.255.0
"""
    parsed = parse_config(text)
    assert parsed.interfaces[0].physical is False
    assert parsed.interfaces[0].network == "10.10.10.0/24"
