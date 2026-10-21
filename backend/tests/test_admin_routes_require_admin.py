"""Every route mounted under /admin declares the admin dependency.

The per-entry admin data-management routes used to rely on one hand-written
`test_rejects_non_admins`; when the photo-delete route it was attached to was
removed (2026-09-05) the sibling routes were briefly left with no non-admin
check at all. This walks the FastAPI dependency tree of every /admin route so
a route that forgets `Depends(get_current_admin)` — hand-written or generated
by the admin registry — fails here, not in production.

Related: app/web/routes_admin.py, app/web/admin_views.py, app/web/deps.py.
"""

from fastapi.routing import APIRoute

from app.main import app
from app.web.deps import get_current_admin


def _depends_on_admin(dependant) -> bool:
    if dependant.call is get_current_admin:
        return True
    return any(_depends_on_admin(sub) for sub in dependant.dependencies)


def test_every_admin_route_requires_admin():
    admin_routes = [
        r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/admin")
    ]
    assert len(admin_routes) > 5, "expected the admin routes to be mounted on the app"
    unguarded = sorted(
        f"{','.join(sorted(r.methods))} {r.path}"
        for r in admin_routes
        if not _depends_on_admin(r.dependant)
    )
    assert not unguarded, (
        f"/admin routes without Depends(get_current_admin): {unguarded}"
    )
