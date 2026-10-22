"""Local HTTP API and the lab UI. Bound to loopback only."""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.requests import Request

from dryrun_lab.constants import CREDIT, DISCLAIMER, WEB_HOST, WEB_PORT
from dryrun_lab.version import version
from dryrun_lab.engine import Engine, EngineUnavailable
from dryrun_lab.hosts import host_config
from dryrun_lab.ioscheck import same_displayed_config
from dryrun_lab.examples import load_office_lab
from dryrun_lab.paths import data_home, static_dir
from dryrun_lab.probes import probes_for_interfaces
from dryrun_lab.store import (
    Device,
    Store,
    add_user_link,
    apply_inference,
    confirm_link,
    dismiss_link,
    place_host,
    public_lab,
    unconfirm_link,
    push_config,
)

log = logging.getLogger("dryrun_lab.server")
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
_store = Store(data_home() / "lab.json")
_engine = Engine()


def warm_saved_lab() -> None:
    """Recompute the lab saved on disk once the engine is listening.

    A new process has an empty cache. Show commands would otherwise answer
    503 until somebody loaded the lab again.
    """
    try:
        if not _store.lab.devices or not _engine.healthy():
            return
        with _store.lock:
            if _engine._ready:
                return
            _engine.recompute(_store.lab)
            _store.save()
    except Exception:
        log.exception("could not recompute the saved lab at startup")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    warm_saved_lab()
    yield


app = FastAPI(title="Dry Run Lab", docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan)


@app.exception_handler(Exception)
async def _json_error(_request: Request, exc: Exception) -> JSONResponse:
    """Every failure is JSON. The page does not have to parse a plain-text 500."""
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse({"detail": detail}, status_code=exc.status_code)
    if isinstance(exc, EngineUnavailable):
        return JSONResponse({"detail": str(exc)}, status_code=503)
    log.exception("request failed")
    return JSONResponse({"detail": "The change was not saved."}, status_code=500)


class DeviceIn(BaseModel):
    name: str
    role: str = "router"
    config: str = ""
    neighborText: str = ""
    x: float | None = None
    y: float | None = None
    ip: str = ""
    mask: str = ""
    gateway: str = ""


class DeviceUpdate(BaseModel):
    config: str | None = None
    neighborText: str | None = None
    x: float | None = None
    y: float | None = None
    role: str | None = None


class LinkIn(BaseModel):
    aDevice: str
    aInterface: str
    bDevice: str
    bInterface: str


class ShowIn(BaseModel):
    device: str
    command: str = Field(min_length=1)


class ImportDevice(BaseModel):
    name: str
    role: str = "router"
    config: str = ""
    neighborText: str = ""
    x: float = 80
    y: float = 80


class ImportIn(BaseModel):
    name: str = "imported"
    devices: list[ImportDevice]


def _refresh(recompute: bool) -> dict:
    with _store.lock:
        apply_inference(_store.lab)
        if recompute:
            _engine.recompute(_store.lab)
        _store.save()
        return _payload()


def _payload() -> dict:
    body = public_lab(_store.lab)
    body["disclaimer"] = DISCLAIMER
    body["credit"] = CREDIT
    body["version"] = version()
    body["engineUp"] = _engine.healthy()
    return body


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "engineUp": _engine.healthy(),
        "computed": _engine._ready,
        "disclaimer": DISCLAIMER,
        "credit": CREDIT,
        "version": version(),
    }


@app.get("/api/lab")
def get_lab() -> dict:
    with _store.lock:
        return _payload()


@app.post("/api/lab/load-example")
def load_example() -> dict:
    lab = load_office_lab()
    with _store.lock:
        _store.lab = lab
        _engine.recompute(_store.lab)
        _store.save()
        return _payload()


@app.post("/api/lab/import")
def import_lab(body: ImportIn) -> dict:
    from dryrun_lab.store import Lab

    lab = Lab(name=body.name)
    for item in body.devices:
        _check_name(item.name)
        if item.role not in _ROLES:
            raise HTTPException(400, "Role must be router, switch, or host")
        lab.devices.append(
            Device(
                name=item.name,
                role=item.role,
                config=item.config,
                neighbor_text=item.neighborText,
                x=item.x,
                y=item.y,
            )
        )
    apply_inference(lab)
    with _store.lock:
        _store.lab = lab
        _engine.recompute(_store.lab)
        _store.save()
        return _payload()


@app.post("/api/devices")
def add_device(body: DeviceIn) -> dict:
    _check_name(body.name)
    if body.role not in _ROLES:
        raise HTTPException(400, "Role must be router, switch, or host")
    with _store.lock:
        if _store.lab.device(body.name):
            raise HTTPException(409, "A device with that name already exists")
        if body.role == "host" and not body.config:
            config = _host_config_from_body(body)
        else:
            config = body.config or _blank_config(body.name, body.role)
        x, y = _placed(body, _store.lab)
        _store.lab.devices.append(
            Device(
                name=body.name,
                role=body.role,
                config=config,
                neighbor_text=body.neighborText,
                x=x,
                y=y,
            )
        )
        if _store.lab.name == "untitled":
            _store.lab.name = "lab"
        apply_inference(_store.lab)
        _engine.recompute(_store.lab)
        _store.save()
        return _payload()


@app.put("/api/devices/{name}")
def update_device(name: str, body: DeviceUpdate) -> dict:
    with _store.lock:
        device = _store.lab.device(name)
        if device is None:
            raise HTTPException(404, "No such device")
        structural = False
        if body.config is not None and not same_displayed_config(device.config, body.config):
            push_config(device, device.config)
            device.config = body.config.replace("\r\n", "\n")
            structural = True
        if body.neighborText is not None and body.neighborText != device.neighbor_text:
            device.neighbor_text = body.neighborText
            structural = True
        if body.role in _ROLES:
            device.role = body.role
        if body.x is not None:
            device.x = body.x
        if body.y is not None:
            device.y = body.y
        if structural:
            apply_inference(_store.lab)
            _engine.recompute(_store.lab)
        _store.save()
        return _payload()


@app.delete("/api/devices/{name}")
def delete_device(name: str) -> dict:
    with _store.lock:
        before = len(_store.lab.devices)
        _store.lab.devices = [
            device for device in _store.lab.devices if device.name.lower() != name.lower()
        ]
        if len(_store.lab.devices) == before:
            raise HTTPException(404, "No such device")
        apply_inference(_store.lab)
        _engine.recompute(_store.lab)
        _store.save()
        return _payload()


@app.post("/api/links")
def create_link(body: LinkIn) -> dict:
    with _store.lock:
        if _store.lab.device(body.aDevice) is None or _store.lab.device(body.bDevice) is None:
            raise HTTPException(404, "Both devices must exist")
        add_user_link(_store.lab, body.aDevice, body.aInterface, body.bDevice, body.bInterface)
        _engine.recompute(_store.lab)
        _store.save()
        return _payload()


@app.delete("/api/links/{link_id}")
def delete_link(link_id: str) -> dict:
    with _store.lock:
        if not dismiss_link(_store.lab, link_id):
            raise HTTPException(404, "No such link")
        _engine.recompute(_store.lab)
        _store.save()
        return _payload()


@app.post("/api/links/{link_id}/confirm")
def confirm(link_id: str) -> dict:
    with _store.lock:
        link = next((item for item in _store.lab.links if item.id == link_id), None)
        if link is None:
            raise HTTPException(404, "No such link")
        headline = (
            f"Confirmed {link.a_device} {link.a_interface} - "
            f"{link.b_device} {link.b_interface}."
        )
        extra = probes_for_interfaces(_store.lab, link.a_device, link.a_interface)
        extra += probes_for_interfaces(_store.lab, link.b_device, link.b_interface)
        notice = _summarize(
            _store.lab,
            lambda: confirm_link(_store.lab, link_id),
            headline,
            extra,
        )
        _store.save()
        payload = _payload()
        payload["notice"] = notice
        return payload


@app.post("/api/links/{link_id}/unconfirm")
def unconfirm(link_id: str) -> dict:
    with _store.lock:
        link = next((item for item in _store.lab.links if item.id == link_id), None)
        if link is None:
            raise HTTPException(404, "No such link")
        if link.status == "suggested":
            payload = _payload()
            payload["unconfirm"] = "already"
            return payload
        headline = (
            f"Suggested {link.a_device} {link.a_interface} - "
            f"{link.b_device} {link.b_interface}."
        )
        extra = probes_for_interfaces(_store.lab, link.a_device, link.a_interface)
        extra += probes_for_interfaces(_store.lab, link.b_device, link.b_interface)
        notice = _summarize(
            _store.lab,
            lambda: unconfirm_link(_store.lab, link_id),
            headline,
            extra,
        )
        _store.save()
        payload = _payload()
        payload["unconfirm"] = "suggested"
        payload["notice"] = notice
        return payload


@app.post("/api/links/{link_id}/dismiss")
def dismiss(link_id: str) -> dict:
    with _store.lock:
        link = next((item for item in _store.lab.links if item.id == link_id), None)
        if link is None:
            raise HTTPException(404, "No such link")
        headline = (
            f"Rejected {link.a_device} {link.a_interface} - "
            f"{link.b_device} {link.b_interface}."
        )
        extra = probes_for_interfaces(_store.lab, link.a_device, link.a_interface)
        extra += probes_for_interfaces(_store.lab, link.b_device, link.b_interface)
        notice = _summarize(
            _store.lab,
            lambda: dismiss_link(_store.lab, link_id),
            headline,
            extra,
        )
        _store.save()
        payload = _payload()
        payload["notice"] = notice
        return payload


@app.post("/api/recompute")
def recompute() -> dict:
    return _refresh(True)


@app.post("/api/show")
def show(body: ShowIn) -> JSONResponse:
    with _store.lock:
        try:
            result = _engine.show_result(_store.lab, body.device, body.command)
        except KeyError:
            raise HTTPException(404, "No such device") from None
        except EngineUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        if result.changed:
            _store.save()
        payload = {
            "device": body.device,
            "command": body.command,
            "text": result.text,
            "prompt": result.prompt,
            "ok": result.ok,
            "simulated": True,
            "disclaimer": DISCLAIMER,
        }
        if result.changed:
            payload["lab"] = _payload()
    return JSONResponse(payload)


_ROLES = {"router", "switch", "host"}


def _summarize(lab, mutate, headline: str, extra: list) -> str:
    """Same summary as a config edit. A down engine still applies the change."""
    try:
        return _engine.summarize_mutation(lab, mutate, headline, extra)
    except EngineUnavailable as exc:
        mutate()
        _engine.recompute(lab)
        return f"{headline}\n\n{exc}\n"


def _placed(body: DeviceIn, lab) -> tuple[float, float]:
    if body.x is not None and body.y is not None:
        return body.x, body.y
    if body.role == "host":
        x, y = place_host(lab)
    else:
        x, y = 120.0, 120.0
    return body.x if body.x is not None else x, body.y if body.y is not None else y


def _blank_config(name: str, role: str) -> str:
    return f"hostname {name}\n!\n"


def _host_config_from_body(body: DeviceIn) -> str:
    import ipaddress

    if not body.ip.strip() or not body.mask.strip() or not body.gateway.strip():
        raise HTTPException(400, "A host needs an IP address, a mask, and a gateway")
    try:
        ipaddress.ip_address(body.ip.strip())
        if "/" in body.mask:
            prefix = int(body.mask.strip().lstrip("/"))
        elif body.mask.strip().isdigit():
            prefix = int(body.mask.strip())
        else:
            prefix = ipaddress.IPv4Network(f"0.0.0.0/{body.mask.strip()}").prefixlen
        return host_config(body.name, f"{body.ip.strip()}/{prefix}", body.gateway.strip())
    except (ValueError, ipaddress.AddressValueError) as exc:
        raise HTTPException(400, str(exc)) from None


def _check_name(name: str) -> None:
    if not _NAME.match(name):
        raise HTTPException(400, "Use a short name: letters, digits, _ or -")


def _static_response(path: str) -> FileResponse:
    root = static_dir().resolve()
    index = root / "index.html"
    if not index.is_file():
        raise HTTPException(503, "UI build is missing")
    rel = path.lstrip("/")
    target = (root / rel).resolve() if rel else index
    if target != root and root not in target.parents:
        raise HTTPException(404)
    if rel and target.is_file():
        return FileResponse(target)
    return FileResponse(index)


@app.get("/")
def index() -> FileResponse:
    return _static_response("")


@app.get("/{path:path}")
def assets(path: str) -> FileResponse:
    if path.startswith("api/"):
        raise HTTPException(404)
    return _static_response(path)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT, log_level="info")


if __name__ == "__main__":
    main()
