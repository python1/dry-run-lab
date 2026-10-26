"""Unique-prefix command matching, the way IOS picks a keyword.

A token matches a keyword when it is a prefix of exactly one keyword at that
point. When it is a prefix of several, the next token selects the keyword
that can accept the rest of the line. `route` is not a prefix of `routing`,
so `ip route` is the route command. `ip rout 10.0.0.0 ...` is also the route
command, because `routing` does not take an address. A finished command with
extra tokens is rejected. Nothing here stores a line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dryrun_lab.configparse import canonical_interface

_IPV4 = re.compile(r"\d+\.\d+\.\d+\.\d+")
_VLANLIST = re.compile(r"\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")
_PROTOS = ("ip", "tcp", "udp", "icmp", "gre", "esp", "ahp", "eigrp", "ospf", "igmp", "pim")
_PORT_OPS = ("eq", "gt", "lt", "neq", "range")
_ACE_FLAGS = ("log-input", "log", "established", "fragments")
_ACE_PAIRS = ("precedence", "tos", "dscp", "time-range")


@dataclass
class _Node:
    kids: dict[str, _Node]
    arg: tuple[str, _Node] | None = None
    done: str | None = None

    def __init__(self) -> None:
        self.kids = {}
        self.arg = None
        self.done = None


@dataclass(frozen=True)
class Match:
    ok: bool
    canonical: str
    kind: str
    error: str | None


def _add(root: _Node, parts: list[str], kind: str) -> None:
    node = root
    for index, part in enumerate(parts):
        if part.startswith("$"):
            arg_kind = part[1:]
            if node.arg is None:
                child = _Node()
                node.arg = (arg_kind, child)
            else:
                existing, child = node.arg
                if existing != arg_kind:
                    raise RuntimeError(f"argument conflict at {parts[: index + 1]}")
            node = child
        else:
            node = node.kids.setdefault(part, _Node())
        if index == len(parts) - 1:
            node.done = kind


def _tree(paths: list[tuple[list[str], str]]) -> _Node:
    root = _Node()
    for parts, kind in paths:
        _add(root, parts, kind)
    return root


def _global_paths() -> list[tuple[list[str], str]]:
    applied = [
        (["hostname", "$word"], "applied"),
        (["interface", "$iface"], "stanza"),
        (["vlan", "$vlan"], "stanza"),
        (["ip", "access-list", "extended", "$name"], "stanza"),
        (["ip", "access-list", "standard", "$name"], "stanza"),
        (["ip", "access-list", "resequence", "$name", "$uint", "$uint"], "escape"),
        (["router", "ospf", "$uint"], "stanza"),
        (["ip", "route", "$ipv4", "$ipv4", "$ipv4"], "applied"),
        (["ip", "route", "$ipv4", "$ipv4", "$ipv4", "$uint"], "applied"),
        (["ip", "route", "$ipv4", "$ipv4", "$ipv4", "name", "$word"], "applied"),
        (["ip", "default-gateway", "$ipv4"], "applied"),
        (["ip", "routing"], "applied"),
        (["no", "ip", "routing"], "applied"),
        (["ip", "source-route"], "applied"),
        (["no", "ip", "source-route"], "applied"),
        (["ip", "cef"], "applied"),
        (["version", "$version"], "applied"),
    ]
    harmless = [
        "logging",
        "snmp-server",
        "ntp",
        "banner",
        "username",
        "line",
        "alias",
        "service",
        "clock",
        "boot",
        "license",
        "archive",
        "parser",
    ]
    featured = [( [word, "$rest"], "harmless") for word in harmless]
    featured.append((["enable", "secret", "$rest"], "harmless"))
    featured.append((["enable", "password", "$rest"], "harmless"))
    featured.append((["ip", "domain", "$rest"], "harmless"))
    featured.append((["no", "logging", "$rest"], "harmless"))
    unmodeled = [
        (["spanning-tree", "$rest"], "unmodeled"),
        (["no", "spanning-tree", "$rest"], "unmodeled"),
        (["storm-control", "$rest"], "unmodeled"),
        (["channel-group", "$rest"], "unmodeled"),
        (["udld", "$rest"], "unmodeled"),
        (["vtp", "mode", "$rest"], "unmodeled"),
        (["mls", "qos"], "unmodeled"),
        (["mls", "qos", "$rest"], "unmodeled"),
        (["policy-map", "$rest"], "unmodeled"),
        (["class-map", "$rest"], "unmodeled"),
        (["service-policy", "$rest"], "unmodeled"),
        (["mac", "access-group", "$rest"], "unmodeled"),
        (["ip", "dhcp", "snooping", "$rest"], "unmodeled"),
        (["ip", "dhcp", "snooping"], "unmodeled"),
        (["ip", "arp", "inspection", "$rest"], "unmodeled"),
        (["ip", "verify", "unicast", "$rest"], "unmodeled"),
        (["ip", "nat", "$rest"], "unmodeled"),
        (["ip", "helper-address", "$rest"], "unmodeled"),
        (["no", "ip", "helper-address"], "unmodeled"),
        (["no", "ip", "helper-address", "$rest"], "unmodeled"),
        (["ip", "directed-broadcast"], "unmodeled"),
        (["ip", "directed-broadcast", "$rest"], "unmodeled"),
        (["no", "ip", "directed-broadcast"], "unmodeled"),
        (["ip", "policy", "route-map", "$rest"], "unmodeled"),
        (["no", "ip", "policy", "route-map"], "unmodeled"),
        (["no", "ip", "policy", "route-map", "$rest"], "unmodeled"),
        (["vlan", "access-map", "$rest"], "unmodeled"),
        (["vlan", "filter", "$rest"], "unmodeled"),
        (["switchport", "port-security", "$rest"], "unmodeled"),
        (["switchport", "block", "$rest"], "unmodeled"),
    ]
    return applied + featured + unmodeled


def _interface_paths() -> list[tuple[list[str], str]]:
    return [
        (["shutdown"], "applied"),
        (["no", "shutdown"], "applied"),
        (["description", "$rest"], "applied"),
        (["ip", "address", "$ipv4", "$ipv4"], "applied"),
        (["ip", "address", "$ipv4", "$ipv4", "secondary"], "applied"),
        (["no", "ip", "address"], "applied"),
        (["encapsulation", "dot1Q", "$uint"], "applied"),
        (["switchport", "mode", "access"], "applied"),
        (["switchport", "mode", "trunk"], "applied"),
        (["switchport", "access", "vlan", "$vlan"], "applied"),
        (["switchport", "trunk", "encapsulation", "dot1q"], "applied"),
        (["switchport", "trunk", "allowed", "vlan", "$vlanlist"], "applied"),
        (["switchport", "trunk", "allowed", "vlan", "add", "$vlanlist"], "applied"),
        (["switchport", "trunk", "allowed", "vlan", "remove", "$vlanlist"], "applied"),
        (["switchport", "trunk", "allowed", "vlan", "except", "$vlanlist"], "applied"),
        (["switchport", "trunk", "native", "vlan", "$vlan"], "applied"),
        (["ip", "access-group", "$word", "in"], "applied"),
        (["ip", "access-group", "$word", "out"], "applied"),
        (["no", "ip", "access-group", "$word", "in"], "applied"),
        (["no", "ip", "access-group", "$word", "out"], "applied"),
        (["no", "switchport"], "applied"),
        (["spanning-tree", "$rest"], "unmodeled"),
        (["no", "spanning-tree", "$rest"], "unmodeled"),
        (["storm-control", "$rest"], "unmodeled"),
        (["switchport", "port-security", "$rest"], "unmodeled"),
        (["switchport", "block", "$rest"], "unmodeled"),
        (["channel-group", "$rest"], "unmodeled"),
        (["udld", "$rest"], "unmodeled"),
        (["mac", "access-group", "$rest"], "unmodeled"),
        (["service-policy", "$rest"], "unmodeled"),
        (["mls", "qos"], "unmodeled"),
        (["mls", "qos", "$rest"], "unmodeled"),
        (["ip", "helper-address", "$rest"], "unmodeled"),
        (["no", "ip", "helper-address"], "unmodeled"),
        (["no", "ip", "helper-address", "$rest"], "unmodeled"),
        (["ip", "directed-broadcast"], "unmodeled"),
        (["ip", "directed-broadcast", "$rest"], "unmodeled"),
        (["no", "ip", "directed-broadcast"], "unmodeled"),
        (["ip", "policy", "route-map", "$rest"], "unmodeled"),
        (["no", "ip", "policy", "route-map"], "unmodeled"),
        (["no", "ip", "policy", "route-map", "$rest"], "unmodeled"),
        (["standby", "$rest"], "unmodeled"),
        (["no", "standby"], "unmodeled"),
        (["no", "standby", "$rest"], "unmodeled"),
        (["vrrp", "$rest"], "unmodeled"),
        (["no", "vrrp"], "unmodeled"),
        (["no", "vrrp", "$rest"], "unmodeled"),
        (["glbp", "$rest"], "unmodeled"),
        (["no", "glbp"], "unmodeled"),
        (["no", "glbp", "$rest"], "unmodeled"),
        (["switchport", "voice", "$rest"], "unmodeled"),
        (["no", "switchport", "voice", "$rest"], "unmodeled"),
        (["dot1x", "$rest"], "unmodeled"),
        (["no", "dot1x", "$rest"], "unmodeled"),
        (["mab"], "unmodeled"),
        (["mab", "$rest"], "unmodeled"),
        (["no", "mab"], "unmodeled"),
        (["no", "mab", "$rest"], "unmodeled"),
        (["authentication", "$rest"], "unmodeled"),
        (["no", "authentication", "$rest"], "unmodeled"),
    ]


def _vlan_paths() -> list[tuple[list[str], str]]:
    return [(["name", "$word"], "applied")]


def _router_paths() -> list[tuple[list[str], str]]:
    return [
        (["router-id", "$ipv4"], "applied"),
        (["passive-interface", "default"], "applied"),
        (["passive-interface", "$iface"], "applied"),
        (["no", "passive-interface", "$iface"], "applied"),
        (["network", "$ipv4", "$ipv4", "area", "$uint"], "applied"),
    ]


def _show_paths() -> list[tuple[list[str], str]]:
    modeled = [
        (["show", "running-config"], "running-config"),
        (["show", "ip", "interface", "brief"], "interfaces"),
        (["show", "ip", "routes"], "routes"),
        (["show", "warnings"], "warnings"),
        (["show", "unsimulated"], "warnings"),
        (["show", "vlan"], "vlan"),
        (["show", "vlan", "brief"], "vlan"),
        (["show", "interfaces", "trunk"], "trunk"),
        (["show", "access-lists"], "acl"),
        (["show", "ip", "access-lists"], "acl"),
        (["show", "ip", "ospf", "neighbors"], "ospf-neighbor"),
    ]
    unmodeled = [
        "version",
        "spanning-tree",
        "arp",
        "inventory",
        "processes",
        "users",
        "logging",
        "clock",
    ]
    paths = list(modeled)
    for word in unmodeled:
        paths.append((["show", word], "unmodeled"))
    paths.extend(
        [
            (["show", "ip", "arp"], "unmodeled"),
            (["show", "ip", "protocols"], "unmodeled"),
            (["show", "ip", "bgp"], "unmodeled"),
            (["show", "ip", "interface"], "unmodeled"),
            (["show", "ip", "ospf", "interface"], "unmodeled"),
            (["show", "ip", "ospf", "database"], "unmodeled"),
            (["show", "interfaces"], "unmodeled"),
            (["show", "interfaces", "status"], "unmodeled"),
            (["show", "mac", "address-table"], "unmodeled"),
            (["show", "cdp", "neighbors"], "unmodeled"),
            (["show", "cdp"], "unmodeled"),
            (["show", "lldp", "neighbors"], "unmodeled"),
            (["show", "lldp"], "unmodeled"),
        ]
    )
    return paths


_GLOBAL = _tree(_global_paths())
_INTERFACE = _tree(_interface_paths())
_VLAN = _tree(_vlan_paths())
_ROUTER = _tree(_router_paths())
_SHOW = _tree(_show_paths())
_TREES = {
    "global": _GLOBAL,
    "interface": _INTERFACE,
    "vlan": _VLAN,
    "router": _ROUTER,
}


def match_config(context: str | None, line: str, acl_style: str = "extended") -> Match:
    """Accept a configuration line, or the IOS caret rejection."""
    mode = context or "global"
    if mode == "acl":
        ace = _match_ace(line, acl_style)
        if ace.ok:
            return ace
        opened = _match_tree(_GLOBAL, line)
        if opened.ok:
            return opened
        return ace
    found = _match_tree(_TREES.get(mode, _GLOBAL), line)
    if found.ok:
        return found
    if mode != "global":
        opened = _match_tree(_GLOBAL, line)
        if opened.ok:
            return opened
    return found


def leaves_mode(context: str | None, line: str, acl_style: str = "extended") -> bool:
    """A global command typed under a stanza returns the prompt to global config."""
    if not context or context == "global":
        return False
    if context == "acl":
        if _match_ace(line, acl_style).ok:
            return False
    else:
        if _match_tree(_TREES[context], line).ok:
            return False
    return _match_tree(_GLOBAL, line).ok


def match_show(command: str) -> str | None:
    """Kind of a supported show command, or None when this lab does not compute it."""
    text = " ".join(command.strip().split())
    if not text or "|" in text:
        return None
    found = _match_tree(_SHOW, text)
    if not found.ok or found.kind == "unmodeled":
        return None
    return found.kind


def _match_tree(root: _Node, line: str) -> Match:
    tokens = line.split()
    status, kind, parts, at = _walk(root, tokens, 0, [])
    if status == "ok" and kind:
        return Match(True, " ".join(parts), kind, None)
    return Match(False, "", "", _marked(line, _column(line, tokens, at, status)))


def _walk(
    node: _Node,
    tokens: list[str],
    index: int,
    built: list[str],
) -> tuple[str, str | None, list[str], int]:
    if index >= len(tokens):
        if node.done:
            return ("ok", node.done, built, index)
        return ("incomplete", None, built, index)
    token = tokens[index]
    low = token.lower()
    hits = [(key, child) for key, child in node.kids.items() if key.lower().startswith(low)]
    exact = [(key, child) for key, child in hits if key.lower() == low]
    if len(exact) == 1:
        hits = exact
    arg_hit: tuple[list[str], _Node, int] | None = None
    if node.arg is not None:
        arg_kind, child = node.arg
        taken = _take(arg_kind, tokens, index)
        if taken is not None:
            rendered, consumed = taken
            arg_hit = (rendered, child, consumed)
    if not hits and arg_hit is None:
        return ("invalid", None, built, index)
    if len(hits) > 1 and arg_hit is None and index + 1 >= len(tokens):
        return ("ambiguous", None, built, index)
    options: list[tuple[_Node, int, list[str]]] = []
    for key, child in hits:
        options.append((child, index + 1, built + [key]))
    if arg_hit is not None:
        rendered, child, consumed = arg_hit
        options.append((child, index + consumed, built + rendered))
    if len(options) == 1:
        child, nxt, new_built = options[0]
        return _walk(child, tokens, nxt, new_built)
    results = [_walk(child, tokens, nxt, new_built) for child, nxt, new_built in options]
    ready = [item for item in results if item[0] == "ok"]
    if len(ready) == 1:
        return ready[0]
    if len(ready) > 1:
        return ("ambiguous", None, built, index)
    viable: list[tuple[str, str | None, list[str], int]] = []
    for (child, nxt, _new_built), result in zip(options, results):
        status, _kind, _parts, at = result
        if status == "invalid" and at == nxt and child.done is not None:
            continue
        if status == "invalid" and at <= index:
            continue
        viable.append(result)
    if len(viable) == 1:
        return viable[0]
    if not viable:
        return max(results, key=lambda item: item[3])
    return ("ambiguous", None, built, index)


def _take(kind: str, tokens: list[str], index: int) -> tuple[list[str], int] | None:
    token = tokens[index]
    if kind == "rest":
        return tokens[index:], len(tokens) - index
    if kind == "ipv4" and _ipv4(token):
        return [token], 1
    if kind == "iface":
        canon = canonical_interface(token)
        if re.search(r"\d", canon):
            return [canon], 1
        return None
    if kind == "uint" and token.isdigit():
        return [token], 1
    if kind == "vlan" and token.isdigit() and 1 <= int(token) <= 4094:
        return [token], 1
    if kind == "word" and token:
        return [token], 1
    if kind == "name" and _NAME.fullmatch(token):
        return [token], 1
    if kind == "version" and _VERSION.fullmatch(token):
        return [token], 1
    if kind == "vlanlist" and _VLANLIST.fullmatch(token):
        return [token], 1
    return None


def _ipv4(token: str) -> bool:
    if not _IPV4.fullmatch(token):
        return False
    return all(0 <= int(piece) <= 255 for piece in token.split("."))


def _match_ace(line: str, style: str) -> Match:
    tokens = line.split()
    if not tokens:
        return Match(False, "", "", _marked(line, 0))
    index = 0
    prefix: list[str] = []
    if tokens[0].isdigit():
        prefix.append(tokens[0])
        index = 1
        if index >= len(tokens):
            return Match(False, "", "", _marked(line, _column(line, tokens, index, "incomplete")))
    action = _one(tokens[index], ("no", "permit", "deny", "remark"))
    if action is None:
        return Match(False, "", "", _marked(line, _column(line, tokens, index, "invalid")))
    if action == "no":
        return _ace_no(line, tokens, index + 1, prefix, style)
    if action == "remark":
        if index + 1 >= len(tokens):
            return Match(False, "", "", _marked(line, _column(line, tokens, index, "incomplete")))
        prefix.append("remark")
        prefix.extend(tokens[index + 1 :])
        return Match(True, " ".join(prefix), "applied", None)
    built, index, error = _ace_body(tokens, index + 1, action, style)
    if error is not None:
        return Match(False, "", "", _marked(line, _column(line, tokens, error[0], error[1])))
    return Match(True, " ".join(prefix + built), "applied", None)


def _ace_no(line: str, tokens: list[str], index: int, prefix: list[str], style: str) -> Match:
    if index >= len(tokens):
        return Match(False, "", "", _marked(line, _column(line, tokens, index, "incomplete")))
    if len(tokens) == index + 1 and tokens[index].isdigit():
        return Match(True, " ".join(prefix + ["no", tokens[index]]), "applied", None)
    action = _one(tokens[index], ("permit", "deny", "remark"))
    if action is None:
        return Match(False, "", "", _marked(line, _column(line, tokens, index, "invalid")))
    if action == "remark":
        if index + 1 >= len(tokens):
            return Match(False, "", "", _marked(line, _column(line, tokens, index, "incomplete")))
        return Match(True, " ".join(prefix + ["no", "remark", *tokens[index + 1 :]]), "applied", None)
    built, _index, error = _ace_body(tokens, index + 1, action, style)
    if error is not None:
        return Match(False, "", "", _marked(line, _column(line, tokens, error[0], error[1])))
    return Match(True, " ".join(prefix + ["no"] + built), "applied", None)


def _ace_body(
    tokens: list[str],
    index: int,
    action: str,
    style: str,
) -> tuple[list[str], int, tuple[int, str] | None]:
    built = [action]
    if style == "standard":
        advanced, index, error = _address(tokens, index)
        if error is not None:
            return built, index, error
        built.extend(advanced)
        if index < len(tokens):
            return built, index, (index, "invalid")
        return built, index, None
    if index >= len(tokens):
        return built, index, (index, "incomplete")
    proto = tokens[index]
    if proto.isdigit():
        built.append(proto)
    else:
        named = _one(proto, _PROTOS)
        if named is None:
            return built, index, (index, "invalid")
        built.append(named)
        proto = named
    index += 1
    advanced, index, error = _address(tokens, index)
    if error is not None:
        return built, index, error
    built.extend(advanced)
    if proto in {"tcp", "udp"}:
        ports, index, error = _ports(tokens, index)
        if error is not None:
            return built, index, error
        built.extend(ports)
    advanced, index, error = _address(tokens, index)
    if error is not None:
        return built, index, error
    built.extend(advanced)
    if proto in {"tcp", "udp"}:
        ports, index, error = _ports(tokens, index)
        if error is not None:
            return built, index, error
        built.extend(ports)
    while index < len(tokens):
        flag = _one(tokens[index], _ACE_FLAGS)
        if flag is not None:
            built.append(flag)
            index += 1
            continue
        pair = _one(tokens[index], _ACE_PAIRS)
        if pair is None:
            return built, index, (index, "invalid")
        if index + 1 >= len(tokens):
            return built, index, (index + 1, "incomplete")
        built.extend([pair, tokens[index + 1]])
        index += 2
    return built, index, None


def _address(
    tokens: list[str],
    index: int,
) -> tuple[list[str], int, tuple[int, str] | None]:
    if index >= len(tokens):
        return [], index, (index, "incomplete")
    kind = _one(tokens[index], ("any", "host"))
    if kind == "any":
        return ["any"], index + 1, None
    if kind == "host":
        if index + 1 >= len(tokens) or not _ipv4(tokens[index + 1]):
            return [], index + 1, (index + 1, "invalid" if index + 1 < len(tokens) else "incomplete")
        return ["host", tokens[index + 1]], index + 2, None
    if _ipv4(tokens[index]):
        if index + 1 >= len(tokens) or not _ipv4(tokens[index + 1]):
            at = index + 1
            return [], at, (at, "invalid" if at < len(tokens) else "incomplete")
        return [tokens[index], tokens[index + 1]], index + 2, None
    return [], index, (index, "invalid")


def _ports(
    tokens: list[str],
    index: int,
) -> tuple[list[str], int, tuple[int, str] | None]:
    if index >= len(tokens):
        return [], index, None
    op = _one(tokens[index], _PORT_OPS)
    if op is None:
        return [], index, None
    need = 2 if op == "range" else 1
    if index + need >= len(tokens):
        return [], index + need, (index + need, "incomplete")
    return [op, *tokens[index + 1 : index + 1 + need]], index + 1 + need, None


def _one(token: str, options: tuple[str, ...]) -> str | None:
    exact = [item for item in options if item.lower() == token.lower()]
    if len(exact) == 1:
        return exact[0]
    hits = [item for item in options if item.lower().startswith(token.lower())]
    if len(hits) == 1:
        return hits[0]
    return None


def _column(line: str, tokens: list[str], index: int, status: str) -> int:
    if not tokens or status == "incomplete" and index >= len(tokens):
        return max(len(line) - 1, 0)
    if index >= len(tokens):
        return max(len(line) - 1, 0)
    pos = 0
    for at, token in enumerate(tokens):
        found = line.find(token, pos)
        if found < 0:
            return 0
        if at == index:
            return found
        pos = found + len(token)
    return 0


def _marked(line: str, column: int) -> str:
    if not line:
        line = ""
        column = 0
    column = max(0, min(column, max(len(line) - 1, 0)))
    return f"{line}\n{' ' * column}^\n% Invalid input detected at '^' marker.\n"
