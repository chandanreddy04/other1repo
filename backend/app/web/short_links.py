"""Single source of truth for the short-link slugs served on the
short-link domain (madeitho.me / s.madeitho.me), plus the app-claimed
Stripe-return paths that ride alongside them in the universal-link
manifest.

Scope: the ``/{slug}/{code}`` links (coded) and the codeless ``/sub``
conversion link (fixed target, no code — the frozen lapse-SMS URL, see
``app/services/sub_lapse_notifications.py``). The bare ``/sponsorships``
management route is a different shape again (fixed target, no code, but
NOT in this registry — it collides on a shared path prefix with the ``s``
slug's coded ``/sponsorships/{code}`` checkout lander, so it stays a plain
route in routes_web_sponsorships.py; see the include_router ordering note
in main.py).

Each :class:`ShortLink` maps a slug — one letter for a coded link, kept
minimal because a code is appended and these ride in SMS / QR; the full
path segment for a codeless link — to its browser-fallback lander and
whether the OS should claim it as a universal link / app link.

Policy (owner decision 2026-09-23): a claimed link opens an in-app
screen — join a group, redeem a referral, the paywall, a Stripe return —
**never** a Stripe checkout page. Claiming a checkout link would route
payment into the app and trip Apple App Store Guideline 3.1.1 / Google
Play Billing, so sponsorship checkout stays browser-only (``s``). Circle
invites (``c``) are browser-only for a different reason: Circle members
use mobile web only, so there's no in-app accept screen to claim the link
into. See ``app/api/v1/endpoints/well_known.py``.

``CLAIMED_APP_PATHS`` are NOT short links — they're the app's own Stripe
checkout-return URLs (``success_url``/``return_url`` in
``app/services/stripe_service.py``, built on SHORT_DOMAIN — the host the
app claims). They ride in the same universal-link manifest as the claimed
short-link slugs so a Stripe return MAY hand back to the app (the OS often
won't for a script-driven redirect); the app's confirming step and its
foreground re-check are the reliable unlock path either way. ``/plans``
and ``/subscription`` each also get a plain `GET` route in
``routes_web.py`` (``plans_web_fallback`` / ``subscription_web_fallback``)
as the browser fallback (uninstalled app / desktop).

``NESTED_SHORT_LINKS`` is a second, smaller registry for a short link
nested one level under an existing coded parent slug — today just
``/s/p/{token}`` (the sponsorship magic-link sign-in short link: ``s`` for
sponsorships, ``p`` for portal). It exists because ``p`` is already the
first-letter match for "portal" but a plain top-level ``ShortLink("p", ...)``
would collide with nothing today yet reads as an unrelated, ungrouped
single-letter slug; nesting it under ``s`` keeps it visually and
semantically scoped to the sponsorship flow it belongs to. Unlike a
top-level coded slug, the appended value is NOT upper-cased on redirect —
it's an opaque, case-sensitive one-time token (a share/referral code is
human-typed and case-insensitive; a sign-in token is neither). Never
AASA-claimed (same Stripe-checkout-adjacent reasoning as ``s`` itself —
the portal opens a real Stripe billing session). ``/s/p/{token}`` can't
collide with the parent's ``/s/{code}`` whatever the code is (a share code
"P" included): the nested route has one more path segment.

Consumers — keep all of these derived from this registry, never hand-edited:
- ``app/web/routes_web.py`` registers a redirect for each entry (301 for a
  coded ``/{slug}/{code}``, 302 for the codeless ``/sub``) and the
  ``/plans`` / ``/subscription`` browser fallbacks.
- ``app/api/v1/endpoints/well_known.py`` builds the AASA / assetlinks
  path list from the claimed entries (``UNIVERSAL_LINK_PATHS``).
- ``mobile/app.config.js`` (iOS ``associatedDomains`` + Android
  ``intentFilters``) must claim exactly the same paths;
  ``tests/test_short_link_routes.py`` asserts the mobile config matches.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ShortLink:
    """One short-link slug and where it points.

    ``slug`` is a single letter for a coded link (e.g. "r", appended with
    a code: ``/r/{code}``) or the full path segment for a codeless link
    (e.g. "sub" → ``/sub``, no code — ``has_code=False``).
    """

    slug: str
    lander: str  # browser-fallback path, e.g. "/referrals" (code appended, upper-cased)
    aasa_claimed: bool  # whether iOS/Android claim it as a universal/app link
    purpose: str
    has_code: bool = True


SHORT_LINKS: tuple[ShortLink, ...] = (
    ShortLink("r", "/referrals", aasa_claimed=True, purpose="Referral share link"),
    ShortLink("g", "/groups", aasa_claimed=True, purpose="Group-plan join invite"),
    # Circle invites are browser-only (owner decision 2026-09-23): Circle
    # members use mobile web only, so there's no in-app accept screen to
    # route into — unlike sponsorship checkout, this isn't about IAP, just
    # that the app has nothing to open the link into.
    ShortLink("c", "/circles", aasa_claimed=False, purpose="Circle-of-trust invite"),
    # Sponsorship checkout is a Stripe checkout — browser-only so it
    # doesn't trip IAP rules.
    ShortLink("s", "/sponsorships", aasa_claimed=False, purpose="Sponsorship checkout"),
    # Public alert-details page for circle members — browser-only so an
    # SMS-only contact with no app and no account can see the details and
    # acknowledge it. The alert UUID in the URL is the access token;
    # Python's UUID parsing accepts the redirect's upper-casing.
    ShortLink("a", "/alerts", aasa_claimed=False, purpose="Alert details for contacts"),
    # Codeless: the frozen lapse-SMS link (`sub_lapse_notifications.py`,
    # NOT touched by this commit). Claimed — the app now opens its own
    # paywall for it instead of the old marketing-site bounce. This is the
    # documented exception to the first-letter rule (test_short_link_
    # first_letter.py): the slug IS the full frozen path segment, not a
    # one-letter code prefix.
    ShortLink(
        "sub",
        "/plans",
        aasa_claimed=True,
        purpose="Lapse-SMS link (paywall)",
        has_code=False,
    ),
)

@dataclass(frozen=True)
class NestedShortLink:
    """A short link nested one level under an existing coded ``SHORT_LINKS``
    parent slug: ``/{parent_slug}/{slug}/{value}`` -> ``{lander}/{value}``.

    ``slug`` still follows the first-letter rule against ``lander``'s own
    resource segment (test_sponsorship_short_link.py expresses this for
    "p" <-> "portal", the way test_short_link_first_letter.py does for the
    top-level registry) — nesting doesn't exempt it, it just avoids
    claiming a second top-level single letter for a sub-flow of an
    existing one. The appended value is never upper-cased (see module
    docstring) and the redirect is 302 (temporary): unlike a share/referral
    code, a sign-in token is consumed by the lander on first use, so
    caching the redirect target would be actively wrong on a repeat visit.
    """

    parent_slug: str
    slug: str
    lander: str
    aasa_claimed: bool = False


NESTED_SHORT_LINKS: tuple[NestedShortLink, ...] = (
    # Sponsorship magic-link sign-in: /s/p/{token} -> /sponsorships/portal/{token}.
    # `token` is a one-time opaque value from
    # app/models/sponsorship_sign_in_token.py, never a human-typed code.
    NestedShortLink(parent_slug="s", slug="p", lander="/sponsorships/portal"),
)

# The app's own Stripe checkout-return URLs (success_url/return_url in
# stripe_service.py, on SHORT_DOMAIN) — NOT short links, but claimed the
# same way so a return MAY hand back to the app; the confirming step's
# foreground re-check is the reliable path. Kept as a plain tuple (not a
# ShortLink) because there's no slug/code shape here, just an exact path
# each platform must claim.
CLAIMED_APP_PATHS: tuple[str, ...] = ("/plans", "/subscription")

# Path patterns the app claims via AASA / assetlinks. DERIVED — never
# hand-edit; flip ``aasa_claimed`` above (or edit CLAIMED_APP_PATHS)
# instead. A coded claimed entry claims the whole ``/{slug}/*`` subtree;
# a codeless one claims its exact path.
UNIVERSAL_LINK_PATHS: list[str] = [
    (f"/{sl.slug}/*" if sl.has_code else f"/{sl.slug}")
    for sl in SHORT_LINKS
    if sl.aasa_claimed
] + list(CLAIMED_APP_PATHS)
