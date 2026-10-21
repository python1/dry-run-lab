"""Lab documents stored as JSON on this machine."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from dryrun_lab.configparse import parse_config
from dryrun_lab.infer import Inference, Suggestion, endpoint_key, infer, link_id


@dataclass
class Device:
    name: str
    role: str
    config: str = ""
    neighbor_text: str = ""
    x: float = 80
    y: float = 80


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
            )
        )
    lab.dismissed = [str(item) for item in data.get("dismissed") or []]
    lab.notes = [str(item) for item in data.get("notes") or []]
    lab.warnings = list(data.get("warnings") or [])
    lab.engine_error = data.get("engineError")
    return lab


def apply_inference(lab: Lab) -> None:
    """Replace suggestions. Confirmed links and dismissed keys stay."""
    payload = {device.name: (device.config, device.neighbor_text) for device in lab.devices}
    result: Inference = infer(payload)
    dismissed = set(lab.dismissed)
    confirmed = [link for link in lab.links if link.status == "confirmed"]
    confirmed_keys = {
        endpoint_key(link.a_device, link.a_interface, link.b_device, link.b_interface)
        for link in confirmed
    }
    suggestions: list[Link] = []
    for item in result.links:
        if item.key in dismissed or item.key in confirmed_keys:
            continue
        suggestions.append(_link_from_suggestion(item, "suggested"))
    # Drop confirmed links that point at a device which is gone.
    alive = {device.name.lower() for device in lab.devices}
    confirmed = [
        link
        for link in confirmed
        if link.a_device.lower() in alive and link.b_device.lower() in alive
    ]
    lab.links = confirmed + suggestions
    lab.notes = result.notes


def add_user_link(lab: Lab, a_device: str, a_interface: str, b_device: str, b_interface: str) -> Link:
    key = endpoint_key(a_device, a_interface, b_device, b_interface)
    lab.dismissed = [item for item in lab.dismissed if item != key]
    for link in lab.links:
        if endpoint_key(link.a_device, link.a_interface, link.b_device, link.b_interface) == key:
            link.status = "confirmed"
            link.source = "user"
            link.reason = "drawn in the lab"
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
    return link


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
        raw["interfaces"] = [
            {
                "name": iface.name,
                "description": iface.description,
                "address": iface.address,
                "network": iface.network,
                "physical": iface.physical,
                "shutdown": iface.shutdown,
            }
            for iface in parsed.interfaces
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
