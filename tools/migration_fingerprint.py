"""Fingerprint committed Alembic files without contacting a database or a host.

The digest records the Git tree for ``backend/alembic`` and the Git blob for
``backend/alembic.ini``. It is a change detector, not a check of a database's
actual revision or physical schema. See docs/deployment.md before using it.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import re
import subprocess
import sys
from pathlib import Path

_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_FORMAT = "prime-crm/alembic-fingerprint/v1"


class FingerprintError(Exception):
    """The committed migration files cannot be fingerprinted safely."""


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FingerprintError("Git could not inspect the commit") from exc
    if result.returncode != 0:
        raise FingerprintError("Git could not inspect the commit or required path")
    return result.stdout.strip()


def fingerprint(repo: Path, commit: str) -> str:
    """Return a stable SHA-256 fingerprint of the committed Alembic inputs."""
    if not _GIT_SHA.fullmatch(commit):
        raise FingerprintError("commit must be a full 40-character lowercase Git SHA")
    if _git(repo, "cat-file", "-t", commit) != "commit":
        raise FingerprintError("the supplied Git object is not a commit")

    objects: list[str] = []
    for path, required_type in (
        ("backend/alembic", "tree"),
        ("backend/alembic.ini", "blob"),
    ):
        object_id = _git(repo, "rev-parse", "--verify", f"{commit}:{path}")
        if not _GIT_SHA.fullmatch(object_id) or _git(repo, "cat-file", "-t", object_id) != required_type:
            raise FingerprintError(f"{path} is missing or is not a {required_type}")
        objects.append(object_id)

    payload = f"{_FORMAT}\n{objects[0]}\n{objects[1]}\n".encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def matches(repo: Path, commit: str, expected: str) -> bool:
    """Compare against an explicitly recorded, lowercase SHA-256 value."""
    if not _DIGEST.fullmatch(expected):
        raise FingerprintError("expected fingerprint must be 64 lowercase hexadecimal characters")
    return hmac.compare_digest(fingerprint(repo, commit), expected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("print", "verify"))
    parser.add_argument("--commit", required=True, help="full 40-character Git commit SHA")
    parser.add_argument("--repo", type=Path, default=Path("."), help="repository directory")
    parser.add_argument("--expected", help="recorded 64-character fingerprint, required for verify")
    args = parser.parse_args(argv)

    if args.action == "verify" and args.expected is None:
        parser.error("--expected is required for verify")
    if args.action == "print" and args.expected is not None:
        parser.error("--expected is only valid for verify")

    try:
        if args.action == "print":
            print(fingerprint(args.repo, args.commit))
            return 0
        if matches(args.repo, args.commit, args.expected):
            print("Migration fingerprint matches the recorded baseline.")
            return 0
        print("Migration fingerprint differs: review and explicitly authorize the migration before deployment.", file=sys.stderr)
        return 1
    except FingerprintError as exc:
        print(f"Migration fingerprint check failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
