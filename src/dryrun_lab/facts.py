"""Facts read from a device config.

The analysis engine decides which lines it parsed. This module only
rewords a line the engine already reported, using that device's config.
"""

from __future__ import annotations

import re
from typing import Any

_GATEWAY = re.compile(r"^ip default-gateway\b", re.IGNORECASE)


def routing_enabled(config: str) -> bool:
    """True when the last `ip routing` / `no ip routing` line enables routing."""
    enabled = False
    for raw in config.replace("\r\n", "\n").split("\n"):
        line = raw.strip().lower()
        if not line or line.startswith("!"):
            continue
        if line == "ip routing":
            enabled = True
        elif line == "no ip routing":
            enabled = False
    return enabled


def annotate_warnings(rows: list[dict[str, Any]], configs: dict[str, str]) -> list[dict[str, Any]]:
    """Mark `ip default-gateway` ignored on devices that have `ip routing`."""
    annotated: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get("text") or "").strip()
        device = row.get("device")
        config = configs.get(str(device), "") if device else ""
        if device and _GATEWAY.match(text) and routing_enabled(config):
            annotated.append(
                {
                    **row,
                    "detail": "ignored when ip routing is enabled",
                    "kind": "ignored",
                }
            )
        else:
            annotated.append(row)
    return annotated
