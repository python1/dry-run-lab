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

_IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_ACE_START = re.compile(r"(?i)^(?:(\d+)\s+)?(permit|deny|remark|no)\b")
_SEQ = re.compile(r"(?i)^(?P<indent>\s*)(?P<num>\d+)\s+(?P<rest>permit|deny|remark)\b")

# First words of commands this lab will accept. A one-character miss is rejected.
_WORDS = {
    "aaa",
    "access-list",
    "alias",
    "archive",
    "arp",
    "banner",
    "boot",
    "cdp",
    "channel-group",
    "class-map",
    "clock",
    "crypto",
    "deny",
    "description",
    "duplex",
    "enable",
    "encapsulation",
    "end",
    "errdisable",
    "exit",
    "hostname",
    "interface",
    "ip",
    "ipv6",
    "line",
    "lldp",
    "logging",
    "mac",
    "mls",
    "mtu",
    "no",
    "ntp",
    "permit",
    "policy-map",
    "remark",
    "router",
    "service",
    "service-policy",
    "shutdown",
    "snmp-server",
    "spanning-tree",
    "speed",
    "standby",
    "storm-control",
    "switchport",
    "udld",
    "username",
    "version",
    "vlan",
    "vrrp",
    "vtp",
}

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
    text = " ".join(line.strip().split())
    if not text or text.startswith("!"):
        return None
    lower = text.lower()
    if lower in {"end", "exit", "abort"}:
        return None
    bad = _bad_ipv4(text)
    if bad is not None:
        return _marked(text, bad)
    # A new stanza closes the previous one, the same way a pasted config does.
    if _opens_stanza(text):
        return _global_line(text)
    kind = _context(draft)
    if kind == "acl":
        return _acl_line(text)
    if kind == "interface":
        return _loose_line(text, _interface_line(text))
    if kind == "vlan":
        return _loose_line(text, _vlan_line(text))
    if kind == "router":
        return _loose_line(text, None)
    return _global_line(text)


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
    if invalid_input(draft, text):
        return None
    if _opens_stanza(text) or _context(draft) is not None:
        return None
    if _applied_global(text) or _harmless_feature(text):
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


def _opens_stanza(text: str) -> bool:
    lower = text.lower()
    if lower.startswith(("interface ", "ip access-list ", "router ")):
        return True
    return re.fullmatch(r"vlan\s+\d+", lower) is not None


def _context(draft: list[str]) -> str | None:
    kind: str | None = None
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
        if lower.startswith("ip access-list "):
            kind = "acl"
            continue
        if lower.startswith("router "):
            kind = "router"
            continue
        if re.fullmatch(r"vlan\s+\d+", lower):
            kind = "vlan"
            continue
        if lower == "exit":
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


def _at(line: str, token: str) -> str:
    lower = line.lower()
    found = lower.find(token.lower())
    return _marked(line, found if found >= 0 else 0)


def _near_miss(word: str) -> bool:
    folded = word.lower()
    if folded in _WORDS or folded.isdigit():
        return False
    return any(_distance(folded, known) == 1 for known in _WORDS)


def _distance(left: str, right: str) -> int:
    if abs(len(left) - len(right)) > 1:
        return 2
    if len(left) > len(right):
        left, right = right, left
    edits = 0
    index = 0
    extra = 0
    while index < len(left):
        if left[index] != right[index + extra]:
            edits += 1
            if edits > 1:
                return 2
            if len(left) != len(right):
                extra = 1
                continue
        index += 1
    if extra and index + extra < len(right):
        edits += 1
    return edits


def _loose_line(text: str, specific: str | None) -> str | None:
    if specific:
        return specific
    word = text.split()[0]
    if word.lower() == "no" and len(text.split()) > 1:
        word = text.split()[1]
    if _near_miss(word):
        return _at(text, word)
    return None


def _acl_line(text: str) -> str | None:
    match = re.match(r"(?i)^(?:(\d+)\s+)?(\S+)(?:\s+(.*))?$", text)
    if match is None:
        return _marked(text, 0)
    word = match.group(2)
    folded = word.lower()
    if folded not in {"permit", "deny", "remark", "no"}:
        return _at(text, word)
    rest = (match.group(3) or "").strip()
    if folded == "no":
        if re.fullmatch(r"\d+", rest):
            return None
        if not rest:
            return _at(text, word)
        return _acl_line(rest)
    if folded == "remark":
        if not rest:
            return _at(text, word)
        return None
    if not rest:
        return _at(text, word)
    proto = rest.split()[0]
    if _near_miss(proto) or (
        proto.lower() not in {"ip", "tcp", "udp", "icmp", "gre", "esp", "ahp", "eigrp", "ospf", "igmp", "pim"}
        and not proto.isdigit()
    ):
        return _at(text, proto)
    return None


def _interface_line(text: str) -> str | None:
    lower = text.lower()
    if lower in {"shutdown", "no shutdown", "no ip address", "exit"}:
        return None
    if lower.startswith("description "):
        return None
    address = re.match(
        r"(?i)^ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)(?:\s+secondary)?$",
        text,
    )
    if lower.startswith("ip address"):
        if address is None:
            return _marked(text, 0)
        return None
    if re.match(r"(?i)^encapsulation\s+dot1q\s+\d+$", lower):
        return None
    if re.match(r"(?i)^switchport\s+mode\s+(access|trunk)$", lower):
        return None
    if re.match(r"(?i)^switchport\s+access\s+vlan\s+\d+$", lower):
        vlan = int(lower.split()[-1])
        if not 1 <= vlan <= 4094:
            return _at(text, lower.split()[-1])
        return None
    if re.match(r"(?i)^switchport\s+trunk\s+encapsulation\s+dot1q$", lower):
        return None
    if re.match(r"(?i)^switchport\s+trunk\s+allowed\s+vlan(\s+add|\s+remove)?\s+[\d,\-]+$", lower):
        return None
    if re.match(r"(?i)^ip\s+access-group\s+\S+\s+(in|out)$", text):
        return None
    if re.match(r"(?i)^no\s+ip\s+access-group\s+\S+\s+(in|out)$", text):
        return None
    return None


def _vlan_line(text: str) -> str | None:
    lower = text.lower()
    if lower.startswith("name ") and len(text.split()) >= 2:
        return None
    if lower == "exit":
        return None
    return None


def _global_line(text: str) -> str | None:
    lower = text.lower()
    parts = text.split()
    if re.match(r"(?i)^(?:\d+\s+)?(permit|deny|remark)\b", text):
        return _marked(text, 0)
    if parts and parts[0].isdigit():
        return _at(text, parts[0])
    if lower.startswith("ip access-list"):
        if len(parts) >= 3 and parts[2].lower() == "resequence":
            if len(parts) != 6 or not parts[4].isdigit() or not parts[5].isdigit():
                return _marked(text, 0)
            if int(parts[4]) < 1 or int(parts[5]) < 1:
                return _marked(text, 0)
            return None
        if len(parts) != 4 or parts[2].lower() not in {"extended", "standard"}:
            column = 0
            if len(parts) > 4:
                column = lower.rfind(parts[4].lower())
            elif len(parts) >= 3 and parts[2].lower() not in {"extended", "standard"}:
                column = lower.find(parts[2].lower())
            return _marked(text, max(column, 0))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", parts[3]):
            return _at(text, parts[3])
        return None
    if lower.startswith("interface "):
        if len(parts) != 2:
            return _marked(text, 0)
        return None
    vlan = re.fullmatch(r"vlan\s+(\d+)", lower)
    if lower.startswith("vlan"):
        if vlan is None or not 1 <= int(vlan.group(1)) <= 4094:
            return _marked(text, 0)
        return None
    if lower.startswith("router "):
        if len(parts) < 2:
            return _marked(text, 0)
        return None
    if lower.startswith("hostname "):
        if len(parts) != 2:
            return _marked(text, 0)
        return None
    if lower.startswith("ip route "):
        if len(parts) < 5:
            return _marked(text, 0)
        return None
    if lower.startswith("ip default-gateway "):
        if len(parts) != 3:
            return _marked(text, 0)
        return None
    if lower in {"ip routing", "no ip routing", "no ip source-route", "ip source-route", "ip cef"}:
        return None
    if re.fullmatch(r"version\s+\d+\.\d+(?:\.\d+)?", lower):
        return None
    if lower.startswith("version"):
        return _marked(text, 0)
    feature = _feature_text(text)
    if any(pattern.match(feature) for pattern in BEHAVIOR_UNMODELED):
        return None
    if any(pattern.match(feature) for pattern in HARMLESS):
        return None
    word = parts[0]
    if word.lower() == "no" and len(parts) > 1:
        word = parts[1]
    if word.lower() in _WORDS:
        return None
    if _near_miss(word):
        return _at(text, word)
    return _marked(text, 0)


def _feature_text(text: str) -> str:
    """Drop a leading `no`, so `no spanning-tree` is the same feature."""
    parts = text.split()
    if parts and parts[0].lower() == "no" and len(parts) > 1:
        return " ".join(parts[1:])
    return text


def _applied_global(text: str) -> bool:
    """Global commands this lab applies. The prompt stays quiet for these."""
    lower = text.lower()
    if lower.startswith(
        ("hostname ", "interface ", "ip access-list ", "router ", "ip route ", "ip default-gateway ")
    ):
        return True
    if re.fullmatch(r"vlan\s+\d+", lower):
        return True
    if lower in {"ip routing", "no ip routing", "no ip source-route", "ip source-route", "ip cef"}:
        return True
    return re.fullmatch(r"version\s+\d+\.\d+(?:\.\d+)?", lower) is not None


def _harmless_feature(text: str) -> bool:
    feature = _feature_text(text)
    return any(pattern.match(feature) for pattern in HARMLESS)


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
