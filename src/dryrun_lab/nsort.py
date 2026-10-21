"""Natural order for interface names.

Gi1/0/2 sorts before Gi1/0/10. Lexical order does the opposite.
"""

from __future__ import annotations

import re


def interface_key(name: str) -> tuple:
    parts = re.split(r"(\d+)", name.strip().lower())
    key: list[tuple] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)
