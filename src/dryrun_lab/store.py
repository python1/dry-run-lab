"""Lab documents stored as JSON on this machine."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from dryrun_lab.configparse import parse_config
from dryrun_lab.nsort import interface_key
from dryrun_lab.infer import Inference, Suggestion, endpoint_key, infer, link_id


@dataclass
class Device:
    name: str
    role: str
    config: str = ""
    neighbor_text: str = ""
    x: float = 80
    y: float = 80
    config_history: list[str] = field(default_factory=list)


@dataclass
class Link:
    id: str
    a_device: str
    a_interface: str
    b_device: str
    b_interface: str
    status: str
    source: str
    reason: str
    down: bool = False


@dataclass
class Lab:
    name: str = "untitled"
    devices: list[Device] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    dismissed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    engine_error: str | None = None

    def device(self, name: str) -> Device | None:
        for device in self.devices:
            if device.name.lower() == name.lower():
                return device
        return None


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.lab = Lab()
        if path.is_file():
            self.lab = lab_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(lab_to_dict(self.lab), indent=2) + "\n",
            encoding="utf-8",
        )


def lab_to_dict(lab: Lab) -> dict:
    return {
        "name": lab.name,
        "devices": [
            {
                "name": device.name,
                "role": device.role,
                "config": device.config,
                "neighborText": device.neighbor_text,
                "x": device.x,
                "y": device.y,
                "configHistory": list(device.config_history),
            }
            for device in lab.devices
        ],
        "links": [
            {
                "id": link.id,
                "aDevice": link.a_device,
                "aInterface": link.a_interface,
                "bDevice": link.b_device,
                "bInterface": link.b_interface,
                "status": link.status,
                "source": link.source,
                "reason": link.reason,
                "down": link.down,
            }
            for link in lab.links
        ],
        "dismissed": list(lab.dismissed),
        "notes": list(lab.notes),
        "warnings": lab.warnings,
        "engineError": lab.engine_error,
    }


def lab_from_dict(data: dict) -> Lab:
    lab = Lab(name=str(data.get("name") or "untitled"))
    for raw in data.get("devices") or []:
        lab.devices.append(
            Device(
                name=str(raw["name"]),
                role=str(raw.get("role") or "router"),
                config=str(raw.get("config") or ""),
                neighbor_text=str(raw.get("neighborText") or ""),
                x=float(raw.get("x") or 80),
                y=float(raw.get("y") or 80),
                config_history=[str(item) for item in raw.get("configHistory") or []],
            )
        )
    for raw in data.get("links") or []:
        lab.links.append(
            Link(
                id=str(raw["id"]),
                a_device=str(raw["aDevice"]),
                a_interface=str(raw["aInterface"]),
                b_device=str(raw["bDevice"]),
                b_interface=str(raw["bInterface"]),
                status=str(raw.get("status") or "suggested"),
                source=str(raw.get("source") or "user"),
                reason=str(raw.get("reason") or ""),
                down=bool(raw.get("down") or False),
            )
        )
    lab.dismissed = [str(item) for item in data.get("dismissed") or []]
    lab.notes = [str(item) for item in data.get("notes") or []]
    lab.warnings = list(data.get("warnings") or [])
    lab.engine_error = data.get("engineError")
    return lab


def place_host(lab: Lab) -> tuple[float, float]:
    """Sit a new host under the lowest card so it does not cover a port list."""
    if not lab.devices:
        return 80.0, 80.0
    left = min(device.x for device in lab.devices)
    warned = {str(row.get("device") or "").lower() for row in lab.warnings}
    bottom = max(_card_bottom(device, device.name.lower() in warned) for device in lab.devices)
    return float(left), float(bottom + 64)


def place_host_near(lab: Lab, anchor: Device, moving: Device | None = None) -> tuple[float, float]:
    """Sit a host under the device it is cabled to, below hosts already there."""
    warned = {str(row.get("device") or "").lower() for row in lab.warnings}
    bottom = _card_bottom(anchor, anchor.name.lower() in warned)
    cabled = {
        link.b_device.lower()
        for link in lab.links
        if link.a_device.lower() == anchor.name.lower()
    } | {
        link.a_device.lower()
        for link in lab.links
        if link.b_device.lower() == anchor.name.lower()
    }
    for device in lab.devices:
        if device is moving or device.role != "host":
            continue
        if device.name.lower() not in cabled or abs(device.x - anchor.x) > 1:
            continue
        bottom = max(bottom, _card_bottom(device, device.name.lower() in warned))
    return float(anchor.x), float(bottom + 64)


def _card_bottom(device: Device, extra: bool) -> float:
    parsed = parse_config(device.config)
    ports = sum(1 for iface in parsed.interfaces if iface.physical)
    height = 48 + max(ports, 1) * 26 + 12 + (22 if extra else 0)
    return device.y + height


def push_config(device: Device, previous: str) -> None:
    """Remember the config that is about to be replaced."""
    device.config_history.append(previous)
    if len(device.config_history) > 20:
        del device.config_history[:-20]


def apply_inference(lab: Lab) -> None:
    """Replace suggestions. Confirmed links and dismissed keys stay.

    A cable drawn in the lab and then set back to suggested stays. An
    inferred cable is suggested again by this pass.
    """
    payload = {device.name: (device.config, device.neighbor_text) for device in lab.devices}
    result: Inference = infer(payload)
    dismissed = set(lab.dismissed)
    alive = {device.name.lower() for device in lab.devices}
    confirmed = [
        link
        for link in lab.links
        if link.status == "confirmed"
        and link.a_device.lower() in alive
        and link.b_device.lower() in alive
    ]
    confirmed_keys = {
        endpoint_key(link.a_device, link.a_interface, link.b_device, link.b_interface)
        for link in confirmed
    }
    suggestions: list[Link] = []
    suggestion_keys: set[str] = set()
    for item in result.links:
        if item.key in dismissed or item.key in confirmed_keys:
            continue
        suggestions.append(_link_from_suggestion(item, "suggested"))
        suggestion_keys.add(item.key)
    kept: list[Link] = []
    for link in lab.links:
        if link.status == "confirmed" or link.source != "user":
            continue
        if link.a_device.lower() not in alive or link.b_device.lower() not in alive:
            continue
        key = endpoint_key(link.a_device, link.a_interface, link.b_device, link.b_interface)
        if key in dismissed or key in confirmed_keys or key in suggestion_keys:
            continue
        link.status = "suggested"
        kept.append(link)
    lab.links = confirmed + kept + suggestions
    lab.notes = result.notes


def add_user_link(lab: Lab, a_device: str, a_interface: str, b_device: str, b_interface: str) -> Link:
    from dryrun_lab.configparse import canonical_interface

    left = lab.device(a_device)
    right = lab.device(b_device)
    if left is not None:
        a_device = left.name
    if right is not None:
        b_device = right.name
    a_interface = canonical_interface(a_interface)
    b_interface = canonical_interface(b_interface)
    key = endpoint_key(a_device, a_interface, b_device, b_interface)
    lab.dismissed = [item for item in lab.dismissed if item != key]
    for link in lab.links:
        if endpoint_key(link.a_device, link.a_interface, link.b_device, link.b_interface) == key:
            link.status = "confirmed"
            link.source = "user"
            link.reason = "drawn in the lab"
            _seat_linked_host(lab, left, right)
            return link
    link = Link(
        id=link_id(key),
        a_device=a_device,
        a_interface=a_interface,
        b_device=b_device,
        b_interface=b_interface,
        status="confirmed",
        source="user",
        reason="drawn in the lab",
    )
    lab.links.append(link)
    _seat_linked_host(lab, left, right)
    return link


def _seat_linked_host(lab: Lab, left: Device | None, right: Device | None) -> None:
    """Move a host under the switch or router the new cable attaches to."""
    if left is None or right is None:
        return
    if left.role == "host" and right.role != "host":
        host, anchor = left, right
    elif right.role == "host" and left.role != "host":
        host, anchor = right, left
    else:
        return
    host.x, host.y = place_host_near(lab, anchor, host)


def unconfirm_link(lab: Lab, link_id_value: str) -> Link | None:
    """Set a confirmed cable back to suggested."""
    for link in lab.links:
        if link.id == link_id_value:
            link.status = "suggested"
            return link
    return None


def confirm_link(lab: Lab, link_id_value: str) -> Link | None:
    for link in lab.links:
        if link.id == link_id_value:
            link.status = "confirmed"
            return link
    return None


def dismiss_link(lab: Lab, link_id_value: str) -> bool:
    for link in list(lab.links):
        if link.id != link_id_value:
            continue
        key = endpoint_key(link.a_device, link.a_interface, link.b_device, link.b_interface)
        if key not in lab.dismissed:
            lab.dismissed.append(key)
        lab.links = [item for item in lab.links if item.id != link_id_value]
        return True
    return False


def public_lab(lab: Lab) -> dict:
    payload = lab_to_dict(lab)
    by_device: dict[str, list[dict]] = {}
    for warning in lab.warnings:
        by_device.setdefault(str(warning.get("device") or ""), []).append(warning)
    devices = []
    for device, raw in zip(lab.devices, payload["devices"]):
        parsed = parse_config(device.config)
        ordered = sorted(parsed.interfaces, key=lambda iface: interface_key(iface.name))
        raw["interfaces"] = [
            {
                "name": iface.name,
                "description": iface.description,
                "address": iface.address,
                "network": iface.network,
                "physical": iface.physical,
                "shutdown": iface.shutdown,
            }
            for iface in ordered
        ]
        raw["unsimulated"] = by_device.get(device.name, [])
        devices.append(raw)
    payload["devices"] = devices
    payload["unsimulatedCount"] = len(lab.warnings)
    return payload


def _link_from_suggestion(item: Suggestion, status: str) -> Link:
    return Link(
        id=link_id(item.key),
        a_device=item.a_device,
        a_interface=item.a_interface,
        b_device=item.b_device,
        b_interface=item.b_interface,
        status=status,
        source=item.source,
        reason=item.reason,
    )
