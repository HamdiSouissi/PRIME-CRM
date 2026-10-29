"""Validate and package a static frontend without contacting any service.

This preparatory tool handles only public build output. It never reads tokens,
contacts Netlify, publishes files, or accesses the production database. The
commit in build-info.json is an informative claim, not a cryptographic proof of
the origin or integrity of the rest of the archive.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

PUBLIC_API_ORIGIN = "https://prime-crm-cqi3.onrender.com"
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_MAX_FILES = 1_000
_MAX_TOTAL_BYTES = 25 * 1024 * 1024
_FORBIDDEN_SUFFIXES = {".crt", ".db", ".dump", ".key", ".p12", ".pfx", ".pem", ".sqlite", ".sqlite3"}


class InvalidFrontendBuild(ValueError):
    """A release input or the static build is not safe to package."""


def _read_static_files(root: Path) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir():
        raise InvalidFrontendBuild("The build directory is missing or is a symbolic link")

    files: dict[str, bytes] = {}
    total = 0

    def onerror(_error: OSError) -> None:
        raise InvalidFrontendBuild("The build directory cannot be read")

    for directory, subdirectories, filenames in os.walk(root, followlinks=False, onerror=onerror):
        base = Path(directory)
        for name in subdirectories + filenames:
            path = base / name
            if (
                name.startswith(".")
                or "\\" in name
                or any(ord(char) < 32 or ord(char) == 127 for char in name)
                or path.is_symlink()
            ):
                raise InvalidFrontendBuild("The build contains hidden, unsafe, or symbolic-link entries")

        for name in filenames:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if relative == "build-info.json" or path.suffix.lower() in _FORBIDDEN_SUFFIXES:
                raise InvalidFrontendBuild("The build contains a reserved or forbidden file")
            if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                raise InvalidFrontendBuild("The build contains a non-regular file")
            if len(files) >= _MAX_FILES:
                raise InvalidFrontendBuild("The build contains too many files")
            with path.open("rb") as source:
                content = source.read(_MAX_TOTAL_BYTES - total + 1)
            total += len(content)
            if total > _MAX_TOTAL_BYTES:
                raise InvalidFrontendBuild("The build exceeds the static archive size limit")
            files[relative] = content
    return files


def _parse_headers(content: bytes) -> dict[str, dict[str, str]]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise InvalidFrontendBuild("Invalid static headers") from None

    blocks: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not raw[0].isspace():
            if line in blocks:
                raise InvalidFrontendBuild("Duplicate static header paths")
            current = blocks[line] = {}
        else:
            if current is None or ":" not in line:
                raise InvalidFrontendBuild("Invalid static headers")
            name, value = line.split(":", 1)
            name = name.strip().lower()
            if not name or name in current:
                raise InvalidFrontendBuild("Invalid or duplicate static headers")
            current[name] = value.strip()
    return blocks


def validate_files(files: dict[str, bytes], api_origin: str) -> None:
    """Fail closed on missing hosting rules, unsafe origin, or an invalid build."""
    if api_origin != PUBLIC_API_ORIGIN:
        raise InvalidFrontendBuild("The configured public API origin is not the expected origin")
    if not files.get("index.html") or files.get("_redirects", b"").strip() != b"/* /index.html 200":
        raise InvalidFrontendBuild("The static entry point or SPA redirect is missing")

    headers = _parse_headers(files.get("_headers", b""))
    general = headers.get("/*", {})
    expected = {
        "x-frame-options": "DENY",
        "content-security-policy": "frame-ancestors 'none'",
        "x-content-type-options": "nosniff",
        "referrer-policy": "strict-origin-when-cross-origin",
    }
    if any(general.get(name) != value for name, value in expected.items()):
        raise InvalidFrontendBuild("Required static security headers are missing")
    if headers.get("/build-info.json", {}).get("cache-control") != "no-store":
        raise InvalidFrontendBuild("The build information must not be cached")

    js_files = {path: data for path, data in files.items() if path.startswith("assets/") and path.endswith(".js")}
    if not any(api_origin.encode("ascii") in data for data in js_files.values()):
        raise InvalidFrontendBuild("The expected API origin is missing from the JavaScript")
    if not any(("/" + path).encode("utf-8") in files["index.html"] for path in js_files):
        raise InvalidFrontendBuild("The entry point does not reference a bundled JavaScript file")


def prepare_archive(dist: Path, output: Path, commit: str, api_origin: str) -> None:
    """Create a deterministic ZIP outside dist only after all validation passes."""
    if not _COMMIT.fullmatch(commit):
        raise InvalidFrontendBuild("A full lowercase Git commit SHA is required")
    if output.suffix.lower() != ".zip":
        raise InvalidFrontendBuild("The output must be a ZIP file")
    resolved_root = dist.resolve()
    resolved_output = output.resolve()
    if resolved_output == resolved_root or resolved_root in resolved_output.parents:
        raise InvalidFrontendBuild("The output must be outside the build directory")

    files = _read_static_files(dist)
    validate_files(files, api_origin)
    files["build-info.json"] = (json.dumps({"commit": commit}, separators=(",", ":")) + "\n").encode("ascii")

    # No partially written release archive is left behind if packaging fails.
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".frontend-", suffix=".zip", delete=False) as handle:
            temporary = Path(handle.name)
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for name, content in sorted(files.items()):
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content, compresslevel=6)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and package a frontend build without deploying it")
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--api-origin", required=True)
    arguments = parser.parse_args()
    try:
        prepare_archive(arguments.dist, arguments.output, arguments.commit, arguments.api_origin)
    except (InvalidFrontendBuild, OSError, ValueError):
        # Avoid echoing paths or environment values. No network request was made.
        print("::error::Frontend build validation or packaging failed; nothing was published.", file=sys.stderr)
        return 1
    print("Frontend archive validated and prepared locally; nothing was published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
