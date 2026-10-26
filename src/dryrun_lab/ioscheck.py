"""IOS-XE checks for lines typed in configuration mode.

Keywords are accepted in any case. A line that is not a real command is
rejected before it joins the pending edit. At global config, a real IOS
command this lab does not apply is stored and the prompt says it was kept
but not simulated. Sequence numbers in `show running-config` follow the
16.12 rule: from IOS-XE 16.12 they are stored in the displayed config.
Remarks are numbered the same way; that part is unconfirmed.
"""

from __future__ import annotations

import re

from dryrun_lab.acls import numbered_config
from dryrun_lab.iosgrammar import Match, leaves_mode, match_config

_IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_SEQ = re.compile(r"(?i)^(?P<indent>\s*)(?P<num>\d+)\s+(?P<rest>permit|deny|remark)\b")

# Forwarding or filtering this lab does not apply. Shown as not simulated.
BEHAVIOR_UNMODELED = (
    re.compile(r"(?i)^spanning-tree\b"),
    re.compile(r"(?i)^storm-control\b"),
    re.compile(r"(?i)^switchport\s+port-security\b"),
    re.compile(r"(?i)^switchport\s+block\b"),
    re.compile(r"(?i)^ip\s+dhcp\s+snooping\b"),
    re.compile(r"(?i)^ip\s+arp\s+inspection\b"),
    re.compile(r"(?i)^ip\s+verify\s+unicast\b"),
    re.compile(r"(?i)^channel-group\b"),
    re.compile(r"(?i)^udld\b"),
    re.compile(r"(?i)^mac\s+access-group\b"),
    re.compile(r"(?i)^(policy-map|class-map|service-policy)\b"),
    re.compile(r"(?i)^mls\s+qos\b"),
    re.compile(r"(?i)^vtp\s+mode\b"),
    re.compile(r"(?i)^ip\s+nat\b"),
    # DHCP relay, first-hop redundancy, policy routing, voice VLAN, VACLs,
    # directed broadcast, and 802.1X change forwarding and this lab does not
    # apply them. The same text on two SVIs is two warnings.
    re.compile(r"(?i)^(?:no\s+)?ip\s+helper-address\b"),
    re.compile(r"(?i)^(?:no\s+)?standby\b"),
    re.compile(r"(?i)^(?:no\s+)?vrrp\b"),
    re.compile(r"(?i)^(?:no\s+)?glbp\b"),
    re.compile(r"(?i)^(?:no\s+)?ip\s+policy\s+route-map\b"),
    re.compile(r"(?i)^(?:no\s+)?switchport\s+voice\b"),
    re.compile(r"(?i)^(?:no\s+)?ip\s+directed-broadcast\b"),
    re.compile(r"(?i)^vlan\s+access-map\b"),
    re.compile(r"(?i)^vlan\s+filter\b"),
    re.compile(r"(?i)^(?:no\s+)?dot1x\b"),
    re.compile(r"(?i)^(?:no\s+)?mab\b"),
    re.compile(
        r"(?i)^(?:no\s+)?authentication\s+"
        r"(?:port-control|host-mode|order|priority|periodic|timer|violation|event)\b"
    ),
)

# No effect on the forwarding this lab computes. Not flagged.
HARMLESS = (
    re.compile(r"(?i)^logging\b"),
    re.compile(r"(?i)^snmp-server\b"),
    re.compile(r"(?i)^ntp\b"),
    re.compile(r"(?i)^banner\b"),
    re.compile(r"(?i)^username\b"),
    re.compile(r"(?i)^enable\s+(secret|password)\b"),
    re.compile(r"(?i)^line\b"),
    re.compile(r"(?i)^alias\b"),
    re.compile(r"(?i)^service\b"),
    re.compile(r"(?i)^clock\b"),
    re.compile(r"(?i)^boot\b"),
    re.compile(r"(?i)^license\b"),
    re.compile(r"(?i)^archive\b"),
    re.compile(r"(?i)^parser\b"),
    re.compile(r"(?i)^ip\s+domain\b"),
)

VERSION_NOTE = "No version line found; assuming IOS-XE 16.12 or later"
KEPT_NOTE = "% Not simulated in this version. The line was kept.\n"


def invalid_input(draft: list[str], line: str) -> str | None:
    """IOS `% Invalid input` text, or None when the line may be kept."""
    found = _classify(draft, line)
    if found is None or found.ok:
        return None
    return found.error


def canonical_line(draft: list[str], line: str) -> str:
    """The line IOS stores: keywords expanded, names left as typed."""
    text = " ".join(line.strip().split())
    if not text or text.startswith("!"):
        return text
    if text.lower() in {"end", "exit", "abort"}:
        return text.lower()
    found = _classify(draft, text)
    if found is not None and found.ok and found.canonical:
        return found.canonical
    return fold_line(text)


def _classify(draft: list[str], line: str) -> Match | None:
    text = " ".join(line.strip().split())
    if not text or text.startswith("!"):
        return None
    if text.lower() in {"end", "exit", "abort"}:
        return Match(True, text.lower(), "applied", None)
    bad = _bad_ipv4(text)
    if bad is not None:
        return Match(False, "", "", _marked(text, bad))
    return match_config(_context(draft), text, _acl_style(draft))


def _acl_style(draft: list[str]) -> str:
    style = "extended"
    for raw in draft:
        match = re.match(r"(?i)^ip\s+access-list\s+(extended|standard)\s+\S+\s*$", raw.strip())
        if match:
            style = match.group(1).lower()
    return style


def fold_line(line: str) -> str:
    """Lowercase IOS keywords. ACL names, hostnames, and free text keep their case."""
    text = " ".join(line.strip().split())
    if not text or text.startswith("!"):
        return text
    parts = text.split()
    low = [part.lower() for part in parts]
    if low[0] in {"description", "remark", "banner", "name"} and len(parts) > 1:
        return low[0] + " " + " ".join(parts[1:])
    if low[:3] == ["ip", "access-list", "resequence"] and len(parts) >= 4:
        return " ".join(low[:3] + [parts[3]] + low[4:])
    if len(low) >= 4 and low[:2] == ["ip", "access-list"] and low[2] in {"extended", "standard"}:
        return " ".join(low[:3] + [parts[3]] + low[4:])
    if low[0] == "hostname" and len(parts) >= 2:
        return "hostname " + parts[1]
    if low[0] == "interface" and len(parts) >= 2:
        return "interface " + parts[1]
    if low[:2] == ["ip", "access-group"] and len(parts) >= 3:
        # ip access-group NAME in|out
        tail = low[3:] if len(parts) > 3 else []
        return " ".join(["ip", "access-group", parts[2], *tail])
    return " ".join(low)


def version_tuple(config: str) -> tuple[int, int] | None:
    """Major and minor from the first `version` line, or None when it is absent."""
    for raw in config.replace("\r\n", "\n").split("\n"):
        match = re.match(r"(?i)^version\s+(\d+)\.(\d+)", raw.strip())
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def sequences_nvgen(config: str) -> bool:
    """True when running-config shows an ACL sequence on every entry.

    IOS-XE 16.12 and later nvgen sequence numbers. No version line uses that
    behavior and `version_note` says so.
    """
    found = version_tuple(config)
    if found is None:
        return True
    major, minor = found
    return major > 16 or (major == 16 and minor >= 12)


def version_note(config: str, *, role: str | None = None) -> str | None:
    """Note for a router or switch with no `version` line.

    A host does not run an IOS image, so it never gets this sentence.
    Omitting `role` keeps the note, which is the check used before a
    device role is known. Sequence display is unchanged either way.
    """
    if role == "host":
        return None
    if version_tuple(config) is None:
        return VERSION_NOTE
    return None


def kept_note(draft: list[str], line: str) -> str | None:
    """Prompt text for a global line that is stored and not applied.

    Applied commands and harmless lines stay quiet. Inside an interface,
    VLAN, router, or ACL stanza the prompt stays quiet too; those lines
    are judged when the edit is committed. A rejected line has no note.
    """
    text = " ".join(line.strip().split())
    if not text or text.startswith("!"):
        return None
    found = _classify(draft, text)
    if found is None or not found.ok:
        return None
    if _context(draft) is not None or found.kind != "unmodeled":
        return None
    return KEPT_NOTE


def display_config(config: str) -> str:
    """Config text as `show running-config` prints the ACL lines."""
    if sequences_nvgen(config):
        return numbered_config(config)
    return _strip_acl_sequences(config)


def same_displayed_config(stored: str, submitted: str) -> bool:
    """True when the panel text is the running-config view of the stored config."""
    left = display_config(stored).strip()
    right = submitted.replace("\r\n", "\n").strip()
    return right == left or right == stored.replace("\r\n", "\n").strip()


def unmodeled_lines(config: str) -> list[tuple[int, str]]:
    """Lines that can change forwarding and that this lab does not apply."""
    found: list[tuple[int, str]] = []
    for index, raw in enumerate(config.replace("\r\n", "\n").split("\n"), start=1):
        text = raw.strip()
        if not text or text.startswith("!"):
            continue
        if any(pattern.match(text) for pattern in BEHAVIOR_UNMODELED):
            found.append((index, text))
    return found


def is_harmless(text: str) -> bool:
    stripped = text.strip()
    return any(pattern.match(stripped) for pattern in HARMLESS)


def _context(draft: list[str]) -> str | None:
    kind: str | None = None
    style = "extended"
    for raw in draft:
        line = " ".join(raw.strip().split())
        lower = line.lower()
        if not lower or lower.startswith("!"):
            continue
        if lower.startswith("ip access-list resequence"):
            kind = None
            continue
        if lower.startswith("interface "):
            kind = "interface"
            continue
        header = re.match(r"ip access-list (extended|standard) \S+$", lower)
        if header:
            kind = "acl"
            style = header.group(1)
            continue
        if lower.startswith("router "):
            kind = "router"
            continue
        if re.fullmatch(r"vlan\s+\d+", lower):
            kind = "vlan"
            continue
        if lower == "exit" or (kind and leaves_mode(kind, line, style)):
            kind = None
    return kind


def _bad_ipv4(text: str) -> int | None:
    for match in _IPV4.finditer(text):
        pieces = match.group(1).split(".")
        offset = 0
        for piece in pieces:
            if int(piece) > 255:
                return match.start(1) + offset
            offset += len(piece) + 1
    return None


def _marked(line: str, column: int) -> str:
    column = max(0, min(column, max(len(line) - 1, 0)))
    return f"{line}\n{' ' * column}^\n% Invalid input detected at '^' marker.\n"


def _strip_acl_sequences(config: str) -> str:
    """Running-config view before IOS-XE 16.12: ACL entries have no sequence."""
    lines = config.replace("\r\n", "\n").split("\n")
    in_acl = False
    rendered: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if re.match(r"(?i)^ip\s+access-list\s+(standard|extended)\s+\S+\s*$", stripped):
            in_acl = True
            rendered.append(raw)
            continue
        if in_acl and stripped and not raw[:1].isspace() and not stripped.startswith("!"):
            in_acl = False
        if in_acl:
            match = _SEQ.match(raw)
            if match:
                indent = match.group("indent") or " "
                rendered.append(f"{indent}{match.group('rest')}{raw[match.end('rest'):]}")
                continue
        rendered.append(raw)
    text = "\n".join(rendered)
    if config.endswith("\n") or not text.endswith("\n"):
        if config.endswith("\n") and not text.endswith("\n"):
            text += "\n"
    return text
