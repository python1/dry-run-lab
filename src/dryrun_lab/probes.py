"""Flows worth comparing before and after a config edit.

Each probe is a computed traceroute, not a packet sent anywhere.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from dryrun_lab.configparse import canonical_interface
from dryrun_lab.store import Lab


@dataclass(frozen=True)
class Probe:
    device: str
    ingress: str | None
    src: str
    dst: str
    note: str
    why: str = ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.device.lower(), self.ingress or "", self.src, self.dst)

    def label(self) -> str:
        where = f"enter {self.device} {self.ingress}" if self.ingress else f"from {self.device}"
        text = f"{where}  {self.src} -> {self.dst} ({self.note})"
        if self.why:
            return f"{text}\n    {self.why}"
        return text


def probes_for_lab(lab: Lab) -> list[Probe]:
    found: list[Probe] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(probe: Probe) -> None:
        if probe.key in seen:
            return
        seen.add(probe.key)
        found.append(probe)

    for device in lab.devices:
        subs = _subinterfaces(device.config)
        routed = [item for item in subs if item["prefix"] is not None and item["prefix"] < 32]
        for item in routed:
            others = [other["address"] for other in routed if other["address"] != item["address"]]
            if not others:
                continue
            src = _host(item["address"], item["prefix"])
            if src is None:
                continue
            add(
                Probe(
                    device=device.name,
                    ingress=item["name"],
                    src=src,
                    dst=others[0],
                    note=f"vlan {item['vlan']}" if item["vlan"] else "connected",
                )
            )
        narrow = [item for item in subs if item["prefix"] == 30]
        loops = _loopbacks(lab, device.name)
        for item in narrow:
            for peer, address in loops:
                add(
                    Probe(
                        device=device.name,
                        ingress=None,
                        src=item["address"],
                        dst=address,
                        note=f"routed toward {peer}",
                    )
                )
    _add_acl_probes(lab, add)
    _add_host_probes(lab, add)
    return [_with_why(lab, probe) for probe in found]


def probes_for_acl(lab: Lab, device: str, commands: list[str]) -> list[Probe]:
    from dryrun_lab.configedit import acl_flows, ingress_interfaces

    owner = lab.device(device)
    if owner is None:
        return []
    found: list[Probe] = []
    for acl_name, src, dst in acl_flows(commands):
        interfaces = ingress_interfaces(owner.config, acl_name)
        if not interfaces:
            found.append(Probe(device=owner.name, ingress=None, src=src, dst=dst, note=f"acl {acl_name}"))
            continue
        for iface in interfaces:
            found.append(
                Probe(
                    device=owner.name,
                    ingress=iface,
                    src=src,
                    dst=dst,
                    note=f"acl {acl_name}",
                )
            )
    return [_with_why(lab, probe) for probe in found]


def _add_acl_probes(lab: Lab, add) -> None:
    from dryrun_lab.acls import deny_flows
    from dryrun_lab.configedit import ingress_interfaces

    for device in lab.devices:
        if device.role == "host":
            continue
        for acl_name, src, dst, _text in deny_flows(device.config):
            interfaces = ingress_interfaces(device.config, acl_name)
            if not interfaces:
                add(Probe(device=device.name, ingress=None, src=src, dst=dst, note=f"acl {acl_name}"))
                continue
            for iface in interfaces:
                add(
                    Probe(
                        device=device.name,
                        ingress=iface,
                        src=src,
                        dst=dst,
                        note=f"acl {acl_name}",
                    )
                )


def _add_host_probes(lab: Lab, add) -> None:
    from dryrun_lab.hosts import host_document

    hosts: list[tuple[str, str]] = []
    for device in lab.devices:
        if device.role != "host":
            continue
        document = host_document(device.name, device.config)
        if not document:
            continue
        for iface in document["hostInterfaces"].values():
            address = str(iface.get("prefix") or "").split("/", 1)[0]
            if address:
                hosts.append((device.name, address))
                break
    for source_name, source_ip in hosts:
        for dest_name, dest_ip in hosts:
            if source_name == dest_name:
                continue
            add(
                Probe(
                    device=source_name,
                    ingress=None,
                    src=source_ip,
                    dst=dest_ip,
                    note=f"host {dest_name}",
                )
            )


def _with_why(lab: Lab, probe: Probe) -> Probe:
    parts: list[str] = []
    for address in (probe.src, probe.dst):
        text = _sample_why(lab, address)
        if text and text not in parts:
            parts.append(text)
    if not parts:
        return probe
    return Probe(
        device=probe.device,
        ingress=probe.ingress,
        src=probe.src,
        dst=probe.dst,
        note=probe.note,
        why=" ".join(parts),
    )


def _sample_why(lab: Lab, address: str) -> str | None:
    """Explain a reachability address that is not configured on any interface."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    if not isinstance(ip, ipaddress.IPv4Address):
        return None
    configured = _configured_addresses(lab)
    if any(iface_ip == address for _device, iface_ip, _network in configured):
        return None
    containers = [
        (device, iface_ip, network)
        for device, iface_ip, network in configured
        if ip in network and network.prefixlen <= 30
    ]
    if not containers:
        return None
    containers.sort(key=lambda item: item[2].prefixlen, reverse=True)
    network = containers[0][2]
    named: list[str] = []
    seen: set[str] = set()
    for device, iface_ip, net in configured:
        if net != network or iface_ip == address:
            continue
        label = f"{iface_ip} on {device}"
        if label in seen:
            continue
        seen.add(label)
        named.append(label)
    if not named:
        return None
    shown = named[0] if len(named) == 1 else ", ".join(named)
    return (
        f"{address} is a sample host in {network}, not a configured address ({shown}). "
        "A trace to a configured address stops on that device, so this check uses another host on the subnet."
    )


def _configured_addresses(lab: Lab) -> list[tuple[str, str, ipaddress.IPv4Network]]:
    found: list[tuple[str, str, ipaddress.IPv4Network]] = []
    for device in lab.devices:
        for item in _subinterfaces(device.config):
            network = ipaddress.ip_network(f"{item['address']}/{item['prefix']}", strict=False)
            found.append((device.name, str(item["address"]), network))
    return found


def _subinterfaces(config: str) -> list[dict]:
    current: dict | None = None
    found: list[dict] = []

    def close() -> None:
        nonlocal current
        if current and current.get("address") and current.get("prefix") is not None:
            found.append(current)
        current = None

    for raw in config.splitlines():
        line = raw.strip()
        match = re.match(r"(?i)^interface\s+(\S+)", line)
        if match:
            close()
            current = {
                "name": canonical_interface(match.group(1)),
                "address": None,
                "prefix": None,
                "vlan": None,
            }
            continue
        if current is None:
            continue
        encap = re.match(r"(?i)^encapsulation\s+dot1q\s+(\d+)", line)
        if encap:
            current["vlan"] = int(encap.group(1))
            continue
        addr = re.match(
            r"(?i)^ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
            line,
        )
        if addr and "secondary" not in line.lower():
            current["address"] = addr.group(1)
            current["prefix"] = _prefix(addr.group(2))
    close()
    return found


def _loopbacks(lab: Lab, skip: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for device in lab.devices:
        if device.name.lower() == skip.lower():
            continue
        for item in _subinterfaces(device.config):
            if item["prefix"] == 32 and item["name"].lower().startswith("loopback"):
                found.append((device.name, item["address"]))
    return found


def _prefix(mask: str) -> int:
    return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen


def _host(address: str, prefix: int) -> str | None:
    network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
    if network.prefixlen >= 31:
        return None
    candidate = network.network_address + 50
    gateway = ipaddress.ip_address(address)
    if candidate not in network or candidate in {network.network_address, network.broadcast_address, gateway}:
        candidate = network.network_address + 10
    if candidate == gateway or candidate not in network:
        return None
    return str(candidate)
