"""Compare frontend release source with an operator-verified live backend commit.

This checks Git objects only. It does not contact Render or prove which commit
is actually live, inspect its environment, or verify the Neon schema.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)


class BackendGuardError(ValueError):
    """A sanitized failure to verify the baseline or backend tree."""


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        raise BackendGuardError("The Git backend baseline could not be verified") from None
    return result.stdout.strip()


def verify_backend_tree(repo: Path, *, tested_commit: str, live_commit: str) -> None:
    """Require a known ancestor and identical backend trees at both commits."""
    if not _SHA.fullmatch(tested_commit) or not _SHA.fullmatch(live_commit):
        raise BackendGuardError("Both commit references must be full lowercase Git SHAs")
    if _git(repo, "cat-file", "-t", tested_commit) != "commit" or _git(repo, "cat-file", "-t", live_commit) != "commit":
        raise BackendGuardError("Both references must identify commit objects")
    _git(repo, "merge-base", "--is-ancestor", live_commit, tested_commit)
    tested_tree = _git(repo, "rev-parse", "--verify", f"{tested_commit}:backend")
    live_tree = _git(repo, "rev-parse", "--verify", f"{live_commit}:backend")
    if not _SHA.fullmatch(tested_tree) or not _SHA.fullmatch(live_tree):
        raise BackendGuardError("The backend tree identifier was invalid")
    if _git(repo, "cat-file", "-t", tested_tree) != "tree" or _git(repo, "cat-file", "-t", live_tree) != "tree":
        raise BackendGuardError("The backend path is not a Git tree")
    if tested_tree != live_tree:
        raise BackendGuardError("The tested backend differs from the recorded live backend")


def main() -> int:
    try:
        verify_backend_tree(
            Path.cwd(),
            tested_commit=os.environ.get("GITHUB_SHA", ""),
            live_commit=os.environ.get("PRODUCTION_BACKEND_COMMIT", ""),
        )
    except BackendGuardError:
        print("::error::Backend baseline check failed; no frontend deployment was requested.", file=sys.stderr)
        return 1
    print("Backend Git tree matches the operator-recorded live commit; Render itself was not queried.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
