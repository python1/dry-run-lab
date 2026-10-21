from dryrun_lab.examples import load_office_lab
from dryrun_lab.hosts import host_config
from dryrun_lab.store import Device, add_user_link, place_host


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
