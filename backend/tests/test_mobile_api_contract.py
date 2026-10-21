"""Mobile → backend HTTP route contract.

Retro guard (2026-07-02): this session found the mobile API layer calling
routes that did not exist — session creation sent legacy fields and 422'd
on every attempt, and extend used POST against a PUT endpoint (405) — both
silently shipped because nothing checked the two sides against each other.
(The push-type contract has its own guard in
test_notification_types_contract.py.)

This test parses every `this.request('<path>', {method: ...})` call in
mobile/services/api.ts and asserts a FastAPI route with that METHOD and
path shape exists. It cannot validate payload fields, but it catches the
method/path half of the drift class mechanically.

Adding a mobile API call? The backend route must exist first (or in the
same change) — that's the point.
"""

import re
from pathlib import Path

from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
MOBILE_API = REPO_ROOT / "mobile" / "services" / "api.ts"

API_PREFIX = "/api/v1"

# this.request('/path'...) or this.request(`/path/${id}`...), optionally
# followed (same call, non-greedy across lines) by a method: 'VERB'. Also
# this.doFetch(...) — the multipart uploads and the token refresh call fetch
# directly, and a renamed upload path went unchecked before (2026-09-23).
_CALL_PATTERN = re.compile(
    r"this\.(?:request|doFetch)(?:<[^>]*>)?\(\s*(['`])(/[^'`]*)\1"
    r"(?:\s*,\s*\{[^)]*?method:\s*'(GET|POST|PUT|PATCH|DELETE)')?",
    re.DOTALL,
)


def _mobile_calls() -> list[tuple[str, str]]:
    """(METHOD, normalized-path) for every this.request/doFetch call in api.ts."""
    source = MOBILE_API.read_text()
    calls = []
    for _, raw_path, method in _CALL_PATTERN.findall(source):
        path = raw_path.split("?")[0]  # query strings aren't part of the route
        # Template params `${expr}` → wildcard segment marker.
        path = re.sub(r"\$\{[^}]*\}", "{param}", path)
        calls.append((method or "GET", path))
    return calls


def _backend_routes() -> list[tuple[set[str], list[str]]]:
    """(methods, path-segments) for every API route under /api/v1."""
    routes = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if not methods or not path.startswith(API_PREFIX):
            continue
        stripped = path[len(API_PREFIX) :] or "/"
        routes.append((set(methods), stripped.rstrip("/").split("/")))
    return routes


def _segments_match(mobile_segs: list[str], backend_segs: list[str]) -> bool:
    if len(mobile_segs) != len(backend_segs):
        return False
    for m, b in zip(mobile_segs, backend_segs, strict=True):
        b_is_param = b.startswith("{") and b.endswith("}")
        m_is_param = m == "{param}"
        if b_is_param or m_is_param:
            # A param segment matches anything non-empty on the other side.
            if not (m and b):
                return False
        elif m != b:
            return False
    return True


def test_every_mobile_api_call_has_a_backend_route():
    backend = _backend_routes()
    calls = _mobile_calls()
    assert calls, "parser found no this.request calls — pattern regression?"

    unmatched = []
    for method, path in calls:
        segs = path.rstrip("/").split("/")
        if not any(
            method in methods and _segments_match(segs, b_segs)
            for methods, b_segs in backend
        ):
            unmatched.append(f"{method} {path}")

    assert not unmatched, (
        "mobile/services/api.ts calls routes the backend does not serve "
        f"(method + path checked): {unmatched}. Either the backend route is "
        "missing/renamed or the mobile call uses the wrong method/path — "
        "this exact drift class shipped a 100%-broken create (422) and "
        "extend (405) before this guard existed."
    )
