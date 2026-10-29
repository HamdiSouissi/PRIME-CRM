"""Diagnose Netlify publishing fields with read-only requests and fixed output.

This helper only reports categories, never API bodies, tokens, IDs, URLs, or
exception details. It does not change settings, create deploys, or publish.
"""

from __future__ import annotations

import os
import sys

from tools.netlify_preflight import (
    SITE_ID,
    SITE_NAME,
    get_site,
    make_opener,
    validate_token,
)
from tools.netlify_release import _DEPLOY_ID, ReleaseOutcomeUnknown, get_deploy

_REPOSITORY = "HamdiSouissi/PRIME-CRM"
_REF = "refs/heads/arena/a18b007f-prime-crm"


class DiagnosticError(ValueError):
    """The sanitized diagnostic context is invalid."""


def validate_context(environment: dict[str, str]) -> None:
    if (
        environment.get("GITHUB_ACTIONS") != "true"
        or environment.get("GITHUB_EVENT_NAME") != "push"
        or environment.get("GITHUB_REPOSITORY") != _REPOSITORY
        or environment.get("GITHUB_REF") != _REF
        or environment.get("NETLIFY_LOCK_DIAGNOSTIC_APPROVED") != "true"
    ):
        raise DiagnosticError("The protected diagnostic context is missing")


def boolean_state(mapping: object, key: str) -> str:
    """Return only fixed labels, without converting or echoing provider values."""
    if not isinstance(mapping, dict):
        return "unavailable"
    if key not in mapping:
        return "absent"
    value = mapping[key]
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "null" if value is None else "invalid"


def published_state(site: dict) -> tuple[str, str, str | None]:
    """Classify the embedded deploy; the actual ID is never included in output."""
    if "published_deploy" not in site:
        return "absent", "unavailable", None
    published = site["published_deploy"]
    if published is None:
        return "null", "unavailable", None
    if not isinstance(published, dict):
        return "invalid", "unavailable", None
    deploy_id = published.get("id")
    if "id" not in published:
        return "object", "absent", None
    if not isinstance(deploy_id, str) or not _DEPLOY_ID.fullmatch(deploy_id):
        return "object", "invalid", None
    return "object", "valid", deploy_id


def run_diagnostic(token: str, opener) -> dict[str, str]:
    """Fetch the fixed site and, if safe, its published deploy; GET only."""
    validate_token(token)
    site = get_site(token, opener)
    project_match = site.get("id") == SITE_ID and site.get("name") == SITE_NAME
    published_type, id_state, deploy_id = published_state(site)
    report = {
        "PROJECT_MATCH": "yes" if project_match else "no",
        "STOPPED_BUILDS": boolean_state(site.get("build_settings"), "stop_builds"),
        "PREVENT_NON_GIT_PROD_DEPLOYS": boolean_state(site, "prevent_non_git_prod_deploys"),
        "PUBLISHED_DEPLOY": published_type,
        "PUBLISHED_DEPLOY_ID": id_state,
        "PUBLISHED_DEPLOY_LOCKED": boolean_state(site.get("published_deploy"), "locked"),
        "DEPLOY_DETAIL": "not_checked",
        "DEPLOY_DETAIL_LOCKED": "unavailable",
    }
    if project_match and deploy_id is not None:
        try:
            detail = get_deploy(token, deploy_id, opener)
        except ReleaseOutcomeUnknown:
            report["DEPLOY_DETAIL"] = "unavailable"
        else:
            report["DEPLOY_DETAIL"] = "available"
            report["DEPLOY_DETAIL_LOCKED"] = boolean_state(detail, "locked")
    return report


def main() -> int:
    try:
        validate_context(os.environ)
        token = os.environ.get("NETLIFY_AUTH_TOKEN", "")
        validate_token(token)
        report = run_diagnostic(token, make_opener())
    except Exception:  # noqa: BLE001 - errors and responses can contain secrets
        print("::error::Netlify read-only diagnostic failed; no deployment or configuration change was requested.", file=sys.stderr)
        return 1
    print("Netlify read-only diagnostic: fixed categories only")
    for key, value in report.items():
        print(f"{key}={value}")
    print("NO_DEPLOYMENT_OR_SETTINGS_CHANGE=yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
