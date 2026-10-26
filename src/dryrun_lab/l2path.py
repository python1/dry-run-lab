"""Walk confirmed cables for the switches a trace does not list.

The computed trace names layer-3 devices. After a host resolves its gateway,
the engine delivers the packet to that neighbor and does not record the
switches in between. This walk is a separate note. It uses confirmed links
and the VLAN facts already computed for those interfaces. Suggested links
are not used.
"""

from __future__ import annotations

import re
from typing import Any

from dryrun_lab.configparse import canonical_interface, parse_config
from dryrun_lab.hosts import gateway_address
from dryrun_lab.store import Lab

_ENCAP = re.compile(r"(?i)^encapsulation\s+dot1q\s+(\d+)\s*$")
_ADDRESS = re.compile(r"(?i)^ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+")


def unattached_host(lab: Lab, source: str) -> str | None:
    """Sentence for a host with an address and no confirmed cable.

    Suggested links are not a connection. An uncabled host reaches nothing.
    """
    host = lab.device(source)
    if host is None or host.role != "host":
        return None
    parsed = parse_config(host.config)
    addressed = [iface for iface in parsed.interfaces if iface.address]
    if not addressed:
        return None
    for iface in addressed:
        if _confirmed_from(lab, host.name, iface.name):
            return None
    iface = addressed[0]
    return (
        f"{host.name} {_short(iface.name)}: no confirmed link. "
        "Suggested links are not used, so this host is not attached."
    )


def layer2_note(
    lab: Lab,
    interfaces: dict[str, list[dict[str, Any]]],
    source: str,
    destination: str,
) -> str | None:
    host = lab.device(source)
    if host is None or host.role != "host":
        return None
    lines = [
        "Switches are not hops in this computed trace. "
        "The path below is from confirmed links and computed VLAN membership.",
    ]
    lines.append(_segment(lab, interfaces, host.name))
    other = _host_owning(lab, destination)
    if other is not None and other.name.lower() != host.name.lower():
        lines.append(_segment(lab, interfaces, other.name))
    return "\n".join(lines)


def _segment(lab: Lab, interfaces: dict[str, list[dict[str, Any]]], name: str) -> str:
    host = lab.device(name)
    if host is None:
        return f"{name}: no such host."
    parsed = parse_config(host.config)
    addressed = next((iface for iface in parsed.interfaces if iface.address), None)
    gateway = gateway_address(host.config)
    if addressed is None:
        return f"{host.name}: no address, so there is no layer-2 path."
    if gateway is None:
        return f"{host.name} {addressed.name}: no default gateway, so only its own subnet can be reached."
    link = _confirmed_from(lab, host.name, addressed.name)
    if not link:
        return (
            f"{host.name} {_short(addressed.name)}: no confirmed link. "
            "Suggested links are not used, so this host is not attached."
        )
    switch, port = link[0]
    row = _row(interfaces, switch, port)
    vlan = _access_vlan(row)
    if vlan is None:
        return (
            f"{host.name} {_short(addressed.name)} — {switch} {_short(port)}: "
            "the attached port is not an access port in a VLAN, so the layer-2 path stops."
        )
    if row is not None and not _up(row):
        return (
            f"VLAN {vlan}: {host.name} {_short(addressed.name)} — {switch} {_short(port)}. "
            "Stops here. That port is down."
        )
    hops: list[tuple[str, str]] = [(host.name, addressed.name), (_display(lab, switch), port)]
    visited = {host.name.lower(), switch.lower()}
    blocked: str | None = None
    queue: list[tuple[str, str, list[tuple[str, str]]]] = [(switch, port, hops)]
    while queue:
        device, arrived, path = queue.pop(0)
        exits = _ports(interfaces, device, vlan, include_down=True)
        if not exits:
            continue
        up_exits = [port for port in exits if _up(_row(interfaces, device, port) or {"admin_up": False})]
        for exit_port in exits:
            local = _row(interfaces, device, exit_port)
            if local is not None and not _up(local):
                fars = _confirmed_from(lab, device, exit_port)
                if fars:
                    far_device, far_port = fars[0]
                    blocked = (
                        f"VLAN {vlan}: {_format(path + [(_display(lab, device), exit_port)])}. "
                        f"Stops here. The confirmed link {_display(lab, device)} {_short(exit_port)} — "
                        f"{_display(lab, far_device)} {_short(far_port)} is down."
                    )
                continue
            if canonical_interface(exit_port) == canonical_interface(arrived) and len(up_exits) > 1:
                continue
            for far_device, far_port in _confirmed_from(lab, device, exit_port):
                sub = _gateway_subinterface(lab, far_device, far_port, vlan, gateway)
                if sub is not None:
                    done = path + [(_display(lab, device), exit_port), (_display(lab, far_device), sub)]
                    return f"VLAN {vlan}: {_format(done)}"
                far_row = _row(interfaces, far_device, far_port)
                if far_row is not None and not _up(far_row):
                    blocked = (
                        f"VLAN {vlan}: {_format(path + [(_display(lab, device), exit_port)])}. "
                        f"Stops here. The confirmed link {_display(lab, device)} {_short(exit_port)} — "
                        f"{_display(lab, far_device)} {_short(far_port)} is down."
                    )
                    continue
                if far_row is None or not _carries(far_row, vlan):
                    continue
                if far_device.lower() in visited:
                    continue
                visited.add(far_device.lower())
                queue.append(
                    (
                        far_device,
                        far_port,
                        path + [(_display(lab, device), exit_port), (_display(lab, far_device), far_port)],
                    )
                )
    if blocked:
        return blocked
    return (
        f"VLAN {vlan}: {_format(hops)}. "
        "Stops here. No confirmed link carries this VLAN to the gateway."
    )


def _host_owning(lab: Lab, address: str) -> Any:
    import ipaddress

    try:
        target = ipaddress.ip_address(address)
    except ValueError:
        return None
    for device in lab.devices:
        if device.role != "host":
            continue
        for iface in parse_config(device.config).interfaces:
            if not iface.address or iface.prefix is None:
                continue
            network = ipaddress.ip_network(f"{iface.address}/{iface.prefix}", strict=False)
            if target in network:
                return device
    return None


def _gateway_subinterface(lab: Lab, device: str, parent: str, vlan: int, gateway: str) -> str | None:
    found = lab.device(device)
    if found is None:
        return None
    parent_name = canonical_interface(parent)
    current: str | None = None
    encap: int | None = None
    address: str | None = None
    matched: str | None = None

    def close() -> None:
        nonlocal matched
        if current and current.startswith(parent_name + ".") and encap == vlan and address == gateway:
            matched = current

    for raw in found.config.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        iface = re.match(r"(?i)^interface\s+(\S+)", line)
        if iface:
            close()
            current = canonical_interface(iface.group(1))
            encap = None
            address = None
            continue
        if current is None:
            continue
        vlan_match = _ENCAP.match(line)
        if vlan_match:
            encap = int(vlan_match.group(1))
            continue
        addr_match = _ADDRESS.match(line)
        if addr_match:
            address = addr_match.group(1)
    close()
    return matched


def _confirmed_from(lab: Lab, device: str, interface: str) -> list[tuple[str, str]]:
    want_device = device.lower()
    want_iface = canonical_interface(interface)
    found: list[tuple[str, str]] = []
    for link in lab.links:
        if link.status != "confirmed":
            continue
        if link.a_device.lower() == want_device and canonical_interface(link.a_interface) == want_iface:
            found.append((link.b_device, canonical_interface(link.b_interface)))
        elif link.b_device.lower() == want_device and canonical_interface(link.b_interface) == want_iface:
            found.append((link.a_device, canonical_interface(link.a_interface)))
    return found


def _ports(
    interfaces: dict[str, list[dict[str, Any]]],
    device: str,
    vlan: int,
    include_down: bool = False,
) -> list[str]:
    names: list[str] = []
    for row in interfaces.get(device.lower(), []):
        if not _carries(row, vlan):
            continue
        if not include_down and not _up(row):
            continue
        names.append(str(row.get("name") or ""))
    return [name for name in names if name]


def _row(interfaces: dict[str, list[dict[str, Any]]], device: str, interface: str) -> dict[str, Any] | None:
    want = canonical_interface(interface)
    for row in interfaces.get(device.lower(), []):
        if canonical_interface(str(row.get("name") or "")) == want:
            return row
    return None


def _access_vlan(row: dict[str, Any] | None) -> int | None:
    if row is None:
        return None
    if str(row.get("mode") or "").upper() != "ACCESS":
        return None
    return _vlan_id(row.get("access_vlan"))


def _carries(row: dict[str, Any], vlan: int) -> bool:
    mode = str(row.get("mode") or "").upper()
    if mode == "ACCESS":
        return _vlan_id(row.get("access_vlan")) == vlan
    if mode == "TRUNK":
        return vlan in _vlan_set(row.get("allowed"))
    return False


def _up(row: dict[str, Any]) -> bool:
    admin = row.get("admin_up")
    active = row.get("active")
    if admin is False or active is False:
        return False
    return True


def _vlan_id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _vlan_set(allowed: Any) -> set[int]:
    found: set[int] = set()
    for part in str(allowed or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            if left.isdigit() and right.isdigit():
                found.update(range(int(left), int(right) + 1))
            continue
        if part.isdigit():
            found.add(int(part))
    return found


def _display(lab: Lab, name: str) -> str:
    device = lab.device(name)
    return device.name if device else name


def _format(hops: list[tuple[str, str]]) -> str:
    return " — ".join(f"{device} {_short(interface)}" for device, interface in hops)


def _short(name: str) -> str:
    return (
        canonical_interface(name)
        .replace("TenGigabitEthernet", "Te")
        .replace("GigabitEthernet", "Gi")
        .replace("FastEthernet", "Fa")
    )
