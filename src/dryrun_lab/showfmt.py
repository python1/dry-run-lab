"""Format analysis rows so they read like a device CLI transcript.

Every string this module returns is computed. Callers print the simulated
banner above it.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

_PROTOCOL = {
    "connected": "C",
    "local": "L",
    "static": "S",
    "ospf": "O",
    "ospfia": "O",
    "ospfe1": "O",
    "ospfe2": "O",
    "ospfis": "O",
    "bgp": "B",
}


def show_running_config(config: str, unsimulated: list[dict[str, Any]]) -> str:
    missed = [row for row in unsimulated if row.get("kind") != "ignored"]
    ignored = [row for row in unsimulated if row.get("kind") == "ignored"]
    lines = [
        "! Loaded config. This is the text the lab simulated, not a live readout.",
    ]
    if missed:
        lines.append(
            f"! {len(missed)} line(s) were NOT simulated. "
            "See the warning list for the text."
        )
    else:
        lines.append("! No unparsed lines were reported for this device.")
    if ignored:
        lines.append(
            f"! {len(ignored)} line(s) ignored when ip routing is enabled."
        )
    lines.append("!")
    body = config.replace("\r\n", "\n").rstrip()
    return "\n".join(lines + [body, ""])


def show_ip_interface_brief(rows: list[dict[str, Any]]) -> str:
    header = (
        f"{'Interface':<26} {'IP-Address':<15} {'OK?':<3} {'Method':<6} "
        f"{'Status':<22} Protocol"
    )
    body = [header]
    ordered = sorted(rows, key=lambda row: str(row.get("name") or ""))
    if not ordered:
        body.append("% No interfaces were computed for this device.")
    for row in ordered:
        address = row.get("address") or "unassigned"
        if isinstance(address, str) and "/" in address:
            address = address.split("/", 1)[0]
        admin = bool(row.get("admin_up", True))
        active = bool(row.get("active"))
        if not admin:
            status, protocol, ok = "administratively down", "down", "YES"
        elif active:
            status, protocol, ok = "up", "up", "YES"
        else:
            status, protocol, ok = "down", "down", "YES"
        body.append(
            f"{str(row.get('name') or ''):<26} {address:<15} {ok:<3} {'sim':<6} "
            f"{status:<22} {protocol}"
        )
    return "\n".join(body) + "\n"


def show_ip_route(rows: list[dict[str, Any]]) -> str:
    lines = [
        "Codes: L - local, C - connected, S - static, O - OSPF, B - BGP",
        "       Codes are the simulator's classification of each computed route.",
        "",
    ]
    parsed: list[tuple[ipaddress.IPv4Network, dict[str, Any], str, str | None]] = []
    gateway = None
    for row in rows:
        network = str(row.get("network") or "")
        try:
            net = ipaddress.ip_network(network)
        except ValueError:
            continue
        hop = _split_hop(row.get("next_hop"))
        if net.prefixlen == 0 and hop[0]:
            gateway = hop[0]
        parsed.append((net, row, hop[0] or "", hop[1]))
    if gateway:
        lines.append(f"Gateway of last resort is {gateway} to network 0.0.0.0")
    else:
        lines.append("Gateway of last resort is not set")
    lines.append("")
    parsed.sort(key=lambda item: (int(item[0].network_address), item[0].prefixlen))
    if not parsed:
        lines.append("% No routes were computed for this device.")
    for net, row, via_ip, via_iface in parsed:
        code = _PROTOCOL.get(str(row.get("protocol") or "").lower(), "?")
        star = "*" if net.prefixlen == 0 else " "
        metric = _int(row.get("metric"))
        distance = _int(row.get("admin_distance"))
        if code in {"C", "L"} and via_iface:
            lines.append(
                f"{code}{star}    {net} is directly connected, {via_iface}"
            )
        elif via_ip and via_iface:
            lines.append(
                f"{code}{star}    {net} [{distance}/{metric}] via {via_ip}, {via_iface}"
            )
        elif via_ip:
            lines.append(f"{code}{star}    {net} [{distance}/{metric}] via {via_ip}")
        elif via_iface:
            lines.append(f"{code}{star}    {net} [{distance}/{metric}] via {via_iface}")
        else:
            lines.append(f"{code}{star}    {net} [{distance}/{metric}]")
    return "\n".join(lines) + "\n"


def _warning_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        where = f"line {row.get('line')}" if row.get("line") else "line ?"
        lines.append(f"  {where}: {row.get('text') or ''}".rstrip())
        if row.get("detail"):
            lines.append(f"    {row['detail']}")
    return lines


def show_unsimulated(device: str, rows: list[dict[str, Any]]) -> str:
    ignored = [row for row in rows if row.get("kind") == "ignored"]
    missed = [row for row in rows if row.get("kind") != "ignored"]
    if not ignored and not missed:
        return f"No unparsed lines were reported for {device}\n"
    lines: list[str] = []
    if missed:
        lines.append(f"These lines were NOT simulated on {device}")
        lines.append("")
        lines.extend(_warning_lines(missed))
    if ignored:
        if lines:
            lines.append("")
        lines.append(f"Ignored when ip routing is enabled on {device}")
        lines.append("")
        lines.extend(_warning_lines(ignored))
    return "\n".join(lines) + "\n"


def normalize_command(command: str) -> str | None:
    folded = " ".join(command.strip().split()).lower()
    if "|" in folded:
        return None
    table = {
        "show running-config": "running-config",
        "show run": "running-config",
        "sh running-config": "running-config",
        "sh run": "running-config",
        "show ip interface brief": "interfaces",
        "show ip int brief": "interfaces",
        "show ip int br": "interfaces",
        "sh ip int brief": "interfaces",
        "sh ip int br": "interfaces",
        "sh ip interface brief": "interfaces",
        "show ip route": "routes",
        "show ip routes": "routes",
        "sh ip route": "routes",
        "sh ip ro": "routes",
        "show warnings": "warnings",
        "show unsimulated": "warnings",
    }
    return table.get(folded)


def command_help() -> str:
    return (
        "This device CLI can compute:\n"
        "  show running-config\n"
        "  show ip interface brief\n"
        "  show ip route\n"
        "Pipes and configuration mode are not available in this version.\n"
    )


def _split_hop(hop: Any) -> tuple[str | None, str | None]:
    if isinstance(hop, dict):
        ip = hop.get("ip") or None
        iface = hop.get("interface") or None
        return (str(ip) if ip else None, str(iface) if iface else None)
    text = str(hop or "").strip()
    both = re.fullmatch(r"interface\s+(\S+)\s+ip\s+(\S+)", text)
    if both:
        return both.group(2), both.group(1)
    only_iface = re.fullmatch(r"interface\s+(\S+)", text)
    if only_iface:
        return None, only_iface.group(1)
    only_ip = re.fullmatch(r"ip\s+(\S+)", text)
    if only_ip:
        return only_ip.group(1), None
    return None, None


def _int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0
