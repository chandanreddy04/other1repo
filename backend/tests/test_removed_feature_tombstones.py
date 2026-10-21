"""Removed features stay removed.

When a feature is deleted end to end, its identifiers go in REMOVED below
(dated, with the owner decision). This scans the live backend and mobile
source for any of them so the feature can't quietly grow back through a
stray import, a copied snippet or a half-reverted merge — and so a removal
sweep that missed a reference fails CI instead of shipping dead code.

Deliberately NOT scanned: alembic history (the migrations that created and
dropped the feature legitimately name it), docs/ and .claude/rules/ (which
record the removal), and the tests that pin the removal contract.

Related: CLAUDE.md "Removing a feature", tests/test_photo_discovery_removed.py.
"""

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

# {label: identifiers}. Label = date + feature, for the failure message.
REMOVED: dict[str, list[str]] = {
    "2026-09-05 background photo discovery (owner decision)": [
        "photoDiscovery",
        "photo_sharing_enabled",
        "photoSharing",
        "session_photos",
        "SessionPhoto",
        "expo-media-library",
        "requestPhotosAccessLevel",
        "photosState",
        "capture_photos",
        "delete_session_photo_data",
    ],
    "2026-09-22 Circle members SMS-only; every push receipt-tracked (owner decision)": [
        # iOS interruption level — only ever set on circle-member pushes.
        "interruption_level",
        "interruptionLevel",
        # The accepted-means-delivered branch for untracked pushes.
        "test_accepted_nonreceipt_kind_is_delivered",
        "Low-stakes push",
        # The alert-tap deep-link to /alert-details for circle-member pushes.
        "alert-details?alertId",
    ],
    "2026-09-22 native Circle-member surface (owner decision)": [
        # Deliberately NOT listed:
        # - alert-details (the deleted mobile/app/alert-details.tsx): the
        #   name stays legitimate for the public web "alert-details page"
        #   (backend/app/web/short_links.py, alert_view.html).
        # - CircleMemberCard: the name was reused (2026-09-23) by renaming
        #   CircleOfTrustCard (the owner's own circle list), so a tombstone
        #   would forbid it.
        "useAlertsStore",
        "useCircleMembershipsStore",
        "AlertLogCard",
        "CircleInvitationCard",
        "acceptCircleByInviteCode",
        "getCircleInvitations",
        "acceptCircleInvitation",
        "declineCircleInvitation",
        "getCircleMemberships",
        "leaveCircle",
        "getUnacknowledgedAlerts",
        "acknowledgeAlert",
        "loadCircleInvitations",
    ],
    "2026-09-22 Circle-member API endpoints (owner decision)": [
        # GET/PUT /api/v1/alerts and the circle-of-trust memberships /
        # invitations endpoints, plus their helpers. The public alert page's
        # /alerts/{id}/acknowledge is deliberately NOT listed (still live) —
        # the web dashboard's own /htmx/alerts/{id}/acknowledge was a
        # separate route, removed 2026-09-23 below.
        "/alerts/unacknowledged",
        "/memberships",
        "accept-by-code",
        "_serialize_with_snapshot",
        "_accept_and_build_response",
        "_resolve_inviter_pending",
    ],
    "2026-09-23 web alerts inline detail (owner decision)": [
        # GET /alerts became a LIST ONLY page (row -> GET /alerts/{id}, the
        # one place details render). Removed: the poll-driven toast
        # fragment, the poll route it fetched, and the inline "Mark as
        # Read" acknowledge button/route (acknowledgement now only happens
        # on the public alert page, POST /alerts/{id}/acknowledge).
        "alert_notification",
        "/htmx/alerts/check",
        "Mark as Read",
    ],
    "2026-09-23 web invitations page + htmx circle handlers (owner decision)": [
        # GET /invitations + GET/POST /circle/{code}[/accept] became the
        # REST-shaped GET /circles + GET/POST /circles/{code}[/accept|
        # decline|leave]. The three cookie-auth htmx handlers they used to
        # share the page with (accept/decline an invitation, leave a
        # circle) were folded into those POSTs — no htmx routes for Circle
        # members (one implementation per action).
        "invitations.html",
        "/htmx/invitation/",
        "/htmx/circle/",
        # The old lander template/handlers (circle_join.html,
        # circle_join_page/_accept, _circle_join_context) and the orphaned
        # dashboard_obfuscated.html / invitation_htmx.html templates.
        "circle_join",
        "dashboard_obfuscated",
        "invitation_htmx",
    ],
    "2026-09-23 web dashboard + profile page (owner decision)": [
        # GET /dashboard (dashboard.html) duplicated /alerts + /circles and
        # was removed; GET /profile (profile.html) + POST /htmx/profile/
        # update became GET/POST /account (account.html) — "Account" is the
        # hub, "profile" is name/photo. Quoted so this doesn't false-positive
        # on the unrelated admin/dashboard.html template string.
        '"dashboard.html"',
        "/htmx/profile/",
        "profile.html",
        # The route literals, quoted for the same reason: '"/dashboard"'
        # never matches "/admin/dashboard", '"/profile"' never matches
        # "/web/profile" or "/users/me/profile-photo".
        '"/dashboard"',
        '"/profile"',
    ],
    "2026-09-23 gift pages (owner decision: sponsorship vocabulary)": [
        # GET/POST /gift[/checkout|/{share_code}[/checkout]], GET
        # /gift/success + /gift/cancel, and the phone-keyed
        # /sponsor[/request|/portal|/done] management flow all became the
        # REST-shaped /sponsorships[/new|/{share_code}[/checkout]] (states
        # on ONE template) and /sponsorships[/sign-in-links|/portal],
        # ?status=saved; the /g/{code} short link became /s/{code}.
        # Deliberately NOT listed: STRIPE_GIFT, gifted_by_phone_id,
        # SponsorshipRequest, create_gift_checkout_session, the gifter_phone
        # form field, resolve_pending_gifts, recordGiftRequest — model/CRUD/
        # service identifiers and mobile sponsor-request-flow names are
        # unchanged this commit. (The generic form's unused gifter_name
        # "Your Name" input WAS removed — the handler never read it.)
        #
        # "}/g/" (the old gift short-link builder form) is deliberately NOT
        # listed here any more (2026-09-23 short-link slugs owner decision,
        # below): the "g" slug is reassigned from the removed gift checkout
        # to the group-plan join link, so that exact substring is now
        # legitimate mobile source again. See the note there.
        "gift.html",
        "gift_personalized",
        "gift_success",
        "gift_cancel",
        "/htmx/gift/",
        '"/gift"',
        "/sponsor/done",
        "/sponsor/request",
        "/sponsor/portal",
        "routes_htmx_gift",
        "gift_auth_form",
        "gift_plan_form",
    ],
    "2026-09-23 web path vocabulary (owner decision)": [
        # GET /referral/{code} -> /referrals/{code}, GET /group/{invite_code}
        # -> /groups/{invite_code}, the /htmx/referral/* htmx auth routes ->
        # /htmx/referrals/*, and GET /admin/sessions/{id}/checkin-on-behalf
        # -> /admin/sessions/{id}/mark-safe (template renamed too). The
        # short-link slugs themselves (r, f) are unchanged — only their
        # browser-fallback landers moved.
        "/htmx/referral/",
        # Quoted so this doesn't false-positive on "/referral/{code}" prose
        # or similar substrings elsewhere; matches the old double-quoted
        # route-literal usage in Python/Jinja.
        '"/referral/',
        '"/group/',
        "checkin-on-behalf",
        "checkin_on_behalf.html",
        # The bare, slash-prefixed route: also covers the old quoted literal,
        # the /delete-account/* web sub-routes and the absolute
        # madeithomeapp.com/delete-account URL. Safe since the mobile in-app
        # deletion screen moved to `/account/delete` (2026-09-23 native
        # account routes, below).
        "/delete-account",
        # The old landers as written in prose/comments.
        "/referral/{",
        "/group/{",
        "check-in-on-behalf",
    ],
    "2026-09-23 native session routes (owner decision)": [
        # app/active-session.tsx, app/session-history.tsx,
        # app/create-session.tsx and app/session/[id].tsx became REST-shaped
        # app/sessions/[index|new|active|[id]].tsx — ONE page per resource
        # (app/sessions/[id].tsx renders live vs ended by server status via
        # utils/sessionMode.ts), sharing one folder navigator
        # (app/sessions/_layout.tsx). "/active-session" is slash-prefixed
        # (not the bare word) because the backend legitimately still says
        # "the mobile active-session screen" in prose comments describing
        # this same live-session concept (crud/alert.py, sessions.py,
        # schemas/session.py, notification_constants.py,
        # test_session_alert_acknowledged.py) — those aren't route literals
        # and backend/ is out of scope for this commit.
        "/active-session",
        "session-history",
        "create-session",
        "session/[id]",
    ],
    "2026-09-23 native account routes (owner decision)": [
        # Vocabulary rename (owner decision): "Account" is the hub tab
        # (name/photo, subscription, sessions, delete) and "Circle" is the
        # owner's set of trusted contacts (tab). `(tabs)/profile.tsx` ->
        # `(tabs)/account.tsx` (tab name="account", title "Account"),
        # `(tabs)/contacts.tsx` -> `(tabs)/circle.tsx` (tab name="circle",
        # title "Circle"). The old standalone in-app editor screen and the
        # auth-flow name-capture screen merged into ONE page,
        # `app/account/profile.tsx` (mode driven by `profileScreenMode()`
        # in utils/profileScreenMode.ts); the old account-deletion and
        # soft-delete-recovery screens moved to `app/account/delete.tsx`
        # and `app/account/restore.tsx` — all three sharing one folder
        # navigator (`app/account/_layout.tsx`), deliberately WITHOUT an
        # `app/account/index.tsx` (the (tabs)/account.tsx tab already owns
        # the bare /account URL — verified via `npx expo export` + the
        # generated route manifest, no collision).
        "edit-profile",
        "welcome-back",
        "complete-profile",
        "(tabs)/profile",
        "(tabs)/contacts",
    ],
    "2026-09-23 backend marketing pages (owner decision)": [
        # Marketing/pricing live only on the separate marketing-site repo
        # (www.madeithomeapp.com); this app backend serves neither. GET /
        # is now a 301 to settings.MARKETING_ORIGIN and GET /pricing is
        # gone. The nav_public/phone_home/success_redirect fragments and
        # pages were orphaned by the removal and deleted with it.
        "marketing.html",
        "pricing.html",
        "nav_public",
        "phone_home",
        "success_redirect",
        # Quoted so this doesn't false-positive on the many legitimate
        # backtick-quoted `/pricing` mentions in comments/docstrings that
        # explain the removal, or on unrelated "pricing" prose — matches
        # the old double-quoted route-literal usage in Python.
        '"/pricing"',
    ],
    "2026-09-23 native plan/subscription routes (owner decision)": [
        # app/paywall.tsx + app/subscribe.tsx + app/subscribed.tsx merged into
        # ONE app/plans.tsx (states: options/picker/confirming/canceled);
        # app/manage-subscription.tsx + app/group-plan.tsx merged into ONE
        # app/subscription.tsx (states by subscriptionState(status): none/
        # individual/group_owner/group_member/sponsored/day_pass).
        # app/redeem-code.tsx -> app/referrals/new.tsx, app/request-sponsor.tsx
        # -> app/sponsorship-requests/new.tsx, app/referral.tsx ->
        # app/referrals/index.tsx, app/f/[inviteCode].tsx's join screen ->
        # app/groups/[code].tsx (f/ and r/ keep their claimed universal-link
        # slugs as thin redirect shims for now).
        # `subscribe.tsx` and the quoted `'/subscribe'` route literal are
        # listed instead of the bare word (backend/app and mobile/app
        # legitimately still say "subscribe"/"subscription" in unrelated
        # prose and endpoint names); same reasoning for the other
        # extension-qualified/quoted identifiers below.
        "manage-subscription",
        "group-plan.tsx",
        "redeem-code",
        "request-sponsor",
        "subscribed.tsx",
        "paywall.tsx",
        "subscribe.tsx",
        "'/subscribe'",
    ],
    "2026-09-23 short-link slugs (owner decision)": [
        # The group-plan join slug moved from "f" to "g" (freeing "g" up
        # from its old, already-removed gift-checkout meaning — see the
        # note on the 2026-09-23 gift-pages entry above) and /sub stopped
        # bouncing to marketing: the app now claims it and opens the
        # paywall directly. Nothing shipped with the old "f" slug, so no
        # alias. "}/f/" is the mobile share-link builder form (the exact
        # string GroupState.tsx used to interpolate); ShortLink("f" and
        # '/f/' are the backend registry and app.config.js literals.
        "}/f/",
        'ShortLink("f"',
        "'/f/'",
        # The iOS Time Sensitive entitlement (com.apple.developer.
        # usernotifications.time-sensitive) is removed too — unused since
        # circle alerts went SMS-only (a81e84c) and no push is
        # Focus/DND-piercing any more.
        "time-sensitive",
    ],
    "2026-09-23 OSM raster tiles (owner decision)": [
        # The admin session-detail trail map was the last one on Leaflet +
        # raw OpenStreetMap raster tiles (their usage policy disallows
        # apps) — it now uses MapLibre GL JS + the OpenFreeMap "liberty"
        # style, same as the mobile app and the public alert page.
        "tile.openstreetmap.org",
        "leaflet@",
    ],
    "2026-09-23 shared vocabulary identifier renames (owner decision)": [
        # mobile/store/useContactsStore.ts -> useCircleStore.ts,
        # mobile/hooks/useContactsScreen.ts -> useCircleScreen.ts,
        # mobile/components/CircleOfTrustCard.tsx -> CircleMemberCard.tsx
        # (the CircleMemberCard name was reserved for exactly this rename —
        # see the 2026-09-22 native Circle-member surface entry above).
        "useContactsStore",
        "useContactsScreen",
        "CircleOfTrustCard",
    ],
    "2026-09-23 push deep_link payload field (surface-consolidation retro)": [
        # The subscription-lapse push carried an unused `deep_link` data
        # field (edece44 dropped it); push data routes by `type` through
        # mobile/services/notificationRouting.ts. 0 hits in live source,
        # docs/ or .claude/rules/ when pinned.
        "deep_link",
    ],
    "2026-09-27 dead notification copy (owner-approved copy batch)": [
        # Push titles computed and discarded (circle alerts are SMS-only),
        # the never-sent server mirror of the client's pre-deadline reminder
        # copy (mobile/services/notifications.ts is the sole source now), and
        # the dead mobile/services/sms.ts module's message builders. sendSMS
        # is deliberately NOT listed: expo-sms's own sendSMSAsync contains it.
        "ALERT_SOS_TITLE",
        "ALERT_MISSED_TITLE",
        "ALERT_RENUDGE_TITLE",
        "SESSION_EXPIRING_TITLE",
        "SESSION_EXPIRING_BODY",
        "generateInvitationMessage",
        "generateEmergencyMessage",
        "generateMissedCheckInMessage",
        "sendCircleInvitation",
        # The all-clear title + body pair, merged into the single-line
        # ALL_CLEAR_SMS in a3f59b0 (ALL_CLEAR is SMS-only, so no push ever
        # read a separate title). docs/notifications.md M5 names them as the
        # previous form; docs/ isn't scanned.
        "ALL_CLEAR_TITLE",
        "ALL_CLEAR_BODY",
    ],
    "2026-09-27 sponsorship JWT magic link -> one-time short-link token": [
        # The sponsorship-management magic link was a JWT in a query string
        # (GET /sponsorships/portal?token=<jwt>); it is now a 12-char
        # one-time DB token behind {SHORT_DOMAIN}/s/p/{token} ->
        # GET /sponsorships/portal/{token}
        # (app/models/sponsorship_sign_in_token.py). docs/ and .claude/rules/
        # aren't scanned, so their "replaced" notes don't trip this.
        "mint_sponsorship_token",
        "decode_sponsorship_token",
        "sponsorship_mgmt",
        "/sponsorships/portal?token=",
    ],
}

_SCAN_ROOTS = [
    "backend/app",
    "backend/tests",
    "mobile/app",
    "mobile/components",
    "mobile/constants",
    "mobile/hooks",
    "mobile/services",
    "mobile/store",
    "mobile/types",
    "mobile/utils",
]
_SCAN_FILES = ["mobile/app.config.js", "mobile/package.json"]
_SUFFIXES = {".py", ".html", ".ts", ".tsx", ".js", ".mjs", ".json"}
_EXCLUDE = {
    Path("backend/tests/test_removed_feature_tombstones.py"),
    Path("backend/tests/test_photo_discovery_removed.py"),
    # Asserts the admin session-detail trail map no longer points at
    # tile.openstreetmap.org — legitimately names the removed URL, like
    # test_photo_discovery_removed.py above.
    Path("backend/tests/test_admin_session_detail_updates.py"),
    # Asserts the deleted /htmx/alerts/check route now 404s — legitimately
    # names the removed path, like test_photo_discovery_removed.py above.
    Path("backend/tests/test_web_alerts_list.py"),
    # Asserts /dashboard, /profile and POST /htmx/profile/update now 404 —
    # same reason.
    Path("backend/tests/test_web_account_and_landing.py"),
    # Asserts /gift, /gift/{code}, /sponsor and /sponsor/done now 404 —
    # same reason.
    Path("backend/tests/test_web_sponsorship_states.py"),
    # Asserts /referral/{code}, /group/{code}, /delete-account[/start|
    # /verify|/confirm], /admin/sessions/{id}/checkin-on-behalf and
    # /htmx/referral/* now 404 — same reason (2026-09-23 web path
    # vocabulary rename).
    Path("backend/tests/test_web_paths_renamed.py"),
    # Asserts GET /pricing now 404s — same reason (2026-09-23 backend
    # marketing pages).
    Path("backend/tests/test_marketing_removed.py"),
    # Lists the retired-vocabulary terms themselves (e.g. "Mark as Read") as
    # scan data — legitimately names them, like test_photo_discovery_removed.py
    # above.
    Path("backend/tests/test_vocabulary.py"),
    # Asserts the sign-in SMS no longer carries /sponsorships/portal?token=
    # — legitimately names the removed query form (2026-09-27 sponsorship
    # short link).
    Path("backend/tests/test_sponsorship_short_link.py"),
}


def _source_files():
    for root in _SCAN_ROOTS:
        for path in (_REPO / root).rglob("*"):
            rel = path.relative_to(_REPO)
            if (
                path.is_file()
                and path.suffix in _SUFFIXES
                and "node_modules" not in rel.parts
                and rel not in _EXCLUDE
            ):
                yield rel
    for f in _SCAN_FILES:
        yield Path(f)


def test_removed_identifiers_do_not_reappear():
    hits: list[str] = []
    files = list(_source_files())
    assert len(files) > 100, "scan found suspiciously few files — root paths drifted?"
    for rel in files:
        text = (_REPO / rel).read_text(encoding="utf-8", errors="ignore")
        for label, idents in REMOVED.items():
            for ident in idents:
                if ident in text:
                    line = next(
                        n
                        for n, text_line in enumerate(text.splitlines(), 1)
                        if ident in text_line
                    )
                    hits.append(f"{rel}:{line} — {ident!r} ({label})")
    assert not hits, "removed-feature identifiers found in live source:\n" + "\n".join(
        hits
    )
