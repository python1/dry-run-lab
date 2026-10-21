"""Shell entrypoint. Prints plain text and talks only to the local lab."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dryrun_lab.constants import CREDIT, WEB_HOST, WEB_PORT
from dryrun_lab.examples import load_lab_dir

FOOTER = (
    "Computed simulation. Not a live device and not proof a live network "
    "will behave the same way."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dryrun-lab",
        description="Drive a local Dry Run Lab from the shell.",
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
            print(f"not simulated: {lab.get('unsimulatedCount') or 0}")
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
            if imported.get("engineError"):
                print(f"error: {imported['engineError']}", file=sys.stderr)
                _footer()
                return 1
        elif args.cmd == "devices":
            lab = _request(args.url, "GET", "/api/lab")
            print(f"{'NAME':<12} {'ROLE':<8} {'INTERFACES':<12} NOT SIMULATED")
            for device in lab.get("devices") or []:
                print(
                    f"{device['name']:<12} {device['role']:<8} "
                    f"{len(device.get('interfaces') or []):<12} "
                    f"{len(device.get('unsimulated') or [])}"
                )
            if not lab.get("devices"):
                print("(no devices)")
        elif args.cmd == "links":
            lab = _request(args.url, "GET", "/api/lab")
            print(f"{'ID':<10} {'STATUS':<12} {'A':<28} {'B':<28} WHY")
            for link in lab.get("links") or []:
                left = f"{link['aDevice']} {link['aInterface']}"
                right = f"{link['bDevice']} {link['bInterface']}"
                why = link.get("reason") or link.get("source") or ""
                print(f"{link['id']:<10} {link['status']:<12} {left:<28} {right:<28} {why}")
            for note in lab.get("notes") or []:
                print(f"note: {note}")
            if not lab.get("links"):
                print("(no links)")
        elif args.cmd == "warnings":
            lab = _request(args.url, "GET", "/api/lab")
            print("These lines were NOT simulated")
            any_row = False
            for device in lab.get("devices") or []:
                if args.device and device["name"].lower() != args.device.lower():
                    continue
                rows = device.get("unsimulated") or []
                if not rows:
                    continue
                any_row = True
                print(f"\n{device['name']}")
                for row in rows:
                    line = row.get("line")
                    where = f"line {line}" if line else "line ?"
                    print(f"  {where}: {row.get('text')}")
                    if row.get("detail"):
                        print(f"    {row['detail']}")
            if not any_row:
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
    _footer()
    return 0


def _footer() -> None:
    print(f"\n{FOOTER}")
    print(CREDIT)


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
