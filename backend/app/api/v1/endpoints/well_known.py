"""Well-known files served from the SHORT-LINK host so iOS / Android
can claim our universal-link / app-link paths and route them into the
installed app instead of rendering the browser fallback (/r/, /g/, /sub,
/plans, /subscription).

These are NOT versioned API endpoints — they're served at the top-level
`/.well-known/` namespace (NOT under /api/v1/), so they're mounted on
the main FastAPI app in app/main.py rather than the v1 router. The
content is generated from settings (IOS_BUNDLE_ID, IOS_TEAM_ID,
ANDROID_PACKAGE_NAME, ANDROID_SHA256_CERT_FINGERPRINTS) so rotating
keys or onboarding a second app variant doesn't need code.

Public, unauthenticated, infinitely cacheable in principle but we ship
short cache headers (15 min) so a typo'd rollout is fast to fix.
"""

from fastapi import APIRouter, Response

from app.core.config import settings
from app.web.short_links import UNIVERSAL_LINK_PATHS

router = APIRouter()

# Paths the app claims, derived from the short-link registry (the single
# source of truth — flip `aasa_claimed` there, or edit CLAIMED_APP_PATHS,
# never hand-edit here). Must stay in sync with the mobile-side
# `associatedDomains` / Android `intent-filter` data tags; tests assert
# that. Sponsorship checkout (/s/) and Circle invites (/c/) are
# deliberately NOT claimed — see short_links.py for the IAP/Circle-web-only
# rationale. /plans and /subscription are claimed too, even though they
# aren't short links — they're the app's Stripe checkout-return URLs (on
# SHORT_DOMAIN), so a return MAY hand back to the app; the confirming
# step's foreground re-check is the reliable path.
_UNIVERSAL_LINK_PATHS = UNIVERSAL_LINK_PATHS

# 15-minute cache: long enough to absorb load on a viral SMS share,
# short enough that a fix to a wrong fingerprint reaches devices fast.
_CACHE_HEADERS = {"Cache-Control": "public, max-age=900"}


@router.get("/apple-app-site-association")
async def apple_app_site_association() -> Response:
    """iOS Universal Links manifest.

    Apple fetches this at app install / link tap, with the Content-Type
    EXACTLY `application/json` — `application/pkcs7-mime` is for the
    signed legacy variant which we don't use (signed is required only
    when serving from a non-HTTPS origin, which we never do).
    """
    if not settings.IOS_TEAM_ID or not settings.IOS_BUNDLE_ID:
        # Returning 404 (not 500) tells iOS "no AASA at this host"
        # cleanly; the app side just falls back to scheme-only deep
        # links during local dev when these aren't set.
        return Response(status_code=404)

    app_id = f"{settings.IOS_TEAM_ID}.{settings.IOS_BUNDLE_ID}"
    payload = {
        "applinks": {
            "apps": [],
            "details": [
                {
                    "appID": app_id,
                    "paths": _UNIVERSAL_LINK_PATHS,
                }
            ],
        }
    }
    return Response(
        content=__import__("json").dumps(payload),
        media_type="application/json",
        headers=_CACHE_HEADERS,
    )


@router.get("/assetlinks.json")
async def assetlinks_json() -> Response:
    """Android App Links manifest.

    Lists one statement per signing certificate; verified via
    `https://digitalassetlinks.googleapis.com` at install time. Multiple
    fingerprints are required if the same package is signed by
    different keys in different distribution channels (EAS internal,
    EAS production, Play App Signing).
    """
    if (
        not settings.ANDROID_PACKAGE_NAME
        or not settings.ANDROID_SHA256_CERT_FINGERPRINTS
    ):
        return Response(status_code=404)

    fingerprints = [
        fp.strip()
        for fp in settings.ANDROID_SHA256_CERT_FINGERPRINTS.split(",")
        if fp.strip()
    ]
    statements = [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": settings.ANDROID_PACKAGE_NAME,
                "sha256_cert_fingerprints": fingerprints,
            },
        }
    ]
    return Response(
        content=__import__("json").dumps(statements),
        media_type="application/json",
        headers=_CACHE_HEADERS,
    )
