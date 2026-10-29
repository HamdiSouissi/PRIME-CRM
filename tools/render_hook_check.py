"""Check a Render deploy-hook URL's shape without contacting any service.

A hook is a secret: never print its value, put it in a command-line argument,
open it in a browser, or log a parser exception that could contain it. A valid
shape does not establish that the key works or that the service is correct.
"""

from __future__ import annotations

import os
import re
import sys
from urllib.parse import parse_qsl, urlsplit

_SERVICE_PATH = re.compile(r"/deploy/srv-[A-Za-z0-9]+\Z")


class InvalidHook(ValueError):
    """The hook is absent or is not in the documented Render URL format."""


def validate_hook(value: str) -> None:
    """Validate a copied service hook locally; make no HTTP requests."""
    try:
        if (
            not value
            or not value.isascii()
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
            or "#" in value
            or ";" in value
        ):
            raise InvalidHook

        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or parts.netloc != "api.render.com"
            or not _SERVICE_PATH.fullmatch(parts.path)
            or not parts.query
        ):
            raise InvalidHook

        parameters = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
        if len(parameters) != 1 or parameters[0][0] != "key" or not parameters[0][1]:
            raise InvalidHook
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in parameters[0][1]):
            raise InvalidHook
    except (ValueError, UnicodeError):
        # Never include a parser exception or any part of the hook in logs.
        raise InvalidHook("Render deploy hook is missing or has an unexpected format") from None


def main() -> int:
    try:
        validate_hook(os.environ.get("RENDER_DEPLOY_HOOK_URL", ""))
    except InvalidHook:
        print("::error::Render deploy hook is missing or has an unexpected format; no request was sent.", file=sys.stderr)
        return 1
    print("Render deploy hook format looks correct; no request was sent. Authenticity was not verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
