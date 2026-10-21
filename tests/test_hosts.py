from dryrun_lab.examples import load_office_lab
from dryrun_lab.hosts import host_config
from dryrun_lab.store import Device, add_user_link, apply_inference, place_host, unconfirm_link


def test_host_config_uses_the_address_and_gateway() -> None:
    text = host_config("PC40", "10.40.40.50/24", "10.40.40.1")
    assert "hostname PC40" in text
    assert "interface Ethernet0" in text
    assert "ip address 10.40.40.50 255.255.255.0" in text
    assert "ip default-gateway 10.40.40.1" in text


def test_place_host_clears_the_switch_port_list() -> None:
    lab = load_office_lab()
    sw2 = lab.device("SW2")
    assert sw2 is not None
    x, y = place_host(lab)
    assert x == min(device.x for device in lab.devices)
    assert y >= sw2.y + 48 + 4 * 26 + 12 + 64
    assert y > 620
    lab.devices.append(
        Device(name="PC40", role="host", x=x, y=y, config=host_config("PC40", "10.40.40.50/24", "10.40.40.1"))
    )
    _x2, y2 = place_host(lab)
    assert y2 >= y + 48 + 26 + 12 + 64


def test_link_add_accepts_short_interface_names() -> None:
    lab = load_office_lab()
    lab.devices.append(
        Device(name="PC40", role="host", x=80, y=800, config=host_config("PC40", "10.40.40.50/24", "10.40.40.1"))
    )
    link = add_user_link(lab, "pc40", "Eth0", "sw2", "Gi0/12")
    assert link.a_device == "PC40"
    assert link.a_interface == "Ethernet0"
    assert link.b_device == "SW2"
    assert link.b_interface == "GigabitEthernet0/12"
    assert link.status == "confirmed"
    pc40 = lab.device("PC40")
    sw2 = lab.device("SW2")
    assert pc40 is not None and sw2 is not None
    assert pc40.x == sw2.x
    assert pc40.y >= sw2.y + 48 + 4 * 26 + 12 + 64


def test_link_add_places_each_host_under_its_switch() -> None:
    lab = load_office_lab()
    sw2 = lab.device("SW2")
    sw3 = lab.device("SW3")
    assert sw2 is not None and sw3 is not None
    lab.devices.append(
        Device(name="PC40", role="host", x=150, y=800, config=host_config("PC40", "10.40.40.50/24", "10.40.40.1"))
    )
    lab.devices.append(
        Device(name="SRV20", role="host", x=150, y=900, config=host_config("SRV20", "10.20.20.50/24", "10.20.20.1"))
    )
    add_user_link(lab, "PC40", "Ethernet0", "SW2", "GigabitEthernet0/12")
    pc40 = lab.device("PC40")
    assert pc40 is not None
    assert pc40.x == sw2.x
    assert pc40.y == sw2.y + 48 + 4 * 26 + 12 + 64
    add_user_link(lab, "SRV20", "Ethernet0", "SW3", "GigabitEthernet0/10")
    srv20 = lab.device("SRV20")
    assert srv20 is not None
    assert srv20.x == sw3.x
    assert srv20.x != sw2.x
    assert srv20.y >= sw3.y + 48 + 12 + 64
    add_user_link(lab, "PC40", "Ethernet0", "SW2", "GigabitEthernet0/12")
    assert pc40.x == sw2.x
    assert pc40.y == sw2.y + 48 + 4 * 26 + 12 + 64
    parked = pc40.y
    add_user_link(lab, "PC40", "Ethernet0", "SW2", "GigabitEthernet0/12")
    assert pc40.y == parked


def test_unconfirm_keeps_a_drawn_cable_and_restores_an_inferred_one() -> None:
    lab = load_office_lab()
    inferred = next(link for link in lab.links if link.status == "suggested")
    inferred.status = "confirmed"
    inferred_id = inferred.id
    assert unconfirm_link(lab, inferred_id) is not None
    apply_inference(lab)
    restored = next(link for link in lab.links if link.id == inferred_id)
    assert restored.status == "suggested"
    lab.devices.append(
        Device(name="PC40", role="host", x=80, y=800, config=host_config("PC40", "10.40.40.50/24", "10.40.40.1"))
    )
    drawn = add_user_link(lab, "PC40", "Eth0", "SW2", "Gi0/12")
    assert drawn.status == "confirmed"
    assert unconfirm_link(lab, drawn.id) is not None
    apply_inference(lab)
    kept = next(link for link in lab.links if link.id == drawn.id)
    assert kept.status == "suggested"
    assert kept.source == "user"
    assert unconfirm_link(lab, "missing") is None
