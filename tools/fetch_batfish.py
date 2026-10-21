#!/usr/bin/env python3
"""Fetch the official Batfish all-in-one jar.

GitHub releases of batfish/batfish attach no jar, and Maven Central has no
org.batfish artifacts. The jar is published inside the official
batfish/allinone image. This downloads that image layer from Docker Hub's
registry and extracts the jar, question templates, and the matching client
wheel. It does not start a container.
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = "batfish/allinone"
# amd64 layer of batfish/allinone:latest published with Batfish v2026.08.27.
# Manifest sha256:a8abaa304b22c13024e426ca1bdf158d0be258af44a5b538fb8f9ef74ac9d58f
PINNED_LAYER = "sha256:53a5a598343f477bae7c97f39174d545529d2d080ed30ec3652c6e3e7ae0ac70"
KEEP_PREFIXES = ("questions/",)
KEEP_FILES = {"allinone-bundle.jar", "log4j2.yaml"}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: fetch_batfish.py DEST", file=sys.stderr)
        return 2
    dest = Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "allinone-bundle.jar").is_file() and (dest / "questions" / "stable").is_dir():
        return 0
    blob = _download_pinned() or _download_by_scanning()
    _extract(blob, dest)
    if not (dest / "allinone-bundle.jar").is_file():
        print("official jar was not in the image layer", file=sys.stderr)
        return 1
    (dest / "provenance.json").write_text(
        json.dumps(
            {
                "image": REPO,
                "layer": PINNED_LAYER,
                "source": "registry-1.docker.io",
                "release": "v2026.08.27",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def _download_pinned() -> bytes | None:
    try:
        return _blob(PINNED_LAYER)
    except Exception as exc:
        print(f"pinned layer failed ({exc}); resolving the latest manifest", file=sys.stderr)
        return None


def _download_by_scanning() -> bytes:
    token = _token()
    index = _json(
        f"https://registry-1.docker.io/v2/{REPO}/manifests/latest",
        token,
        "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json",
    )
    digest = None
    for item in index.get("manifests") or []:
        platform = item.get("platform") or {}
        if platform.get("os") == "linux" and platform.get("architecture") == "amd64":
            digest = item["digest"]
            break
    if not digest:
        raise RuntimeError("no linux/amd64 manifest")
    manifest = _json(
        f"https://registry-1.docker.io/v2/{REPO}/manifests/{digest}",
        token,
        "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json",
    )
    candidates = [
        layer
        for layer in manifest.get("layers") or []
        if 40_000_000 <= int(layer.get("size") or 0) <= 120_000_000
    ]
    for layer in candidates:
        blob = _blob(layer["digest"])
        names = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz").getnames()
        if "allinone-bundle.jar" in names:
            return blob
    raise RuntimeError("could not find allinone-bundle.jar in the official image")


def _extract(blob: bytes, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member in archive.getmembers():
            name = member.name
            if name in KEEP_FILES or name.startswith(KEEP_PREFIXES) or name.startswith("pybatfish-"):
                archive.extract(member, dest, filter="data")


class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Docker Hub answers a blob GET with a redirect to a signed CDN URL.

    urllib forwards the registry bearer token onto that hop, and the CDN
    rejects it. The signed URL does not need the token.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


def _open(request: urllib.request.Request):
    opener = urllib.request.build_opener(_DropAuthOnRedirect)
    return opener.open(request, timeout=180)


def _blob(digest: str) -> bytes:
    token = _token()
    request = urllib.request.Request(
        f"https://registry-1.docker.io/v2/{REPO}/blobs/{digest}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "dryrun-lab"},
    )
    with _open(request) as response:
        return response.read()


def _token() -> str:
    url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{REPO}:pull"
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read())["token"]


def _json(url: str, token: str, accept: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": accept},
    )
    with _open(request) as response:
        return json.loads(response.read())


if __name__ == "__main__":
    raise SystemExit(main())
