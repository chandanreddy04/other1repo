"""Every route API_REFERENCE.md documents is actually served.

API_REFERENCE.md is an inventory doc: each endpoint block starts with a
`METHOD /path` line (relative to the `/api/v1` base URL, except the delivery
webhooks, which are served at the site root under `/webhooks/`). A route that
was renamed or removed without the doc following would send a reader to a
404, so each documented line must resolve to a live `(method, path)` in
`app.main.app` — path parameters compared by position, not name.

Only lines that START with the method are checked (the endpoint blocks);
inline prose mentions like "`POST /users/me/restore`" are not.

Related: API_REFERENCE.md, tests/test_mobile_api_contract.py (the same idea
for mobile/services/api.ts), tests/test_notification_inventory_complete.py.
"""

import re
from pathlib import Path

from fastapi.routing import APIRoute

from app.main import app

_DOC = Path(__file__).resolve().parents[2] / "API_REFERENCE.md"
_API_PREFIX = "/api/v1"

_ENDPOINT_LINE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) (/\S*)", re.MULTILINE)
_PARAM = re.compile(r"{[^}]+}")


def _normalize(path: str) -> str:
    return _PARAM.sub("{}", path.split("?", 1)[0].rstrip("/") or "/")


def _documented() -> list[tuple[str, str]]:
    out = []
    for method, path in _ENDPOINT_LINE.findall(_DOC.read_text(encoding="utf-8")):
        full = path if path.startswith("/webhooks/") else _API_PREFIX + path
        out.append((method, _normalize(full)))
    return out


def _served() -> set[tuple[str, str]]:
    return {
        (method, _normalize(route.path))
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def test_api_reference_documents_endpoints():
    assert len(_documented()) >= 25, "parsed suspiciously few endpoint lines"


def test_every_documented_route_exists():
    served = _served()
    missing = [f"{m} {p}" for m, p in _documented() if (m, p) not in served]
    assert not missing, (
        "API_REFERENCE.md documents routes the app does not serve — update the "
        "doc (or restore the route):\n" + "\n".join(missing)
    )
