"""Talk to a local Batfish service. Configs never leave this machine."""

from __future__ import annotations

import json
import logging
import re
import shutil
import socket
import threading
from pathlib import Path
from typing import Any

from dryrun_lab.configparse import canonical_interface
from dryrun_lab.constants import ENGINE_HOST, ENGINE_PORT, SIMULATED_BANNER
from dryrun_lab.paths import data_home
from dryrun_lab.showfmt import (
    command_help,
    normalize_command,
    show_ip_interface_brief,
    show_ip_route,
    show_running_config,
    show_unsimulated,
)
from dryrun_lab.store import Lab, Link

log = logging.getLogger("dryrun_lab.engine")


class EngineUnavailable(RuntimeError):
    pass


class Engine:
    def __init__(self, host: str = ENGINE_HOST, port: int = ENGINE_PORT) -> None:
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._session: Any = None
        self._interfaces: dict[str, list[dict[str, Any]]] = {}
        self._routes: dict[str, list[dict[str, Any]]] = {}
        self._ready = False

    def healthy(self) -> bool:
        probe = socket.socket()
        probe.settimeout(0.4)
        try:
            probe.connect((self.host, self.port))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    def recompute(self, lab: Lab) -> None:
        if not lab.devices:
            self._interfaces = {}
            self._routes = {}
            self._ready = False
            lab.warnings = []
            lab.engine_error = None
            return
        if not self.healthy():
            lab.engine_error = "Analysis engine is not running on 127.0.0.1:%s." % self.port
            self._ready = False
            return
        try:
            with self._lock:
                snapshot = self._write_snapshot(lab)
                session = self._client()
                session.set_network("dryrun")
                session.init_snapshot(str(snapshot), name="lab", overwrite=True)
                warnings = _warnings(session)
                self._interfaces = _interfaces(session)
                self._routes = _routes(session)
                self._ready = True
            lab.warnings = _attach_devices(warnings, lab)
            lab.engine_error = None
        except Exception as exc:  # Batfish client raises its own types
            log.exception("recompute failed")
            lab.engine_error = f"Analysis failed: {exc}"
            self._ready = False

    def show(self, lab: Lab, device_name: str, command: str) -> str:
        device = lab.device(device_name)
        if device is None:
            raise KeyError(device_name)
        kind = normalize_command(command)
        if kind is None:
            if "|" in command:
                text = "% Pipes are not simulated in this version.\n\n" + command_help()
            else:
                text = "% Unrecognized command.\n\n" + command_help()
            return _wrap(device.name, command, text)
        if kind == "running-config":
            rows = [row for row in lab.warnings if row.get("device") == device.name]
            return _wrap(device.name, command, show_running_config(device.config, rows))
        if kind == "warnings":
            rows = [row for row in lab.warnings if row.get("device") == device.name]
            return _wrap(device.name, command, show_unsimulated(device.name, rows))
        if not self._ready:
            if lab.engine_error:
                raise EngineUnavailable(lab.engine_error)
            raise EngineUnavailable("Nothing has been computed yet.")
        key = device.name.lower()
        if kind == "interfaces":
            body = show_ip_interface_brief(self._interfaces.get(key, []))
        else:
            body = show_ip_route(self._routes.get(key, []))
        return _wrap(device.name, command, body)

    def _client(self) -> Any:
        if self._session is not None:
            return self._session
        logging.getLogger("pybatfish").setLevel(logging.ERROR)
        from pybatfish.client.session import Session

        self._session = Session(host=self.host, port=self.port)
        return self._session

    def _write_snapshot(self, lab: Lab) -> Path:
        root = data_home() / "snapshot"
        if root.exists():
            shutil.rmtree(root)
        configs = root / "configs"
        configs.mkdir(parents=True)
        for device in lab.devices:
            safe = _safe_name(device.name)
            (configs / f"{safe}.cfg").write_text(device.config, encoding="utf-8")
        edges = []
        for link in lab.links:
            if link.status != "confirmed":
                continue
            edges.append(_edge(link))
        topo_dir = root / "batfish"
        topo_dir.mkdir()
        (topo_dir / "layer1_topology.json").write_text(
            json.dumps({"edges": edges}, indent=2) + "\n",
            encoding="utf-8",
        )
        return root


def _wrap(device: str, command: str, body: str) -> str:
    return f"{device}# {command.strip()}\n{SIMULATED_BANNER}\n\n{body}"


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return cleaned or "device"


def _edge(link: Link) -> dict[str, Any]:
    return {
        "node1": {
            "hostname": link.a_device.lower(),
            "interfaceName": canonical_interface(link.a_interface),
        },
        "node2": {
            "hostname": link.b_device.lower(),
            "interfaceName": canonical_interface(link.b_interface),
        },
    }


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    return json.loads(frame.to_json(orient="records"))


def _warnings(session: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    try:
        parsed = _records(session.q.parseWarning().answer().frame())
    except Exception:
        log.exception("parseWarning failed")
        parsed = []
    for row in parsed:
        filename = str(row.get("Filename") or "")
        text = str(row.get("Text") or "").strip()
        line = _as_int(row.get("Line"))
        key = (filename, str(line), text)
        if key in seen or not text:
            continue
        seen.add(key)
        rows.append(
            {
                "file": filename,
                "line": line,
                "text": text,
                "detail": str(row.get("Comment") or "This line was not recognized"),
                "kind": "parse",
            }
        )
    try:
        issues = _records(session.q.initIssues().answer().frame())
    except Exception:
        log.exception("initIssues failed")
        issues = []
    for row in issues:
        kind = str(row.get("Type") or "")
        if "parse" in kind.lower():
            continue
        text = str(row.get("Line_Text") or "").strip()
        detail = str(row.get("Details") or kind)
        sources = row.get("Source_Lines") or []
        if isinstance(sources, str):
            sources = [sources]
        if not sources:
            sources = [""]
        for source in sources:
            filename, line = _split_source(str(source))
            line = _as_int(line)
            key = (filename, str(line), text or detail)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "file": filename,
                    "line": line,
                    "text": text or detail,
                    "detail": detail,
                    "kind": "convert",
                }
            )
    return rows


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _split_source(source: str) -> tuple[str, int | None]:
    # configs/R1.cfg:[43] or configs/R1.cfg:43
    match = re.match(r"^(?P<file>.+?):\[?(?P<line>\d+)", source)
    if not match:
        return source, None
    return match.group("file"), int(match.group("line"))


def _attach_devices(rows: list[dict[str, Any]], lab: Lab) -> list[dict[str, Any]]:
    by_file = {}
    for device in lab.devices:
        by_file[_safe_name(device.name).lower() + ".cfg"] = device.name
        by_file[device.name.lower() + ".cfg"] = device.name
    attached = []
    for row in rows:
        filename = str(row.get("file") or "")
        stem = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
        device = by_file.get(stem)
        attached.append({**row, "device": device})
    return attached


_IFACE_REF = re.compile(r"^([^[]+)\[(.+)]$")


def _interfaces(session: Any) -> dict[str, list[dict[str, Any]]]:
    frame = session.q.interfaceProperties().answer().frame()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in _records(frame):
        ref = row.get("Interface")
        if isinstance(ref, dict):
            node = str(ref.get("hostname") or "")
            name = str(ref.get("interface") or "")
        else:
            match = _IFACE_REF.match(str(ref or ""))
            if not match:
                continue
            node, name = match.group(1), match.group(2)
        if not node or not name:
            continue
        grouped.setdefault(node.lower(), []).append(
            {
                "name": name,
                "address": row.get("Primary_Address"),
                "active": bool(row.get("Active")),
                "admin_up": bool(row.get("Admin_Up")) if row.get("Admin_Up") is not None else True,
            }
        )
    return grouped


def _routes(session: Any) -> dict[str, list[dict[str, Any]]]:
    frame = session.q.routes().answer().frame()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in _records(frame):
        node = str(row.get("Node") or "").lower()
        grouped.setdefault(node, []).append(
            {
                "network": row.get("Network"),
                "next_hop": row.get("Next_Hop"),
                "protocol": row.get("Protocol"),
                "metric": row.get("Metric"),
                "admin_distance": row.get("Admin_Distance"),
                "vrf": row.get("VRF"),
            }
        )
    return grouped
