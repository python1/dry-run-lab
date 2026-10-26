"""Guess cables from configs and pasted neighbor text.

Suggestions are not installed as topology until someone confirms them.
A shared subnet with more than two members, or a prefix shorter than /30,
is reported as a note instead of a cable.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass, field

from dryrun_lab.configparse import Iface, ParsedConfig, canonical_interface, interface_pattern, parse_config

_IFACE = interface_pattern().pattern
_DESC = re.compile(rf"(?i)\bto\s+([A-Za-z][A-Za-z0-9_-]{{0,40}})\s+({_IFACE})")
_CDP_ROW = re.compile(
    rf"^(?P<device>\S+)\s+(?P<local>{_IFACE})\s+\d+\s+.*?(?P<remote>{_IFACE})\s*$"
)
_LLDP_LOCAL = re.compile(r"(?i)^local\s+intf:\s*(\S+)")
_LLDP_NAME = re.compile(r"(?i)^system\s+name:\s*(\S+)")
_LLDP_PORT = re.compile(r"(?i)^port\s+id:\s*(\S+)")
_CDP_DETAIL_DEV = re.compile(r"(?i)^device\s+id:\s*(\S+)")
_CDP_DETAIL_PORTS = re.compile(
    rf"(?i)^interface:\s*({_IFACE})\s*,\s*port\s+id\s*\(outgoing port\):\s*({_IFACE})"
)


@dataclass
class Suggestion:
    a_device: str
    a_interface: str
    b_device: str
    b_interface: str
    source: str
    reason: str

    @property
    def key(self) -> str:
        return endpoint_key(self.a_device, self.a_interface, self.b_device, self.b_interface)


@dataclass
class Inference:
    links: list[Suggestion] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def endpoint_key(a_device: str, a_interface: str, b_device: str, b_interface: str) -> str:
    left = (a_device.lower(), canonical_interface(a_interface).lower())
    right = (b_device.lower(), canonical_interface(b_interface).lower())
    if left > right:
        left, right = right, left
    return f"{left[0]}|{left[1]}|{right[0]}|{right[1]}"


def link_id(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()[:8]


def infer(devices: dict[str, tuple[str, str]]) -> Inference:
    """devices maps a device name to (config text, neighbor text)."""
    parsed = {name: parse_config(config) for name, (config, _neighbor) in devices.items()}
    names = list(devices)
    found: dict[str, list[Suggestion]] = {}

    def add(item: Suggestion) -> None:
        found.setdefault(item.key, []).append(item)

    for name, (_config, neighbor) in devices.items():
        for iface in parsed[name].interfaces:
            if not iface.description:
                continue
            match = _DESC.search(iface.description)
            if not match:
                continue
            remote = _resolve_device(match.group(1), names)
            if remote is None or remote.lower() == name.lower():
                continue
            remote_iface = canonical_interface(match.group(2))
            known = parsed[remote].get(remote_iface) is not None
            why = f"description on {name} {iface.name}"
            if not known:
                why += f"; {remote_iface} is not in {remote}'s config"
            add(
                Suggestion(
                    name,
                    iface.name,
                    remote,
                    remote_iface,
                    "description",
                    why,
                )
            )
        for local, remote_dev, remote_iface, kind in _neighbors(neighbor):
            remote = _resolve_device(remote_dev, names)
            if remote is None or remote.lower() == name.lower():
                continue
            local_name = canonical_interface(local)
            remote_name = canonical_interface(remote_iface)
            if parsed[name].get(local_name) is None:
                continue
            # CDP and LLDP pastes do not suggest a cable when either end is a host.
            if _looks_like_host(devices[name][0]) or _looks_like_host(devices[remote][0]):
                continue
            add(
                Suggestion(
                    name,
                    local_name,
                    remote,
                    remote_name,
                    kind,
                    f"{kind.upper()} neighbor text on {name}",
                )
            )

    notes: list[str] = []
    grouped: dict[str, list[tuple[str, Iface]]] = {}
    for name, cfg in parsed.items():
        for iface in cfg.interfaces:
            if iface.network:
                grouped.setdefault(iface.network, []).append((name, iface))
    for network, members in sorted(grouped.items()):
        if len(members) < 2:
            continue
        prefix = int(network.split("/")[1])
        physical = [(name, iface) for name, iface in members if iface.physical]
        unique_devices = {name.lower() for name, _iface in physical}
        if prefix >= 30 and len(physical) == 2 and len(unique_devices) == 2:
            (a_name, a_iface), (b_name, b_iface) = physical
            add(
                Suggestion(
                    a_name,
                    a_iface.name,
                    b_name,
                    b_iface.name,
                    "subnet",
                    f"shared subnet {network}",
                )
            )
            continue
        where = ", ".join(f"{name} {iface.name}" for name, iface in members)
        notes.append(
            f"{network} is shared by {where}. Not turned into a cable."
        )

    _suggest_host_cables(devices, add)

    links: list[Suggestion] = []
    for key, items in found.items():
        sources = []
        reasons = []
        for item in items:
            if item.source not in sources:
                sources.append(item.source)
            if item.reason not in reasons:
                reasons.append(item.reason)
        first = items[0]
        links.append(
            Suggestion(
                first.a_device,
                canonical_interface(first.a_interface),
                first.b_device,
                canonical_interface(first.b_interface),
                "+".join(sorted(sources)),
                "; ".join(reasons),
            )
        )
    links.sort(key=lambda item: item.key)
    return Inference(links=links, notes=notes)


def _suggest_host_cables(devices: dict[str, tuple[str, str]], add) -> None:
    """Suggest a host cable from an access VLAN plus a matching description.

    CDP and LLDP do not list hosts. A suggestion is added only when the host
    address sits in that access VLAN's subnet and exactly one switch port's
    description matches the host. Anything else stays a manual cable.
    """
    blocks = {name: _interface_blocks(config) for name, (config, _neighbor) in devices.items()}
    vlan_nets: dict[int, list[ipaddress.IPv4Network]] = {}
    for name, rows in blocks.items():
        if _looks_like_host(devices[name][0]):
            continue
        for row in rows:
            network = _block_network(row)
            if network is None:
                continue
            vlan_id = _vlan_number(row["name"])
            if vlan_id is None and row["dot1q"] is not None:
                vlan_id = row["dot1q"]
            if vlan_id is None:
                continue
            vlan_nets.setdefault(vlan_id, [])
            if network not in vlan_nets[vlan_id]:
                vlan_nets[vlan_id].append(network)

    hosts: list[tuple[str, dict]] = []
    access: list[tuple[str, dict]] = []
    for name, (config, _neighbor) in devices.items():
        if _looks_like_host(config):
            for row in blocks[name]:
                if row["address"] and row["name"].startswith("Ethernet"):
                    hosts.append((name, row))
            continue
        for row in blocks[name]:
            if row["mode"] == "trunk" or row["access_vlan"] is None:
                continue
            if not row["name"].startswith(("GigabitEthernet", "TenGigabitEthernet", "FastEthernet", "Ethernet")):
                continue
            access.append((name, row))

    candidates: list[tuple[str, dict, str, dict, int, ipaddress.IPv4Network]] = []
    for host, host_row in hosts:
        try:
            address = ipaddress.ip_address(host_row["address"])
        except ValueError:
            continue
        for switch, port in access:
            if not _description_matches(host, port["description"]):
                continue
            vlan_id = port["access_vlan"]
            for network in vlan_nets.get(vlan_id, []):
                if address in network:
                    candidates.append((host, host_row, switch, port, vlan_id, network))
                    break

    host_hits: dict[str, int] = {}
    port_hits: dict[tuple[str, str], int] = {}
    for host, _host_row, switch, port, _vlan_id, _network in candidates:
        host_hits[host] = host_hits.get(host, 0) + 1
        key = (switch.lower(), port["name"].lower())
        port_hits[key] = port_hits.get(key, 0) + 1
    for host, host_row, switch, port, vlan_id, network in candidates:
        if host_hits[host] != 1 or port_hits[(switch.lower(), port["name"].lower())] != 1:
            continue
        add(
            Suggestion(
                host,
                host_row["name"],
                switch,
                port["name"],
                "host",
                (
                    f"{host} {host_row['address']} is in VLAN {vlan_id} ({network}); "
                    f"{switch} {port['name']} description matches {host}"
                ),
            )
        )


def _looks_like_host(config: str) -> bool:
    """A host has a default gateway and is not a router or a switch.

    Switch commands sit indented under an interface, so a column-0 search
    misses them. A vlan definition, an SVI, or any switchport line means
    this device is not a host, even when it also has ``ip default-gateway``.
    """
    if not re.search(r"(?im)^ip\s+default-gateway\s+\d", config):
        return False
    if re.search(r"(?im)^ip\s+routing\s*$", config):
        return False
    for raw in config.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        if re.match(r"(?i)^(?:no\s+)?switchport\b", line):
            return False
        if re.match(r"(?i)^vlan\s+(?:\d+|access-map\b|filter\b)", line):
            return False
        if re.match(r"(?i)^interface\s+vlan\d+\b", line):
            return False
    return True


def _description_matches(host: str, description: str) -> bool:
    """True when the port description names this host, not merely the VLAN."""
    if not description.strip():
        return False
    folded_host = host.casefold()
    folded_desc = description.casefold()
    if len(folded_host) >= 3 and folded_host in folded_desc:
        return True
    words = [word for word in re.split(r"[^a-z0-9]+", folded_desc) if word]
    wordset = set(words)
    numbers = {int(word) for word in words if word.isdigit()}
    parts = [part for part in re.split(r"[^a-z0-9]+", folded_host) if part]
    alpha = [part for part in parts if not part.isdigit() and len(part) >= 3]
    nums = [int(part) for part in parts if part.isdigit()]
    if not alpha:
        return False
    for token in alpha:
        if token in wordset:
            continue
        if len(token) >= 4 and any(word.startswith(token) for word in wordset):
            continue
        return False
    if nums and not all(number in numbers for number in nums):
        return False
    return True


def _interface_blocks(config: str) -> list[dict]:
    rows: list[dict] = []
    current: dict | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            rows.append(current)
            current = None

    for raw in config.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        iface = re.match(r"(?i)^interface\s+(\S+)", line)
        if iface:
            close()
            current = {
                "name": canonical_interface(iface.group(1)),
                "description": "",
                "mode": "",
                "access_vlan": None,
                "address": None,
                "mask": None,
                "dot1q": None,
            }
            continue
        if current is None:
            continue
        desc = re.match(r"(?i)^description\s+(.+)$", line)
        if desc:
            current["description"] = desc.group(1).strip()
            continue
        mode = re.match(r"(?i)^switchport\s+mode\s+(access|trunk)\s*$", line)
        if mode:
            current["mode"] = mode.group(1).lower()
            continue
        vlan = re.match(r"(?i)^switchport\s+access\s+vlan\s+(\d+)\s*$", line)
        if vlan:
            current["access_vlan"] = int(vlan.group(1))
            continue
        encap = re.match(r"(?i)^encapsulation\s+dot1[qQ]\s+(\d+)\s*$", line)
        if encap:
            current["dot1q"] = int(encap.group(1))
            continue
        addr = re.match(
            r"(?i)^ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
            line,
        )
        if addr and "secondary" not in line.lower():
            current["address"] = addr.group(1)
            current["mask"] = addr.group(2)
    close()
    return rows


def _block_network(row: dict) -> ipaddress.IPv4Network | None:
    if not row.get("address") or not row.get("mask"):
        return None
    try:
        return ipaddress.ip_network(f"{row['address']}/{row['mask']}", strict=False)
    except ValueError:
        return None


def _vlan_number(name: str) -> int | None:
    match = re.fullmatch(r"(?i)vlan(\d+)", name)
    if not match:
        return None
    return int(match.group(1))


def _resolve_device(token: str, names: list[str]) -> str | None:
    folded = {name.lower(): name for name in names}
    raw = token.strip().rstrip(".")
    if raw.lower() in folded:
        return folded[raw.lower()]
    short = raw.split(".", 1)[0]
    if short.lower() in folded:
        return folded[short.lower()]
    return None


def _neighbors(text: str) -> list[tuple[str, str, str, str]]:
    found: list[tuple[str, str, str, str]] = []
    if not text.strip():
        return found
    for line in text.splitlines():
        row = _CDP_ROW.match(line.strip())
        if row:
            found.append((row.group("local"), row.group("device"), row.group("remote"), "cdp"))
    blocks = re.split(r"\n\s*\n|^-{4,}.*$", text, flags=re.MULTILINE)
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        local = name = port = None
        detail_dev = None
        detail_local = None
        detail_remote = None
        for line in lines:
            got = _LLDP_LOCAL.match(line)
            if got:
                local = got.group(1)
            got = _LLDP_NAME.match(line)
            if got:
                name = got.group(1)
            got = _LLDP_PORT.match(line)
            if got:
                port = got.group(1)
            got = _CDP_DETAIL_DEV.match(line)
            if got:
                detail_dev = got.group(1)
            got = _CDP_DETAIL_PORTS.match(line)
            if got:
                detail_local, detail_remote = got.group(1), got.group(2)
        if local and name and port:
            found.append((local, name, port, "lldp"))
        if detail_dev and detail_local and detail_remote:
            found.append((detail_local, detail_dev, detail_remote, "cdp"))
    return found
