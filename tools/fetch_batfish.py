#!/usr/bin/env python3
"""Fetch the official Batfish all-in-one jar.

GitHub releases of batfish/batfish attach no jar, and Maven Central has no
org.batfish artifacts. The jar is published inside the official
batfish/allinone image. This downloads that image layer from Docker Hub's
registry and extracts the jar, question templates, and the matching client
wheel. It does not start a container.

The layer and the jar are checked against pinned sha256 values. A mismatch
stops the install. There is no fallback to a floating tag.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = "batfish/allinone"
RELEASE = "v2026.08.27"
# amd64 layer of batfish/allinone:v2026.08.27.
# Manifest sha256:a8abaa304b22c13024e426ca1bdf158d0be258af44a5b538fb8f9ef74ac9d58f
PINNED_LAYER = "sha256:53a5a598343f477bae7c97f39174d545529d2d080ed30ec3652c6e3e7ae0ac70"
PINNED_JAR = "7552e1380e79379b17e200b80d84c1671f689cb63a0d338678c1c4675157310f"
KEEP_PREFIXES = ("questions/",)
KEEP_FILES = {"allinone-bundle.jar", "log4j2.yaml"}


class BatfishPinError(RuntimeError):
    """The downloaded layer or jar does not match the pinned sha256."""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: fetch_batfish.py DEST", file=sys.stderr)
        return 2
    dest = Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    try:
        _ensure(dest)
    except BatfishPinError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _ensure(dest: Path) -> None:
    jar = dest / "allinone-bundle.jar"
    ready = jar.is_file() and (dest / "questions" / "stable").is_dir()
    if ready:
        try:
            _check_jar(jar.read_bytes())
        except BatfishPinError as exc:
            print(
                f"{exc} Cached copy rejected. Downloading the pinned layer once.",
                file=sys.stderr,
            )
            jar.unlink()
        else:
            _write_provenance(dest, cached=True)
            return
    blob = _blob(PINNED_LAYER)
    _check_blob(blob)
    _extract(blob, dest)
    if not jar.is_file():
        raise BatfishPinError("official jar was not in the pinned image layer")
    _check_jar(jar.read_bytes())
    _write_provenance(dest, cached=False)


def _check_blob(blob: bytes) -> None:
    digest = hashlib.sha256(blob).hexdigest()
    expected = PINNED_LAYER.split(":", 1)[1]
    if digest != expected:
        raise BatfishPinError(
            "Batfish layer sha256 mismatch: "
            f"got {digest}, expected {expected}. Refusing to use it."
        )


def _check_jar(data: bytes) -> None:
    digest = hashlib.sha256(data).hexdigest()
    if digest != PINNED_JAR:
        raise BatfishPinError(
            "Batfish jar sha256 mismatch: "
            f"got {digest}, expected {PINNED_JAR}. Refusing to use it."
        )


def _write_provenance(dest: Path, cached: bool) -> None:
    jar = dest / "allinone-bundle.jar"
    digest = hashlib.sha256(jar.read_bytes()).hexdigest()
    info = {
        "image": REPO,
        "layer": PINNED_LAYER,
        "source": "registry-1.docker.io",
        "release": RELEASE,
        "sha256": digest,
        "expectedSha256": PINNED_JAR,
        "cached": cached,
    }
    (dest / "provenance.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(
        "batfish source={source} image={image} version={release} layer={layer} "
        "sha256={sha256} expected={expectedSha256} cached={cached}".format(**info)
    )
    print(f"layer sha256 verified: {PINNED_LAYER}")


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


if __name__ == "__main__":
    raise SystemExit(main())
