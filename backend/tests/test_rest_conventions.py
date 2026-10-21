"""Lint test that enforces REST naming conventions on API routes.

URLs should be nouns (resources), not verbs (actions).  HTTP methods convey the
action.  This test scans every route registered on the FastAPI app and flags
paths that contain known verb patterns.

Accepted exceptions are listed in ALLOWED_ACTION_ROUTES with a reason.
"""

import re

from app.main import app

# Verb-like path segments that violate REST conventions.
_VERB_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"/upload[-_]"),
    re.compile(r"/request[-_]"),
    re.compile(r"/verify[-_]"),
    re.compile(r"/resend[-_]"),
    re.compile(r"/send[-_]"),
    re.compile(r"/get[-_]"),
    re.compile(r"/fetch[-_]"),
    re.compile(r"/create[-_]"),
    re.compile(r"/delete[-_]"),
    re.compile(r"/update[-_]"),
    re.compile(r"/apply\b"),
    re.compile(r"/lookup\b"),
    re.compile(r"/search\b"),
    re.compile(r"/import[-_]"),
    re.compile(r"/export[-_]"),
    re.compile(r"/grant[-_]"),
    re.compile(r"/check[-_]"),
]

# Suffix patterns: path ending with a descriptive noun that duplicates what
# GET already means (e.g. /info, /status).
_SUFFIX_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"/info$"),
    re.compile(r"/status$"),
    re.compile(r"/list$"),
    re.compile(r"/details$"),
]

# --------------------------------------------------------------------------- #
# Allowed exceptions — each entry maps a (method, path) to a reason string.
# Add new exceptions here when a non-RESTful route is intentionally needed.
# --------------------------------------------------------------------------- #
ALLOWED_ACTION_ROUTES: dict[tuple[str, str], str] = {
    # Auth is conventionally RPC-style (OAuth, OpenID Connect patterns)
    ("POST", "/api/v1/auth/request-otp"): "Auth endpoints follow RPC convention",
    ("POST", "/api/v1/auth/verify-otp"): "Auth endpoints follow RPC convention",
    ("POST", "/api/v1/auth/resend-otp"): "Auth endpoints follow RPC convention",
    # HTMX web routes — server-rendered forms use RPC-style endpoints
    (
        "POST",
        "/htmx/auth/request-otp",
    ): "HTMX web routes follow RPC convention for form actions",
    (
        "POST",
        "/htmx/auth/verify-otp",
    ): "HTMX web routes follow RPC convention for form actions",
    (
        "POST",
        "/htmx/referrals/request-otp",
    ): "HTMX web routes follow RPC convention for form actions",
    (
        "POST",
        "/htmx/referrals/verify-otp",
    ): "HTMX web routes follow RPC convention for form actions",
    (
        "POST",
        "/htmx/sponsorships/{share_code}/request-otp",
    ): "HTMX web routes follow RPC convention for form actions",
    (
        "POST",
        "/htmx/sponsorships/{share_code}/verify-otp",
    ): "HTMX web routes follow RPC convention for form actions",
    # Public phone-keyed sponsorship-management flow (magic link → Stripe portal)
    (
        "POST",
        "/sponsorships/sign-in-links",
    ): "Sponsorship-mgmt flow stage 2 (send magic-link SMS); see account-deletion-plan.md",
}


def _get_all_routes() -> list[tuple[str, str]]:
    """Return (method, path) pairs for all routes in the app."""
    routes = []
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                if method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    routes.append((method, route.path))
    return routes


def _strip_path_params(path: str) -> str:
    """Remove path parameter segments for pattern matching."""
    return re.sub(r"/\{[^}]+\}", "", path)


class TestRESTConventions:
    def test_no_verb_urls(self):
        """API routes should not contain verb patterns in their paths."""
        violations = []
        for method, path in _get_all_routes():
            if (method, path) in ALLOWED_ACTION_ROUTES:
                continue
            stripped = _strip_path_params(path)
            for pattern in _VERB_PATTERNS:
                if pattern.search(stripped):
                    violations.append(
                        f"  {method} {path} — matches verb pattern {pattern.pattern}"
                    )
                    break

        assert not violations, (
            "Routes with verb-like URL segments found. "
            "Either rename to a noun-based path or add to ALLOWED_ACTION_ROUTES "
            "with a justification:\n" + "\n".join(violations)
        )

    def test_no_redundant_suffixes(self):
        """GET routes should not have redundant suffixes like /info or /status."""
        violations = []
        for method, path in _get_all_routes():
            if method != "GET":
                continue
            if (method, path) in ALLOWED_ACTION_ROUTES:
                continue
            stripped = _strip_path_params(path)
            for pattern in _SUFFIX_PATTERNS:
                if pattern.search(stripped):
                    violations.append(
                        f"  {method} {path} — redundant suffix {pattern.pattern}"
                    )
                    break

        assert not violations, (
            "GET routes with redundant suffixes found. "
            "The HTTP method already implies retrieval — use the collection root "
            "instead:\n" + "\n".join(violations)
        )

    def test_allowed_exceptions_are_still_registered(self):
        """Ensure allowed exceptions haven't been removed (stale entries)."""
        registered = set(_get_all_routes())
        stale = []
        for method_path, reason in ALLOWED_ACTION_ROUTES.items():
            if method_path not in registered:
                stale.append(f"  {method_path[0]} {method_path[1]} — {reason}")
        assert not stale, (
            "ALLOWED_ACTION_ROUTES contains entries for routes that no longer exist. "
            "Remove them:\n" + "\n".join(stale)
        )
