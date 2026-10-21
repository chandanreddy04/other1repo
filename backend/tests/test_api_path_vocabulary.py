"""Pins the /api/v1 path vocabulary after the resource rename (owner decision
2026-09-23: Circle / groups / sessions are the shared nouns — see
.claude/rules/backend-conventions.md REST API Conventions).

Two static checks over app.routes:
  1. None of the old hyphenated/verb-shaped legacy segments
     (circle-of-trust, group-plans, location-history, regenerate-invite,
     /join/, /leave) may reappear in a live /api/v1 path.
  2. Every literal (non-parameter) path segment under /api/v1 must be in
     ALLOWED_PATH_SEGMENTS — a new route that introduces an undocumented
     noun fails until it's added here deliberately, keeping future routes
     on-vocabulary instead of drifting back toward ad hoc naming.

Related: tests/test_rest_conventions.py (verb/suffix linting, not vocabulary),
tests/test_mobile_api_contract.py (mobile/backend path parity).
"""

from app.main import app

API_PREFIX = "/api/v1"

# Hyphenated/verb-shaped segments from the pre-rename API. None of these may
# appear in a live /api/v1 path again (owner decision 2026-09-23).
_LEGACY_SEGMENTS: list[str] = [
    "circle-of-trust",
    "group-plans",
    "location-history",
    "regenerate-invite",
    "/join/",
    "/leave",
]

# Every literal (non-parameter) path segment allowed under /api/v1, as of
# the 2026-09-23 rename. Adding a new literal segment to a route requires
# adding it here too — a deliberate, on-vocabulary decision, not an accident.
ALLOWED_PATH_SEGMENTS: set[str] = {
    # auth
    "auth",
    "request-otp",
    "verify-otp",
    "resend-otp",
    "refresh",
    # users
    "users",
    "me",
    "profile-photo",
    "restore",
    # circle
    "circle",
    "members",
    "settings",
    # sessions
    "sessions",
    "active",
    "outfit-photos",
    "complete",
    "extend",
    "locations",
    "retention",
    # subscriptions
    "subscriptions",
    "checkout",
    "day-pass",
    "portal",
    # referrals
    "referrals",
    # sponsorship-requests
    "sponsorship-requests",
    # groups
    "groups",
    "invite-code",
    # config
    "config",
    # framework
    "openapi.json",
}


def _api_v1_routes() -> list[tuple[str, str]]:
    """(method, path) pairs for every /api/v1 route."""
    routes = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if not methods or not path.startswith(API_PREFIX):
            continue
        for method in methods:
            if method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                routes.append((method, path))
    return routes


def test_no_legacy_hyphenated_nouns():
    """None of the pre-rename legacy path segments may reappear."""
    routes = _api_v1_routes()
    assert routes, "no /api/v1 routes found — route discovery regression?"

    violations = []
    for method, path in routes:
        for legacy in _LEGACY_SEGMENTS:
            if legacy in path:
                violations.append(
                    f"  {method} {path} — contains legacy segment {legacy!r}"
                )

    assert not violations, (
        "Legacy pre-rename API vocabulary found in /api/v1 routes (owner "
        "decision 2026-09-23 — see .claude/rules/backend-conventions.md):\n"
        + "\n".join(violations)
    )


def test_only_allowed_resource_nouns():
    """Every literal /api/v1 path segment must be a recorded vocabulary word."""
    routes = _api_v1_routes()
    paths = {path for _, path in routes}

    violations = []
    for path in paths:
        stripped = path[len(API_PREFIX) :]
        segments = [s for s in stripped.split("/") if s]
        for segment in segments:
            if segment.startswith("{") and segment.endswith("}"):
                continue
            if segment not in ALLOWED_PATH_SEGMENTS:
                violations.append(
                    f"  {path} — segment {segment!r} not in ALLOWED_PATH_SEGMENTS"
                )

    assert not violations, (
        "A /api/v1 route introduces a resource-noun segment that isn't in "
        "ALLOWED_PATH_SEGMENTS. Add it there deliberately if it's "
        "on-vocabulary, or rename the route:\n" + "\n".join(violations)
    )
