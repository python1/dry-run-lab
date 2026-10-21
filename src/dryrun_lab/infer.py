"""Guess cables from configs and pasted neighbor text.

Suggestions are not installed as topology until someone confirms them.
A shared subnet with more than two members, or a prefix shorter than /30,
is reported as a note instead of a cable.
"""

from __future__ import annotations

import hashlib
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
