"""Shell entrypoint. Prints plain text and talks only to the local lab."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dryrun_lab.constants import CREDIT, DISCLAIMER, WEB_HOST, WEB_PORT
from dryrun_lab.examples import load_lab_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dryrun-lab",
        description="Drive a local Dry Run Lab from the shell.",
        epilog=f"{DISCLAIMER}\n\n{CREDIT}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--url",
        default=f"http://{WEB_HOST}:{WEB_PORT}",
        help="Lab URL (loopback)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Engine and lab status")
    sub.add_parser("serve", help="Run the lab server in the foreground")

    load = sub.add_parser("load", help="Load a lab directory of configs")
    load.add_argument("path")

    sub.add_parser("devices", help="List devices")
    sub.add_parser("links", help="List cables, including suggestions")

    warnings = sub.add_parser("warnings", help="Lines that were not simulated")
    warnings.add_argument("--device", default=None)

    show = sub.add_parser("show", help="Run a computed show command")
    show.add_argument("device")
    show.add_argument("command")

    confirm = sub.add_parser("confirm", help="Accept a suggested link")
    confirm.add_argument("link_id")

    dismiss = sub.add_parser("dismiss", help="Reject a suggested link")
    dismiss.add_argument("link_id")

    host = sub.add_parser("host", help="Add, delete, or list hosts")
    host_sub = host.add_subparsers(dest="host_cmd", required=True)
    host_add = host_sub.add_parser("add", help="Add a host with an address and gateway")
    host_add.add_argument("name")
    host_add.add_argument("--ip", required=True, help="Address with prefix, such as 10.40.40.50/24")
    host_add.add_argument("--gw", required=True, help="Default gateway, such as 10.40.40.1")
    host_add.add_argument("--x", type=float, default=None)
    host_add.add_argument("--y", type=float, default=None)
    host_delete = host_sub.add_parser("delete", help="Delete a host")
    host_delete.add_argument("name")
    host_sub.add_parser("list", help="List hosts")

    link = sub.add_parser("link", help="Add, delete, or list cables")
    link_sub = link.add_subparsers(dest="link_cmd", required=True)
    link_add = link_sub.add_parser("add", help="Add a confirmed cable")
    link_add.add_argument("a_device")
    link_add.add_argument("a_interface")
    link_add.add_argument("b_device")
    link_add.add_argument("b_interface")
    link_delete = link_sub.add_parser("delete", help="Delete a cable so it is not inferred again")
    link_delete.add_argument("link_id")
    link_sub.add_parser("list", help="List cables, including suggestions")

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        from dryrun_lab.server import main as serve

        serve()
        return 0
    try:
        if args.cmd == "status":
            body = _request(args.url, "GET", "/api/health")
            lab = _request(args.url, "GET", "/api/lab")
            print(f"engine: {'up' if body.get('engineUp') else 'down'}")
            print(f"lab: {lab.get('name')}")
            print(f"devices: {len(lab.get('devices') or [])}")
            print(f"links: {len(lab.get('links') or [])}")
            missed, ignored = _warning_counts(lab)
            print(f"not simulated: {missed}")
            print(f"ignored when ip routing is enabled: {ignored}")
            if lab.get("engineError"):
                print(f"error: {lab['engineError']}")
        elif args.cmd == "load":
            lab = load_lab_dir(Path(args.path))
            imported = _request(
                args.url,
                "POST",
                "/api/lab/import",
                {
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
                },
            )
            print(f"loaded {imported.get('name')}: {len(imported.get('devices') or [])} devices")
            _disclaimer()
            if imported.get("engineError"):
                print(f"error: {imported['engineError']}", file=sys.stderr)
                return 1
        elif args.cmd == "devices":
            lab = _request(args.url, "GET", "/api/lab")
            print(f"{'NAME':<12} {'ROLE':<8} {'INTERFACES':<12} {'NOT SIMULATED':<16} IGNORED")
            for device in lab.get("devices") or []:
                rows = device.get("unsimulated") or []
                missed = sum(1 for row in rows if row.get("kind") not in {"ignored", "limit"})
                ignored = sum(1 for row in rows if row.get("kind") == "ignored")
                print(
                    f"{device['name']:<12} {device['role']:<8} "
                    f"{len(device.get('interfaces') or []):<12} "
                    f"{missed:<16} {ignored}"
                )
            if not lab.get("devices"):
                print("(no devices)")
        elif args.cmd == "links":
            lab = _request(args.url, "GET", "/api/lab")
            _print_links(lab)
        elif args.cmd == "host":
            if args.host_cmd == "add":
                from dryrun_lab.hosts import host_config

                config = host_config(args.name, args.ip, args.gw)
                body: dict = {"name": args.name, "role": "host", "config": config}
                if args.x is not None:
                    body["x"] = args.x
                if args.y is not None:
                    body["y"] = args.y
                lab = _request(args.url, "POST", "/api/devices", body)
                added = _device(lab, args.name)
                if added is None:
                    raise RuntimeError(f"Host {args.name} was not added")
                print(f"added host {added['name']} at {args.ip} gateway {args.gw}")
                if lab.get("engineError"):
                    print(f"error: {lab['engineError']}", file=sys.stderr)
                    return 1
            elif args.host_cmd == "delete":
                lab = _request(args.url, "DELETE", f"/api/devices/{args.name}")
                print(f"deleted host {args.name}")
                if lab.get("engineError"):
                    print(f"error: {lab['engineError']}", file=sys.stderr)
                    return 1
            else:
                lab = _request(args.url, "GET", "/api/lab")
                _print_hosts(lab)
        elif args.cmd == "link":
            if args.link_cmd == "add":
                lab = _request(
                    args.url,
                    "POST",
                    "/api/links",
                    {
                        "aDevice": args.a_device,
                        "aInterface": args.a_interface,
                        "bDevice": args.b_device,
                        "bInterface": args.b_interface,
                    },
                )
                added = _find_link(lab, args.a_device, args.a_interface, args.b_device, args.b_interface)
                if added is None:
                    raise RuntimeError("Cable was not added")
                print(
                    f"added {added['id']}: {added['aDevice']} {added['aInterface']} — "
                    f"{added['bDevice']} {added['bInterface']}"
                )
                if lab.get("engineError"):
                    print(f"error: {lab['engineError']}", file=sys.stderr)
                    return 1
            elif args.link_cmd == "delete":
                _request(args.url, "DELETE", f"/api/links/{args.link_id}")
                print(f"deleted {args.link_id}")
            else:
                lab = _request(args.url, "GET", "/api/lab")
                _print_links(lab)
        elif args.cmd == "warnings":
            lab = _request(args.url, "GET", "/api/lab")
            found = _print_warnings(lab, args.device, "missed", "These lines were NOT simulated")
            found = _print_warnings(
                lab,
                args.device,
                "ignored",
                "Ignored when ip routing is enabled",
            ) or found
            found = _print_warnings(lab, args.device, "limit", "Not modeled") or found
            if not found:
                print("(none reported)")
        elif args.cmd == "show":
            result = _request(
                args.url,
                "POST",
                "/api/show",
                {"device": args.device, "command": args.command},
            )
            sys.stdout.write(result.get("text") or "")
            if not str(result.get("text") or "").endswith("\n"):
                print()
        elif args.cmd == "confirm":
            _request(args.url, "POST", f"/api/links/{args.link_id}/confirm")
            print(f"confirmed {args.link_id}")
        elif args.cmd == "dismiss":
            _request(args.url, "POST", f"/api/links/{args.link_id}/dismiss")
            print(f"dismissed {args.link_id}")
    except SystemExit:
        raise
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _device(lab: dict, name: str) -> dict | None:
    for device in lab.get("devices") or []:
        if str(device.get("name") or "").lower() == name.lower():
            return device
    return None


def _print_hosts(lab: dict) -> None:
    import ipaddress
    import re

    from dryrun_lab.hosts import gateway_address

    print(f"{'NAME':<12} {'ADDRESS':<20} GATEWAY")
    found = False
    for device in lab.get("devices") or []:
        if device.get("role") != "host":
            continue
        found = True
        config = str(device.get("config") or "")
        address = ""
        match = re.search(
            r"(?im)^\s*ip address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
            config,
        )
        if match:
            iface = ipaddress.ip_interface(f"{match.group(1)}/{match.group(2)}")
            address = f"{iface.ip}/{iface.network.prefixlen}"
        gateway = gateway_address(config) or ""
        print(f"{device['name']:<12} {address:<20} {gateway}")
    if not found:
        print("(no hosts)")


def _print_links(lab: dict) -> None:
    print(f"{'ID':<10} {'STATUS':<16} {'A':<28} {'B':<28} WHY")
    for link in lab.get("links") or []:
        left = f"{link['aDevice']} {link['aInterface']}"
        right = f"{link['bDevice']} {link['bInterface']}"
        why = link.get("reason") or link.get("source") or ""
        status = link.get("status") or ""
        if link.get("down"):
            status = f"{status} down"
        print(f"{link['id']:<10} {status:<16} {left:<28} {right:<28} {why}")
    for note in lab.get("notes") or []:
        print(f"note: {note}")
    if not lab.get("links"):
        print("(no links)")


def _find_link(lab: dict, a_device: str, a_interface: str, b_device: str, b_interface: str) -> dict | None:
    from dryrun_lab.infer import endpoint_key

    want = endpoint_key(a_device, a_interface, b_device, b_interface)
    for link in lab.get("links") or []:
        if endpoint_key(link["aDevice"], link["aInterface"], link["bDevice"], link["bInterface"]) == want:
            return link
    return None


def _disclaimer() -> None:
    print(DISCLAIMER)
    print(CREDIT)


def _warning_counts(lab: dict) -> tuple[int, int]:
    missed = 0
    ignored = 0
    for device in lab.get("devices") or []:
        for row in device.get("unsimulated") or []:
            if row.get("kind") == "ignored":
                ignored += 1
            elif row.get("kind") != "limit":
                missed += 1
    return missed, ignored


def _print_warnings(lab: dict, device_name: str | None, kind: str, heading: str) -> bool:
    printed = False
    any_row = False
    for device in lab.get("devices") or []:
        if device_name and device["name"].lower() != device_name.lower():
            continue
        rows = []
        for row in device.get("unsimulated") or []:
            row_kind = row.get("kind")
            if kind == "ignored" and row_kind == "ignored":
                rows.append(row)
            elif kind == "limit" and row_kind == "limit":
                rows.append(row)
            elif kind == "missed" and row_kind not in {"ignored", "limit"}:
                rows.append(row)
        if not rows:
            continue
        if not printed:
            print(heading)
            printed = True
        any_row = True
        print(f"\n{device['name']}")
        for row in rows:
            line = row.get("line")
            if line:
                print(f"  line {line}: {row.get('text')}")
            else:
                print(f"  {row.get('text')}")
            if row.get("detail"):
                print(f"    {row['detail']}")
    if any_row:
        print()
    return any_row


def _request(base: str, method: str, path: str, body: dict | None = None) -> dict:
    if not base.startswith("http://127.0.0.1") and not base.startswith("http://localhost"):
        raise SystemExit("The lab client only talks to loopback.")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("detail") or detail
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"{exc.code} {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Dry Run Lab is not running. Start it with ./ensure-running "
            f"({exc.reason})"
        ) from None
