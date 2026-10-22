"""Read interface facts out of a vendor-style config.

The grammar is intentionally small: hostname, interface blocks, addresses,
descriptions, and admin state. It is used to draw the canvas and to guess
cables. Forwarding results come from the analysis engine, not from this parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ALIAS_PAIRS: list[tuple[str, str]] = [
    ("tengigabitethernet", "TenGigabitEthernet"),
    ("gigabitethernet", "GigabitEthernet"),
    ("fastethernet", "FastEthernet"),
    ("port-channel", "Port-channel"),
    ("portchannel", "Port-channel"),
    ("ethernet", "Ethernet"),
    ("loopback", "Loopback"),
    ("gig", "GigabitEthernet"),
    ("fas", "FastEthernet"),
    ("ten", "TenGigabitEthernet"),
    ("eth", "Ethernet"),
    ("vlan", "Vlan"),
    ("gi", "GigabitEthernet"),
    ("fa", "FastEthernet"),
    ("te", "TenGigabitEthernet"),
    ("et", "Ethernet"),
    ("po", "Port-channel"),
    ("lo", "Loopback"),
    ("vl", "Vlan"),
]
_ALIASES = sorted(_ALIAS_PAIRS, key=lambda item: len(item[0]), reverse=True)

_INTERFACE_RE = re.compile(
    r"(?:TenGigabitEthernet|GigabitEthernet|FastEthernet|Port-channel|Ethernet|"
    r"Loopback|Vlan|Te|Ten|Gi|Gig|Fa|Fas|Eth|Et|Po|Lo|Vl)\s*\d\S*",
    re.IGNORECASE,
)


@dataclass
class Iface:
    name: str
    description: str = ""
    address: str | None = None
    mask: str | None = None
    prefix: int | None = None
    network: str | None = None
    shutdown: bool = False
    physical: bool = False


@dataclass
class ParsedConfig:
    hostname: str | None
    interfaces: list[Iface] = field(default_factory=list)

    def get(self, name: str) -> Iface | None:
        want = canonical_interface(name)
        for iface in self.interfaces:
            if iface.name == want:
                return iface
        return None


def canonical_interface(name: str) -> str:
    compact = re.sub(r"\s+", "", name.strip())
    low = compact.lower()
    for alias, canon in _ALIASES:
        if not low.startswith(alias):
            continue
        rest = compact[len(alias) :]
        if rest and rest[0].isdigit():
            return canon + rest
    return compact


def is_physical(name: str) -> bool:
    canon = canonical_interface(name)
    if "." in canon:
        return False
    return canon.startswith(
        ("GigabitEthernet", "TenGigabitEthernet", "FastEthernet", "Ethernet")
    )


def parse_config(text: str) -> ParsedConfig:
    hostname: str | None = None
    interfaces: list[Iface] = []
    current: Iface | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            interfaces.append(current)
            current = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        if line.lower() == "end":
            close()
            break
        host = re.match(r"(?i)^hostname\s+(\S+)", line)
        if host and current is None:
            hostname = host.group(1)
            continue
        iface = re.match(r"(?i)^interface\s+(\S+)", line)
        if iface:
            close()
            name = canonical_interface(iface.group(1))
            current = Iface(name=name, physical=is_physical(name))
            continue
        if current is None:
            continue
        desc = re.match(r"(?i)^description\s+(.+)$", line)
        if desc:
            current.description = desc.group(1).strip()
            continue
        if re.match(r"(?i)^shutdown$", line):
            current.shutdown = True
            continue
        if re.match(r"(?i)^no\s+shutdown$", line):
            current.shutdown = False
            continue
        addr = re.match(
            r"(?i)^ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
            line,
        )
        if addr and "secondary" not in line.lower():
            current.address = addr.group(1)
            current.mask = addr.group(2)
            current.prefix = _prefix_len(addr.group(2))
            current.network = _network(addr.group(1), addr.group(2))
    close()
    return ParsedConfig(hostname=hostname, interfaces=interfaces)


def interface_pattern() -> re.Pattern[str]:
    return _INTERFACE_RE


def _prefix_len(mask: str) -> int:
    bits = 0
    for part in mask.split("."):
        bits = (bits << 8) | int(part)
    return bin(bits).count("1")


def _network(address: str, mask: str) -> str:
    addr = _octets(address)
    m = _octets(mask)
    net = ".".join(str(a & b) for a, b in zip(addr, m))
    return f"{net}/{_prefix_len(mask)}"


def _octets(text: str) -> list[int]:
    return [int(part) for part in text.split(".")]
