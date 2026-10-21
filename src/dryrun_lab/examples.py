"""Load the synthetic office lab that ships with the repo."""

from __future__ import annotations

import json
from pathlib import Path

from dryrun_lab.configparse import parse_config
from dryrun_lab.paths import example_lab
from dryrun_lab.store import Device, Lab, apply_inference


def load_lab_dir(path: Path) -> Lab:
    topo_path = path / "topology.json"
    if not topo_path.is_file():
        raise FileNotFoundError(f"No topology.json in {path}")
    topo = json.loads(topo_path.read_text(encoding="utf-8"))
    lab = Lab(name=str(topo.get("name") or path.name))
    for raw in topo.get("devices") or []:
        config_path = path / raw["file"]
        config = config_path.read_text(encoding="utf-8")
        neighbor = ""
        if raw.get("neighbors"):
            neighbor_path = path / raw["neighbors"]
            if neighbor_path.is_file():
                neighbor = neighbor_path.read_text(encoding="utf-8")
        parsed = parse_config(config)
        name = parsed.hostname or config_path.stem
        role = raw.get("role") or "router"
        if role not in {"router", "switch"}:
            role = "router"
        lab.devices.append(
            Device(
                name=name,
                role=role,
                config=config,
                neighbor_text=neighbor,
                x=float(raw.get("x") or 80),
                y=float(raw.get("y") or 80),
            )
        )
    apply_inference(lab)
    return lab


def load_office_lab() -> Lab:
    return load_lab_dir(example_lab())
