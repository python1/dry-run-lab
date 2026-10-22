"""Format analysis rows so they read like a device CLI transcript.

Every string this module returns is computed. Callers print the simulated
banner above it.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from dryrun_lab.nsort import interface_key

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
    missed = [row for row in unsimulated if row.get("kind") not in {"ignored", "limit", "unreachable"}]
    ignored = [row for row in unsimulated if row.get("kind") == "ignored"]
    unreachable = [row for row in unsimulated if row.get("kind") == "unreachable"]
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
    if unreachable:
        lines.append(f"! {len(unreachable)} ACL line(s) will never match.")
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
    ordered = sorted(rows, key=lambda row: interface_key(str(row.get("name") or "")))
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
    limits = [row for row in rows if row.get("kind") == "limit"]
    unreachable = [row for row in rows if row.get("kind") == "unreachable"]
    missed = [row for row in rows if row.get("kind") not in {"ignored", "limit", "unreachable"}]
    if not ignored and not missed and not limits and not unreachable:
        return f"No unparsed lines were reported for {device}\n"
    lines: list[str] = []
    if unreachable:
        lines.append(f"Will never match on {device}")
        lines.append("")
        for row in unreachable:
            lines.append(f"  {row.get('text') or ''}".rstrip())
            if row.get("detail"):
                lines.append(f"    {row['detail']}")
    if missed:
        if lines:
            lines.append("")
        lines.append(f"These lines were NOT simulated on {device}")
        lines.append("")
        lines.extend(_warning_lines(missed))
    if ignored:
        if lines:
            lines.append("")
        lines.append(f"Ignored when ip routing is enabled on {device}")
        lines.append("")
        lines.extend(_warning_lines(ignored))
    if limits:
        if lines:
            lines.append("")
        lines.append(f"Not modeled on {device}")
        lines.append("")
        lines.extend(_warning_lines(limits))
    return "\n".join(lines) + "\n"


def show_vlan_brief(rows: list[dict[str, Any]], names: dict[int, str]) -> str:
    header = f"{'VLAN':<6} {'Name':<32} {'Status':<9} Ports"
    lines = [header, f"{'----':<6} {'-' * 32} {'-' * 9} {'-' * 24}"]
    by_id: dict[int, list[str]] = {}
    for row in rows:
        vlan_id = _int(row.get("vlan"))
        ports = [_short_interface(name) for name in row.get("ports") or []]
        by_id.setdefault(vlan_id, [])
        for port in ports:
            if port not in by_id[vlan_id]:
                by_id[vlan_id].append(port)
    for vlan_id, name in names.items():
        by_id.setdefault(vlan_id, [])
        names.setdefault(vlan_id, name)
    if not by_id:
        return "No switched VLANs were computed for this device.\n"
    for vlan_id in sorted(by_id):
        ports = sorted(by_id[vlan_id], key=interface_key)
        lines.append(
            f"{vlan_id:<6} {(names.get(vlan_id) or '')[:32]:<32} {'active':<9} {', '.join(ports)}"
        )
    return "\n".join(lines) + "\n"


def show_interfaces_trunk(rows: list[dict[str, Any]]) -> str:
    trunks = [row for row in rows if str(row.get("mode") or "").upper() == "TRUNK"]
    trunks.sort(key=lambda row: interface_key(str(row.get("name") or "")))
    if not trunks:
        return "No trunk interfaces were computed for this device.\n"
    lines = [
        f"{'Port':<18} {'Mode':<8} {'Encapsulation':<16} {'Status':<12} Native vlan",
    ]
    for row in trunks:
        active = bool(row.get("active")) and bool(row.get("admin_up", True))
        status = "trunking" if active else "down"
        native = row.get("native") if row.get("native") is not None else ""
        lines.append(
            f"{_short_interface(str(row.get('name') or '')):<18} {'on':<8} {'802.1q':<16} {status:<12} {native}"
        )
    lines.append("")
    lines.append(f"{'Port':<18} Vlans allowed on trunk")
    for row in trunks:
        allowed = row.get("allowed") or ""
        lines.append(f"{_short_interface(str(row.get('name') or '')):<18} {allowed}")
    return "\n".join(lines) + "\n"


def show_access_lists(config: str, interfaces: list[dict[str, Any]]) -> str:
    from dryrun_lab.acls import parse_acls

    lists = parse_acls(config)
    if not lists:
        return "No access lists are configured on this device.\n"
    applied: dict[str, list[str]] = {}
    for row in interfaces:
        name = str(row.get("name") or "")
        inbound = row.get("filter_in")
        outbound = row.get("filter_out")
        if inbound:
            applied.setdefault(str(inbound), []).append(f"inbound on {name}")
        if outbound:
            applied.setdefault(str(outbound), []).append(f"outbound on {name}")
    lines: list[str] = []
    for acl in lists:
        lines.append(f"{acl.kind.capitalize()} IP access list {acl.name}")
        for ace in acl.aces:
            lines.append(f"    {ace.seq} {ace.text}")
        for note in applied.get(acl.name, []):
            lines.append(f"  {note}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_ping(dst: str, src: str | None, ingress: str | None, trace: dict[str, Any], drop: str | None) -> str:
    ok = trace.get("disposition") in {"ACCEPTED", "DELIVERED_TO_SUBNET", "EXITS_NETWORK"}
    where = f"to {dst}"
    if src:
        where += f" source {src}"
    if ingress:
        where += f" ingress {ingress}"
    lines = [
        "Computed ping. Not a packet on a live network.",
        where,
        "!!!!!" if ok else ".....",
        f"Success rate is {'100 percent (5/5)' if ok else '0 percent (0/5)'}",
        f"Disposition: {trace.get('disposition') or trace.get('error') or 'none'}",
        explain_disposition(trace, drop, dst),
        _format_steps(trace),
    ]
    if drop:
        lines.append(drop.rstrip("\n"))
    if trace.get("l2"):
        lines.append(str(trace["l2"]))
    return "\n".join(lines).rstrip() + "\n"


def format_traceroute(dst: str, src: str | None, ingress: str | None, trace: dict[str, Any], drop: str | None) -> str:
    where = f"to {dst}"
    if src:
        where += f" source {src}"
    if ingress:
        where += f" ingress {ingress}"
    lines = [
        "Computed traceroute. Not a packet on a live network.",
        where,
        f"Disposition: {trace.get('disposition') or trace.get('error') or 'none'}",
        explain_disposition(trace, drop, dst),
        _format_steps(trace),
    ]
    if drop:
        lines.append(drop.rstrip("\n"))
    if trace.get("l2"):
        lines.append(str(trace["l2"]))
    return "\n".join(lines).rstrip() + "\n"


def explain_disposition(trace: dict[str, Any], drop: str | None, dst: str) -> str:
    """One sentence under the disposition. It names the interface or ACL sequence."""
    disposition = str(trace.get("disposition") or "NONE").upper()
    steps = trace.get("steps") or []
    denied = disposition in {"DENIED_IN", "DENIED_OUT", "DENIED"} or any(
        str(step.get("action") or "").upper() == "DENIED" for step in steps
    )
    if denied:
        return _deny_sentence(steps, drop, disposition)
    if disposition == "ACCEPTED":
        node, iface = _located(steps, "ACCEPTED", "interface")
        if node and iface:
            return f"Delivered to {node} on {_short_interface(iface)}."
        return "Delivered to the destination."
    if disposition == "DELIVERED_TO_SUBNET":
        node, iface = _located(steps, "DELIVERED_TO_SUBNET", "outputInterface", "interface")
        where = _where(node, iface)
        return f"Delivered onto the subnet out {where}."
    if disposition == "EXITS_NETWORK":
        node, iface = _located(steps, "EXITS_NETWORK", "outputInterface", "interface")
        return f"The trace leaves the lab on {_where(node, iface)}."
    if disposition == "NO_ROUTE":
        node, _iface = _located(steps, "NO_ROUTE", "outputInterface", "interface")
        return f"No route for {dst} on {node or 'the device'}."
    if disposition == "NULL_ROUTED":
        node, _iface = _located(steps, "NULL_ROUTED", "outputInterface", "interface")
        return f"Discarded by a null route for {dst} on {node or 'the device'}."
    if disposition == "NEIGHBOR_UNREACHABLE":
        step = _action_step(steps, "NEIGHBOR_UNREACHABLE")
        detail = (step or {}).get("detail") or {}
        node = str((step or {}).get("node") or "the device")
        iface = str(detail.get("outputInterface") or detail.get("interface") or "")
        neighbor = detail.get("resolvedNexthopIp") or detail.get("arpIp") or "the next hop"
        return f"No neighbor answered for {neighbor} on {_where(node, iface)}."
    if disposition == "NO_ACTIVE_LOCATION":
        return "No active location. The interface where this trace starts is shut or not up."
    if disposition == "INSUFFICIENT_INFO":
        return "The engine did not have enough information to finish this trace."
    if disposition == "LOOP":
        return "The trace looped and was stopped."
    error = trace.get("error")
    if error:
        return f"No trace was computed. {error}"
    return "No trace was computed."


def _deny_sentence(steps: list[dict[str, Any]], drop: str | None, disposition: str) -> str:
    node = "the device"
    iface = ""
    acl = ""
    for step in steps:
        if str(step.get("action") or "").upper() != "DENIED":
            continue
        node = str(step.get("node") or node)
        detail = step.get("detail") or {}
        acl = str(detail.get("filter") or acl)
        prefer = "outputInterface" if disposition == "DENIED_OUT" else "inputInterface"
        iface = str(detail.get(prefer) or detail.get("inputInterface") or detail.get("outputInterface") or iface)
    sequence = ""
    ace = ""
    if drop:
        named = re.search(r"ACL\s+(\S+)", drop)
        if named:
            acl = named.group(1)
        lined = re.search(r"sequence\s+(\d+):\s*(.+)", drop)
        if lined:
            sequence = lined.group(1)
            ace = lined.group(2).strip()
    src, dest = _ace_endpoints(ace) if ace else (None, None)
    where = _where(node, iface)
    label = f"ACL {acl}" if acl else "a filter"
    if sequence:
        label = f"{label} sequence {sequence}"
    if src and dest:
        return f"Dropped because {label} on {where} denies {src} to {dest}."
    return f"Dropped because {label} on {where} denies this flow."


def _ace_endpoints(ace: str) -> tuple[str | None, str | None]:
    parts = ace.split()
    if len(parts) < 4:
        return None, None
    rest = parts[2:]
    src, rest = _take_endpoint(rest)
    dest, _rest = _take_endpoint(rest)
    return src, dest


def _take_endpoint(tokens: list[str]) -> tuple[str | None, list[str]]:
    if not tokens:
        return None, tokens
    if tokens[0].lower() == "any":
        return "any", tokens[1:]
    if tokens[0].lower() == "host" and len(tokens) > 1:
        return tokens[1], tokens[2:]
    if len(tokens) > 1 and _IP.fullmatch(tokens[0]) and _IP.fullmatch(tokens[1]):
        return _wildcard_prefix(tokens[0], tokens[1]), tokens[2:]
    if _IP.fullmatch(tokens[0]):
        return tokens[0], tokens[1:]
    return tokens[0], tokens[1:]


def _wildcard_prefix(address: str, wildcard: str) -> str:
    try:
        inverted = int(ipaddress.ip_address(wildcard)) ^ 0xFFFFFFFF
        mask = ipaddress.ip_address(inverted)
        network = ipaddress.ip_network(f"{address}/{mask}", strict=False)
    except ValueError:
        return f"{address} {wildcard}"
    return str(network)


def _action_step(steps: list[dict[str, Any]], action: str) -> dict[str, Any] | None:
    for step in steps:
        if str(step.get("action") or "").upper() == action:
            return step
    return steps[-1] if steps else None


def _located(steps: list[dict[str, Any]], action: str, *keys: str) -> tuple[str, str]:
    step = _action_step(steps, action)
    if step is None:
        return "", ""
    detail = step.get("detail") or {}
    iface = ""
    for key in keys:
        if detail.get(key):
            iface = str(detail[key])
            break
    return str(step.get("node") or ""), iface


def _where(node: str, iface: str) -> str:
    if node and iface:
        return f"{node} {_short_interface(iface)}"
    return node or iface or "the device"


def format_change_diff(
    routes_before: dict[str, list[dict[str, Any]]],
    routes_after: dict[str, list[dict[str, Any]]],
    warnings_before: list[dict[str, Any]],
    warnings_after: list[dict[str, Any]],
    reach_before: dict[str, str],
    reach_after: dict[str, str],
    applied: int,
    headline: str | None = None,
    notices: list[str] | None = None,
) -> str:
    lines = [headline or f"Applied {applied} line(s). Recomputed."]
    for notice in notices or []:
        lines.append(notice)
    lines.extend(["", "Routes"])
    route_lines = _diff_routes(routes_before, routes_after)
    lines.extend(route_lines or ["  (no route changes)"])
    lines.append("")
    lines.append("Warnings")
    warning_lines = _diff_warnings(warnings_before, warnings_after)
    lines.extend(warning_lines or ["  (no warning changes)"])
    lines.append("")
    lines.append("Reachability")
    reach_lines = _diff_reach(reach_before, reach_after)
    lines.extend(reach_lines or ["  (no reachability changes)"])
    return "\n".join(lines) + "\n"


def parse_flow(command: str) -> dict[str, str | None] | None:
    parts = command.strip().split()
    if not parts or parts[0].lower() not in {"ping", "traceroute"}:
        return None
    rest = parts[1:]
    if rest and rest[0].lower() == "ip":
        rest = rest[1:]
    if not rest or not _IP.fullmatch(rest[0]):
        return None
    src: str | None = None
    ingress: str | None = None
    index = 1
    while index < len(rest):
        token = rest[index].lower()
        if token == "source" and index + 1 < len(rest) and _IP.fullmatch(rest[index + 1]):
            src = rest[index + 1]
            index += 2
            continue
        if token == "ingress" and index + 1 < len(rest):
            ingress = rest[index + 1]
            index += 2
            continue
        return None
    return {"kind": parts[0].lower(), "dst": rest[0], "src": src, "ingress": ingress}


def vlan_names(config: str) -> dict[int, str]:
    names: dict[int, str] = {}
    current: int | None = None
    for raw in config.splitlines():
        line = raw.strip()
        match = re.fullmatch(r"(?i)vlan\s+(\d+)", line)
        if match and not raw[:1].isspace():
            current = int(match.group(1))
            names.setdefault(current, "")
            continue
        named = re.match(r"(?i)^name\s+(\S+)", line)
        if named and current is not None:
            names[current] = named.group(1)
            continue
        if line and not raw[:1].isspace() and not line.lower().startswith("name "):
            if not re.fullmatch(r"(?i)vlan\s+\d+", line):
                current = None
    return names


def _format_steps(trace: dict[str, Any]) -> str:
    steps = trace.get("steps") or []
    if not steps:
        if trace.get("error"):
            return str(trace["error"])
        return "(no hops)"
    lines = []
    for index, step in enumerate(steps, start=1):
        action = step.get("action") or ""
        detail = _step_detail(step.get("detail"))
        node = step.get("node") or ""
        lines.append(f"  {index} {node} {action} {detail}".rstrip())
    return "\n".join(lines)


def _step_detail(detail: Any) -> str:
    if not isinstance(detail, dict):
        return str(detail or "")
    parts: list[str] = []
    for key in ("inputInterface", "outputInterface", "interface", "filter", "filterType"):
        if detail.get(key):
            parts.append(f"{key} {detail[key]}")
    return " ".join(parts)


def _diff_routes(
    before: dict[str, list[dict[str, Any]]],
    after: dict[str, list[dict[str, Any]]],
) -> list[str]:
    lines: list[str] = []
    nodes = sorted(set(before) | set(after))
    for node in nodes:
        old = {_route_key(row): row for row in before.get(node, [])}
        new = {_route_key(row): row for row in after.get(node, [])}
        removed = [old[key] for key in old if key not in new]
        added = [new[key] for key in new if key not in old]
        if not removed and not added:
            continue
        lines.append(f"  {node}")
        for row in removed:
            lines.append(f"    - {_one_route(row)}")
        for row in added:
            lines.append(f"    + {_one_route(row)}")
    return lines


def _one_route(row: dict[str, Any]) -> str:
    net = str(row.get("network") or "")
    code = _PROTOCOL.get(str(row.get("protocol") or "").lower(), "?")
    via_ip, via_iface = _split_hop(row.get("next_hop"))
    if code in {"C", "L"} and via_iface:
        return f"{code} {net} is directly connected, {via_iface}"
    if via_ip and via_iface:
        return f"{code} {net} via {via_ip}, {via_iface}"
    if via_ip:
        return f"{code} {net} via {via_ip}"
    if via_iface:
        return f"{code} {net} via {via_iface}"
    return f"{code} {net}"


def _route_key(row: dict[str, Any]) -> tuple[str, str, str]:
    via_ip, via_iface = _split_hop(row.get("next_hop"))
    return (str(row.get("network") or ""), str(row.get("protocol") or "").lower(), f"{via_ip or ''}|{via_iface or ''}")


def _warning_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("device") or ""),
        str(row.get("text") or "").strip(),
        str(row.get("detail") or "").strip(),
        str(row.get("kind") or ""),
    )


def _diff_warnings(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    old = {_warning_key(row): row for row in before}
    new = {_warning_key(row): row for row in after}
    lines: list[str] = []
    for key in old:
        if key not in new:
            row = old[key]
            lines.append(f"  - {row.get('device') or '?'} {row.get('text')} ({row.get('detail')})")
    for key in new:
        if key not in old:
            row = new[key]
            lines.append(f"  + {row.get('device') or '?'} {row.get('text')} ({row.get('detail')})")
    return lines


def _diff_reach(before: dict[str, str], after: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for key in sorted(set(before) | set(after)):
        left = before.get(key, "not present")
        right = after.get(key, "not present")
        if left == right:
            continue
        lines.append(f"  {key}")
        lines.append(f"    before: {left}")
        lines.append(f"    after:  {right}")
    return lines


def _short_interface(name: str) -> str:
    return (
        name.replace("TenGigabitEthernet", "Te")
        .replace("GigabitEthernet", "Gi")
        .replace("FastEthernet", "Fa")
    )


_IP = re.compile(r"\d+\.\d+\.\d+\.\d+")


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
        "show vlan brief": "vlan",
        "show vlan": "vlan",
        "sh vlan brief": "vlan",
        "sh vlan": "vlan",
        "show interfaces trunk": "trunk",
        "show interface trunk": "trunk",
        "show int trunk": "trunk",
        "sh interfaces trunk": "trunk",
        "sh int trunk": "trunk",
        "show access-lists": "acl",
        "show access-list": "acl",
        "show ip access-lists": "acl",
        "sh access-lists": "acl",
        "sh ip access-lists": "acl",
    }
    return table.get(folded)


def command_help() -> str:
    return (
        "This device CLI can compute:\n"
        "  show running-config\n"
        "  show ip interface brief\n"
        "  show ip route\n"
        "  show vlan brief\n"
        "  show interfaces trunk\n"
        "  show access-lists\n"
        "  show warnings\n"
        "  ping DESTINATION [source ADDRESS] [ingress INTERFACE]\n"
        "  traceroute DESTINATION [source ADDRESS] [ingress INTERFACE]\n"
        "  configure terminal ... end\n"
        "  revert\n"
        "Ping, traceroute, and show results are computed. Pipes are not available.\n"
        "revert restores the previous config on this device and recomputes.\n"
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
