"""Apply configure-terminal lines to one device config.

The result is still text. The analysis engine recomputes from that text.
Nothing is sent to a live device.
"""

from __future__ import annotations

import ipaddress
import re

from dryrun_lab.acls import apply_acl_body, apply_resequence_command, is_resequence
from dryrun_lab.configparse import canonical_interface
from dryrun_lab.ioscheck import fold_line

_STANZA = re.compile(r"^(interface|vlan|router|ip access-list|line|banner)\b", re.IGNORECASE)
_ENTER = {"configure terminal", "configure", "conf t", "conf term", "conf terminal"}
_DENY = re.compile(
    r"^(?:\d+\s+)?deny\s+ip\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+"
    r"(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s*$",
    re.IGNORECASE,
)


def apply_config_lines(config: str, commands: list[str]) -> str:
    lines = config.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    context: list[tuple[str, str]] = []
    for raw in commands:
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        line = fold_line(line)
        lower = line.lower()
        if lower in {"end", "abort"}:
            break
        if lower in _ENTER:
            continue
        if lower == "exit":
            if context:
                context.pop()
            continue
        if lower.startswith("interface "):
            name = canonical_interface(line.split(None, 1)[1])
            context = [("interface", name)]
            _ensure_interface(lines, name)
            continue
        vlan = re.fullmatch(r"vlan\s+(\d+)", lower)
        if vlan:
            context = [("vlan", vlan.group(1))]
            _ensure_header(lines, f"vlan {vlan.group(1)}")
            continue
        if is_resequence(line):
            lines = apply_resequence_command(lines, line)
            context = []
            continue
        if lower.startswith("ip access-list "):
            context = [("acl", line)]
            _ensure_header(lines, line)
            continue
        if lower.startswith("router "):
            context = [("router", line)]
            _ensure_header(lines, line)
            continue
        if not context:
            _apply_global(lines, line)
            continue
        kind, ident = context[-1]
        _apply_inside(lines, kind, ident, line)
    return "\n".join(lines).rstrip() + "\n"


def prompt_for(device: str, commands: list[str]) -> str:
    context: list[tuple[str, str]] = []
    for raw in commands:
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        lower = line.lower()
        if lower in _ENTER or lower in {"end", "abort"}:
            continue
        if lower == "exit":
            if context:
                context.pop()
            continue
        if lower.startswith("interface "):
            context = [("interface", canonical_interface(line.split(None, 1)[1]))]
            continue
        if re.fullmatch(r"vlan\s+\d+", lower):
            context = [("vlan", lower.split()[1])]
            continue
        if is_resequence(line):
            context = []
            continue
        if lower.startswith("ip access-list "):
            context = [("acl", line)]
            continue
        if lower.startswith("router "):
            context = [("router", line)]
            continue
    if not context:
        return f"{device}(config)#"
    kind = context[-1][0]
    if kind == "interface":
        return f"{device}(config-if)#"
    if kind == "acl":
        ident = context[-1][1].lower()
        if re.search(r"\bstandard\b", ident):
            return f"{device}(config-std-nacl)#"
        return f"{device}(config-ext-nacl)#"
    if kind == "vlan":
        return f"{device}(config-vlan)#"
    if kind == "router":
        return f"{device}(config-router)#"
    return f"{device}(config)#"


def context_depth(commands: list[str]) -> int:
    """How many `exit` commands it takes to leave configuration mode."""
    depth = 1
    nested = 0
    for raw in commands:
        line = raw.strip().lower()
        if not line:
            continue
        if line.startswith("ip access-list resequence"):
            nested = 0
            continue
        if line.startswith("interface ") or line.startswith("ip access-list ") or line.startswith("router "):
            nested = 1
            continue
        if re.fullmatch(r"vlan\s+\d+", line):
            nested = 1
            continue
        if line == "exit" and nested:
            nested = 0
    return depth + nested


def acl_flows(commands: list[str]) -> list[tuple[str, str, str]]:
    """ACL name plus a representative source and destination for each new deny."""
    current: str | None = None
    found: list[tuple[str, str, str]] = []
    for raw in commands:
        line = raw.strip()
        lower = line.lower()
        if is_resequence(line):
            current = None
            continue
        if lower.startswith("ip access-list "):
            current = line.split()[-1]
            continue
        if lower in {"exit", "end"}:
            if lower == "exit":
                current = None
            continue
        match = _DENY.match(line)
        if match and current:
            src = _representative(match.group(1), match.group(2))
            dst = _representative(match.group(3), match.group(4))
            if src is None or dst is None:
                continue
            found.append((current, src, dst))
    return found


def ingress_interfaces(config: str, acl_name: str) -> list[str]:
    current: str | None = None
    found: list[str] = []
    for raw in config.splitlines():
        line = raw.strip()
        match = re.match(r"(?i)^interface\s+(\S+)", line)
        if match:
            current = canonical_interface(match.group(1))
            continue
        if current and re.match(rf"(?i)^ip\s+access-group\s+{re.escape(acl_name)}\s+in$", line):
            found.append(current)
    return found


def _representative(network: str, wildcard: str) -> str | None:
    try:
        base = ipaddress.IPv4Address(network)
        wild = int(ipaddress.IPv4Address(wildcard))
    except (ipaddress.AddressValueError, ValueError):
        return None
    if wild == 0:
        return str(base)
    host = int(base) | (wild & 50)
    if (host & ~wild) != (int(base) & ~wild):
        host = int(base) | 1
    return str(ipaddress.IPv4Address(host))


def _ensure_interface(lines: list[str], name: str) -> None:
    for line in lines:
        match = re.match(r"(?i)^interface\s+(\S+)", line.strip())
        if match and canonical_interface(match.group(1)) == name:
            return
    _insert_before_end(lines, f"interface {name}")


def _ensure_header(lines: list[str], header: str) -> None:
    want = header.strip().lower()
    for line in lines:
        if line.strip().lower() == want:
            return
    _insert_before_end(lines, header.strip())


def _insert_before_end(lines: list[str], header: str) -> None:
    for index, line in enumerate(lines):
        if line.strip().lower() == "end":
            lines.insert(index, "!")
            lines.insert(index + 1, header)
            return
    if lines and lines[-1].strip():
        lines.append("!")
    lines.append(header)


def _find_header(lines: list[str], kind: str, ident: str) -> int | None:
    for index, line in enumerate(lines):
        text = line.strip()
        lower = text.lower()
        if kind == "interface":
            match = re.match(r"(?i)^interface\s+(\S+)", text)
            if match and canonical_interface(match.group(1)) == ident:
                return index
        elif kind == "vlan" and lower == f"vlan {ident}":
            return index
        elif kind == "acl" and lower == ident.lower():
            return index
        elif kind == "router" and lower == ident.lower():
            return index
    return None


def _block_end(lines: list[str], start: int) -> int:
    for index in range(start + 1, len(lines)):
        text = lines[index]
        stripped = text.strip()
        if not stripped:
            continue
        if text.startswith("!"):
            return index
        if stripped.lower() == "end":
            return index
        if not text[0].isspace() and _STANZA.match(stripped):
            return index
    return len(lines)


def _apply_inside(lines: list[str], kind: str, ident: str, line: str) -> None:
    start = _find_header(lines, kind, ident)
    if start is None:
        return
    end = _block_end(lines, start)
    body = lines[start + 1 : end]
    if kind == "interface":
        _apply_interface_body(body, line)
    elif kind == "acl":
        body[:] = apply_acl_body(body, line)
    elif kind == "vlan":
        _apply_vlan_body(body, line)
    else:
        _append_unique(body, line)
    lines[start + 1 : end] = body


def _apply_interface_body(body: list[str], line: str) -> None:
    added = re.match(r"(?i)^switchport\s+trunk\s+allowed\s+vlan\s+add\s+(.+)$", line.strip())
    if added:
        extra = [part.strip() for part in added.group(1).split(",") if part.strip()]
        for index, existing in enumerate(body):
            match = re.match(r"(?i)^switchport\s+trunk\s+allowed\s+vlan\s+(.+)$", existing.strip())
            if not match:
                continue
            current = match.group(1).strip()
            if current.lower().startswith(("add ", "remove ", "except ", "none")):
                continue
            have = [part.strip() for part in current.split(",") if part.strip()]
            for item in extra:
                if item not in have:
                    have.append(item)
            body[index] = "switchport trunk allowed vlan " + ",".join(have)
            return
        body.append(line.strip())
        return
    if _replace_pair(body, line, "shutdown", "no shutdown"):
        return
    replacements = (
        ("ip address", ("ip address ", "no ip address")),
        ("encapsulation", ("encapsulation ",)),
        ("description", ("description ",)),
        ("switchport mode", ("switchport mode ",)),
        ("switchport access", ("switchport access ",)),
        ("switchport trunk encapsulation", ("switchport trunk encapsulation ",)),
    )
    lower = line.strip().lower()
    for _label, prefixes in replacements:
        if any(lower.startswith(prefix) or lower == prefix.strip() for prefix in prefixes):
            for index, existing in enumerate(body):
                existing_lower = existing.strip().lower()
                if any(existing_lower.startswith(prefix) or existing_lower == prefix.strip() for prefix in prefixes):
                    body[index] = line.strip()
                    return
            body.append(line.strip())
            return
    access_group = re.match(r"(?i)^ip\s+access-group\s+\S+\s+(in|out)$", line.strip())
    if access_group:
        direction = access_group.group(1).lower()
        for index, existing in enumerate(body):
            match = re.match(r"(?i)^ip\s+access-group\s+\S+\s+(in|out)$", existing.strip())
            if match and match.group(1).lower() == direction:
                body[index] = line.strip()
                return
    _append_unique(body, line)


def _replace_pair(body: list[str], line: str, left: str, right: str) -> bool:
    lower = line.strip().lower()
    if lower not in {left, right}:
        return False
    for index, existing in enumerate(body):
        if existing.strip().lower() in {left, right}:
            body[index] = line.strip()
            return True
    body.append(line.strip())
    return True


def _apply_vlan_body(body: list[str], line: str) -> None:
    text = line.strip()
    if text.lower().startswith("name "):
        for index, existing in enumerate(body):
            if existing.strip().lower().startswith("name "):
                body[index] = text
                return
    _append_unique(body, text)


def _append_unique(body: list[str], line: str) -> None:
    """Skip a second copy of the same command inside this one stanza.

    Typing `spanning-tree portfast` twice under Gi0/10 stores it once.
    Gi0/11 has its own body, so the same text there is a different line.
    """
    text = line.strip()
    if any(existing.strip().lower() == text.lower() for existing in body):
        return
    body.append(text)


def _apply_global(lines: list[str], line: str) -> None:
    text = line.strip()
    route = re.match(r"(?i)^ip\s+route\s+(\S+)\s+(\S+)\s+(\S+)", text)
    if route:
        prefix = (route.group(1), route.group(2))
        for index, existing in enumerate(lines):
            match = re.match(r"(?i)^ip\s+route\s+(\S+)\s+(\S+)\s+(\S+)", existing.strip())
            if match and (match.group(1), match.group(2)) == prefix:
                lines[index] = text
                return
    # A second copy of the same global command is a no-op, the way IOS treats it.
    if any(existing.strip().lower() == text.lower() for existing in lines):
        return
    _insert_before_end(lines, text)
