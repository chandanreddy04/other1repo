"""Every admin sidebar link must point at a real, registered route.

The admin nav in `admin/base_admin.html` is hardcoded, not derived from the
view registry (`.claude/rules/admin.md`), so a removed or renamed view can
leave a dead `<a href="/admin/...">` behind with nothing to catch it. This
parses the `/admin/...` hrefs inside the sidebar `<nav class="admin-sidebar">`
only (not the rest of the template), drops any `?query` / `#fragment`, and
checks each path resolves against `app.routes` (FastAPI path templates like
`/admin/sessions/{item_id}` are turned into a regex so a concrete href like
`/admin/sessions/new` — or any other literal segment — can match).

Caught the dead `/admin/sponsors` link removed 2026-09-23 (no view was ever
registered for it — see admin_registry.ALL_VIEWS).

Related: app/web/templates/admin/base_admin.html, app/web/admin_registry.py
"""

import re
from pathlib import Path

from app.main import app

_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "web"
    / "templates"
    / "admin"
    / "base_admin.html"
)

_NAV_RE = re.compile(r'<nav class="admin-sidebar">(.*?)</nav>', re.DOTALL)
_HREF_RE = re.compile(r'href="(/admin/[^"]*)"')


def _sidebar_hrefs() -> list[str]:
    text = _TEMPLATE.read_text(encoding="utf-8")
    nav = _NAV_RE.search(text)
    assert nav, 'no <nav class="admin-sidebar"> found — template parsing regressed'
    hrefs = []
    for href in _HREF_RE.findall(nav.group(1)):
        # Strip any Jinja template expression that leaked into the
        # attribute value (none currently, but don't silently pass one).
        assert "{{" not in href and "{%" not in href, (
            f"href contains unresolved Jinja syntax: {href!r}"
        )
        # A query string or fragment doesn't change which route serves it.
        hrefs.append(re.split(r"[?#]", href, maxsplit=1)[0])
    return hrefs


def _registered_get_paths() -> list[str]:
    paths = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if path and methods and "GET" in methods:
            paths.append(path)
    return paths


def _path_to_regex(path: str) -> re.Pattern[str]:
    """Turn a FastAPI path template into a matching regex, replacing each
    `{param}` segment with a single-path-segment wildcard."""
    escaped_segments = []
    for segment in path.split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            escaped_segments.append("[^/]+")
        else:
            escaped_segments.append(re.escape(segment))
    pattern = "^" + "/".join(escaped_segments) + "$"
    return re.compile(pattern)


def test_sidebar_links_resolve_to_registered_routes():
    hrefs = _sidebar_hrefs()
    assert hrefs, "no /admin hrefs found — template parsing regressed"

    registered = _registered_get_paths()
    regexes = [_path_to_regex(p) for p in registered]

    unresolved = []
    for href in hrefs:
        if not any(rx.match(href) for rx in regexes):
            unresolved.append(href)

    assert not unresolved, (
        "Sidebar links in admin/base_admin.html don't resolve to any "
        "registered GET route (dead link — remove it or register the "
        f"view): {unresolved}"
    )
