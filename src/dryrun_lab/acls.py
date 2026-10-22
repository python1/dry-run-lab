"""Named ACL sequence numbers, the way a device assigns them.

Unnumbered lines already in a config are 10, 20, 30, and so on. A new line
with no number is appended and gets the last sequence plus 10. A line that
starts with a number is inserted at that sequence. `show access-lists` and
the snapshot always print the numbers, and a drop is named by sequence.
`show running-config` prints a number on every entry from IOS-XE 16.12, and
when the config has no version line. The saved config keeps a number when
the user typed it, resequence wrote new ones, or leaving it off would assign
a different sequence next time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADER = re.compile(r"(?i)^ip\s+access-list\s+(standard|extended)\s+(\S+)\s*$")
_ACE = re.compile(r"(?i)^(?:(\d+)\s+)?(permit|deny|remark)\b\s*(.*)$")
_NO_SEQ = re.compile(r"(?i)^no\s+(\d+)\s*$")
_NO_ACE = re.compile(r"(?i)^no\s+(?:(\d+)\s+)?(permit|deny|remark)\b\s*(.*)$")
_RESEQUENCE = re.compile(r"(?i)^ip\s+access-list\s+resequence\s+(\S+)\s+(\d+)\s+(\d+)\s*$")
_STANZA = re.compile(r"(?i)^(interface|vlan|router|ip access-list|line|banner)\b")
_ANY = {"permit ip any any", "permit any"}


@dataclass(frozen=True)
class Ace:
    seq: int
    text: str
    explicit: bool = False


@dataclass
class Acl:
    kind: str
    name: str
    aces: list[Ace]


def parse_acls(config: str) -> list[Acl]:
    found: list[Acl] = []
    for _start, _end, kind, name, body, _extras in _blocks(config):
        found.append(Acl(kind=kind, name=name, aces=aces_from_body(body)))
    return found


def numbered_config(config: str) -> str:
    """Rewrite each named ACL so every entry carries its sequence number."""
    text = config.replace("\r\n", "\n")
    newline = text.endswith("\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    pieces: list[str] = []
    cursor = 0
    for start, end, _kind, _name, body, extras in _blocks(text):
        pieces.extend(lines[cursor:start])
        pieces.append(lines[start])
        pieces.extend(_render(aces_from_body(body), extras, numbered=True))
        cursor = end
    pieces.extend(lines[cursor:])
    rendered = "\n".join(pieces).rstrip() + "\n"
    if not newline and not config.endswith("\n"):
        return rendered
    return rendered


def apply_acl_body(body: list[str], line: str) -> list[str]:
    """Apply one line typed inside `ip access-list` mode."""
    stripped = [" ".join(item.strip().split()) for item in body if item.strip() and not item.strip().startswith("!")]
    aces = aces_from_body(stripped)
    extras = [item for item in stripped if not _ACE.match(item)]
    command = " ".join(line.strip().split())
    removed = _remove(aces, command)
    if removed is not None:
        return _render(removed, extras)
    match = _ACE.match(command)
    if match is None:
        extras.append(command)
        return _render(aces, extras)
    seq = int(match.group(1)) if match.group(1) else None
    text = _ace_text(match.group(2), match.group(3))
    if seq is None:
        seq = (aces[-1].seq + 10) if aces else 10
        while any(ace.seq == seq for ace in aces):
            seq += 10
        aces.append(Ace(seq, text, explicit=False))
    else:
        aces = [ace for ace in aces if ace.seq != seq]
        aces.append(Ace(seq, text, explicit=True))
    aces.sort(key=lambda ace: ace.seq)
    return _render(aces, extras)


def apply_resequence_command(lines: list[str], command: str) -> list[str]:
    """Renumber one named ACL, or keep a form this lab does not apply."""
    match = _RESEQUENCE.match(command.strip())
    if match is None or int(match.group(2)) < 1 or int(match.group(3)) < 1:
        return _keep_unsimulated(list(lines), command.strip())
    name, start, step = match.group(1), int(match.group(2)), int(match.group(3))
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    source = text.split("\n")
    if source and source[-1] == "":
        source.pop()
    pieces: list[str] = []
    cursor = 0
    found = False
    for start_at, end, _kind, acl_name, body, extras in _blocks(text):
        pieces.extend(source[cursor:start_at])
        pieces.append(source[start_at])
        aces = aces_from_body(body)
        if acl_name.lower() == name.lower():
            found = True
            ordered = sorted(aces, key=lambda ace: ace.seq)
            aces = [Ace(start + index * step, ace.text, explicit=True) for index, ace in enumerate(ordered)]
        pieces.extend(_render(aces, extras))
        cursor = end
    if not found:
        return _keep_unsimulated(list(lines), command.strip())
    pieces.extend(source[cursor:])
    return pieces


def is_resequence(command: str) -> bool:
    return command.strip().lower().startswith("ip access-list resequence")


def split_sequence(line: str) -> tuple[int | None, str]:
    match = re.match(r"(?i)^(\d+)\s+(permit|deny|remark)\b", line.strip())
    if not match:
        return None, " ".join(line.strip().split())
    number = int(match.group(1))
    rest = line.strip()[match.end(1) :].strip()
    return number, " ".join(rest.split())


def sequence_of(config: str, acl_name: str, ace_text: str) -> int | None:
    """Sequence of one ACE.

    A sequence written on the line is that line, even when an earlier ACE
    has the same text. Without a sequence, identical lines are left unnamed
    rather than reported as the first copy.
    """
    reported, want = split_sequence(ace_text)
    found: list[int] = []
    for acl in parse_acls(config):
        if acl.name.lower() != acl_name.lower():
            continue
        for ace in acl.aces:
            if ace.text.lower() != want.lower():
                continue
            if reported is not None and ace.seq == reported:
                return ace.seq
            found.append(ace.seq)
    if reported is not None or len(found) != 1:
        return None
    return found[0]


def ace_at_index(config: str, acl_name: str, index: int | None) -> tuple[int, str] | None:
    """Sequence and text of the ACE at a filter line index."""
    if index is None or index < 0:
        return None
    for acl in parse_acls(config):
        if acl.name.lower() != acl_name.lower():
            continue
        ordered = sorted(acl.aces, key=lambda ace: ace.seq)
        if index >= len(ordered):
            return None
        ace = ordered[index]
        return ace.seq, ace.text
    return None


def added_aces(before: str, after: str) -> list[tuple[Acl, Ace]]:
    """Lines in `after` that this edit introduced.

    The same text and sequence is the line that was already there. A new
    sequence is a new line unless it only replaces a copy whose sequence
    disappeared, as a resequence does. Identical text is not counted by
    walking from the top, so a duplicate inserted earlier is the new line.
    """
    from collections import Counter

    old: dict[tuple[str, str], Counter[int]] = {}
    for acl in parse_acls(before):
        for ace in acl.aces:
            old.setdefault((acl.name.lower(), ace.text.lower()), Counter())[ace.seq] += 1
    pending: list[tuple[Acl, Ace]] = []
    for acl in parse_acls(after):
        for ace in acl.aces:
            key = (acl.name.lower(), ace.text.lower())
            counts = old.get(key)
            if counts is not None and counts[ace.seq] > 0:
                counts[ace.seq] -= 1
                continue
            pending.append((acl, ace))
    found: list[tuple[Acl, Ace]] = []
    for acl, ace in pending:
        counts = old.get((acl.name.lower(), ace.text.lower()))
        leftover = next((seq for seq, count in (counts or {}).items() if count > 0), None)
        if leftover is not None and counts is not None:
            counts[leftover] -= 1
            continue
        found.append((acl, ace))
    return found


def shadow_sentence(acl: Acl, ace: Ace, blocking: list[str]) -> str:
    """Say which line cannot match. Callers add 'added' only for a new line."""
    blocker = _blocking_ace(acl, ace, blocking)
    if blocker is None:
        return f"Line at sequence {ace.seq}; it will never match."
    return (
        f"Line at sequence {ace.seq}, after sequence {blocker.seq} {blocker.text}; "
        "it will never match."
    )


def deny_flows(config: str) -> list[tuple[str, str, str, str]]:
    """ACL name, source, destination, and the ace text for each deny ip line."""
    found: list[tuple[str, str, str, str]] = []
    for acl in parse_acls(config):
        for ace in acl.aces:
            flow = _deny_endpoints(ace.text)
            if flow is None:
                continue
            src, dst = flow
            found.append((acl.name, src, dst, ace.text))
    return found


def aces_from_body(body: list[str]) -> list[Ace]:
    parsed: list[tuple[int | None, str]] = []
    for raw in body:
        match = _ACE.match(" ".join(raw.strip().split()))
        if not match:
            continue
        seq = int(match.group(1)) if match.group(1) else None
        parsed.append((seq, _ace_text(match.group(2), match.group(3))))
    if not parsed:
        return []
    if all(seq is None for seq, _text in parsed):
        return [Ace(10 * (index + 1), text) for index, (_seq, text) in enumerate(parsed)]
    # An explicit number keeps its place. An unnumbered line takes the next
    # free step of 10, and a number typed below that step (25 between 20 and
    # 30) does not push the following unnumbered line forward.
    aces: list[Ace] = []
    used: set[int] = set()
    next_auto = 10
    for seq, text in parsed:
        if seq is None:
            assigned = next_auto
            while assigned in used:
                assigned += 10
            used.add(assigned)
            next_auto = assigned + 10
            aces.append(Ace(assigned, text, explicit=False))
            continue
        used.add(seq)
        if seq >= next_auto:
            next_auto = seq + 10
        aces.append(Ace(seq, text, explicit=True))
    aces.sort(key=lambda ace: ace.seq)
    return aces


def _blocks(config: str) -> list[tuple[int, int, str, str, list[str], list[str]]]:
    lines = config.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    found: list[tuple[int, int, str, str, list[str], list[str]]] = []
    index = 0
    while index < len(lines):
        header = _HEADER.match(lines[index].strip())
        if header is None or lines[index][:1].isspace():
            index += 1
            continue
        start = index
        index += 1
        body: list[str] = []
        extras: list[str] = []
        while index < len(lines):
            raw = lines[index]
            stripped = raw.strip()
            if not stripped:
                index += 1
                continue
            if raw.startswith("!") or stripped.lower() == "end":
                break
            if not raw[:1].isspace() and _STANZA.match(stripped):
                break
            if _ACE.match(" ".join(stripped.split())):
                body.append(stripped)
            else:
                extras.append(stripped)
            index += 1
        found.append((start, index, header.group(1).lower(), header.group(2), body, extras))
    return found


def _render(aces: list[Ace], extras: list[str], *, numbered: bool = False) -> list[str]:
    """Write ACL lines in running-config style.

    A number is written when the user typed it, when every line is being
    numbered for the snapshot, or when leaving it off would make the next
    read assign a different sequence. Default 10, 20, 30 stay unnumbered.
    """
    ordered = sorted(aces, key=lambda ace: ace.seq)
    lines: list[str] = []
    next_auto = 10
    used: set[int] = set()
    for ace in ordered:
        if numbered or ace.explicit or not _auto_would_match(ace.seq, next_auto, used):
            lines.append(f" {ace.seq} {ace.text}")
            used.add(ace.seq)
            if ace.seq >= next_auto:
                next_auto = ace.seq + 10
            continue
        assigned = next_auto
        while assigned in used:
            assigned += 10
        lines.append(f" {ace.text}")
        used.add(assigned)
        next_auto = assigned + 10
    lines.extend(f" {extra}" for extra in extras)
    return lines


def _auto_would_match(seq: int, next_auto: int, used: set[int]) -> bool:
    assigned = next_auto
    while assigned in used:
        assigned += 10
    return assigned == seq


def _ace_text(action: str, rest: str) -> str:
    return " ".join(f"{action} {rest}".split())


def _remove(aces: list[Ace], command: str) -> list[Ace] | None:
    only = _NO_SEQ.match(command)
    if only:
        seq = int(only.group(1))
        return [ace for ace in aces if ace.seq != seq]
    match = _NO_ACE.match(command)
    if match is None:
        return None
    seq = int(match.group(1)) if match.group(1) else None
    want = _ace_text(match.group(2), match.group(3)).lower()
    out: list[Ace] = []
    removed = False
    for ace in aces:
        same = ace.text.lower() == want and (seq is None or ace.seq == seq)
        if same and not removed:
            removed = True
            continue
        out.append(ace)
    return out


def _keep_unsimulated(lines: list[str], command: str) -> list[str]:
    if any(line.strip().lower() == command.lower() for line in lines):
        return lines
    for index, line in enumerate(lines):
        if line.strip().lower() == "end":
            lines.insert(index, command)
            return lines
    lines.append(command)
    return lines


def _blocking_ace(acl: Acl, ace: Ace, blocking: list[str]) -> Ace | None:
    earlier = [item for item in acl.aces if item.seq < ace.seq]
    chosen: list[Ace] = []
    for raw in blocking:
        seq, text = split_sequence(str(raw))
        for item in earlier:
            if item.text.lower() != text.lower():
                continue
            if seq is not None and item.seq != seq:
                continue
            chosen.append(item)
    if chosen:
        return max(chosen, key=lambda item: item.seq)
    for item in earlier:
        if item.text.lower() in _ANY:
            return item
    return None


def _deny_endpoints(text: str) -> tuple[str, str] | None:
    match = re.match(
        r"(?i)^deny\s+ip\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+"
        r"(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s*$",
        text.strip(),
    )
    if match is None:
        return None
    src = _representative(match.group(1), match.group(2))
    dst = _representative(match.group(3), match.group(4))
    if src is None or dst is None:
        return None
    return src, dst


def _representative(network: str, wildcard: str) -> str | None:
    import ipaddress

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
