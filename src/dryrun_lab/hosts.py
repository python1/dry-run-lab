"""Turn a host device into the analyzer's host file.

Only a host with an address is written. The file is generated here from the
host's config. Suggested cables are not attachments; a host with no confirmed
link is reported as not modeled.
"""

from __future__ import annotations

import re
from typing import Any

from dryrun_lab.configparse import parse_config
from dryrun_lab.store import Lab

_GATEWAY = re.compile(r"(?i)^ip\s+default-gateway\s+(\d+\.\d+\.\d+\.\d+)\s*$")


def host_config(name: str, cidr: str, gateway: str) -> str:
    """Config text for one host: Ethernet0, an address, and a default gateway."""
    import ipaddress

    try:
        iface = ipaddress.ip_interface(cidr)
    except ValueError as exc:
        raise ValueError("Address must look like 10.40.40.50/24") from exc
    if not isinstance(iface, ipaddress.IPv4Interface):
        raise ValueError("Address must be IPv4")
    if iface.network.prefixlen >= 31:
        raise ValueError("Address needs a prefix length of 30 or less")
    try:
        gw = ipaddress.ip_address(gateway)
    except ValueError as exc:
        raise ValueError("Gateway must be an IPv4 address") from exc
    if not isinstance(gw, ipaddress.IPv4Address):
        raise ValueError("Gateway must be an IPv4 address")
    return (
        f"hostname {name}\n"
        "!\n"
        "interface Ethernet0\n"
        f" ip address {iface.ip} {iface.netmask}\n"
        "!\n"
        f"ip default-gateway {gw}\n"
        "!\n"
        "end\n"
    )


def gateway_address(config: str) -> str | None:
    for raw in config.replace("\r\n", "\n").split("\n"):
        match = _GATEWAY.match(raw.strip())
        if match:
            return match.group(1)
    return None


def host_document(name: str, config: str) -> dict[str, Any] | None:
    parsed = parse_config(config)
    gateway = gateway_address(config)
    interfaces: dict[str, dict[str, str]] = {}
    for iface in parsed.interfaces:
        if not iface.address or iface.prefix is None:
            continue
        entry = {"name": iface.name, "prefix": f"{iface.address}/{iface.prefix}"}
        if gateway:
            entry["gateway"] = gateway
        interfaces[iface.name] = entry
    if not interfaces:
        return None
    return {"hostname": name.lower(), "hostInterfaces": interfaces}


def host_limits(lab: Lab) -> list[dict[str, Any]]:
    """Limits this lab adds. These are not lines the engine failed to parse."""
    rows: list[dict[str, Any]] = []
    confirmed = [link for link in lab.links if link.status == "confirmed"]
    for device in lab.devices:
        if device.role != "host":
            continue
        parsed = parse_config(device.config)
        addressed = [iface for iface in parsed.interfaces if iface.address]
        attached = False
        for iface in parsed.interfaces:
            for link in confirmed:
                ends = {
                    (link.a_device.lower(), link.a_interface),
                    (link.b_device.lower(), link.b_interface),
                }
                if (device.name.lower(), iface.name) in ends:
                    attached = True
        if not addressed:
            rows.append(
                {
                    "file": "",
                    "line": None,
                    "text": "no address on this host",
                    "detail": "No address is set, so this host is not in the snapshot.",
                    "kind": "limit",
                    "device": device.name,
                }
            )
            continue
        if not attached:
            rows.append(
                {
                    "file": "",
                    "line": None,
                    "text": "no confirmed link",
                    "detail": (
                        "No confirmed link attaches this host. "
                        "Suggested links are not used."
                    ),
                    "kind": "limit",
                    "device": device.name,
                }
            )
        if gateway_address(device.config) is None:
            rows.append(
                {
                    "file": "",
                    "line": None,
                    "text": "no default gateway",
                    "detail": (
                        "No default gateway is set on this host. "
                        "Only its own subnet can be reached."
                    ),
                    "kind": "limit",
                    "device": device.name,
                }
            )
    return rows
