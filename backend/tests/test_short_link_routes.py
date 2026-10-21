"""Short-link routes (/r/, /g/, /c/, /s/, /a/, /sub) — the browser fallback
for universal links. On a device with the app installed the OS catches the
URL via the AASA / assetlinks manifest and never hits the server; these
tests cover the fallback path for non-installed-app users."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus
from app.web.short_links import CLAIMED_APP_PATHS, SHORT_LINKS, UNIVERSAL_LINK_PATHS
from tests.helpers import create_test_user


@pytest.mark.asyncio
class TestReferralShortUrl:
    async def test_redirects_to_canonical_referral_lander(self, client: AsyncClient):
        response = await client.get("/r/abc12345", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/referrals/ABC12345"

    async def test_normalizes_code_to_uppercase(self, client: AsyncClient):
        """Codes share-link generators may pick differs in case from the
        DB-stored uppercase, so normalize on the redirect to avoid two
        canonical URLs for the same code."""
        response = await client.get("/r/abc", follow_redirects=False)
        assert response.headers["location"].endswith("/ABC")

    async def test_no_open_redirect_via_query_param(self, client: AsyncClient):
        """Regression: the registry-driven handler must take its lander
        only from the closure, never from a request param. A `_lander`
        (or any) query param must not influence the redirect target."""
        response = await client.get(
            "/r/abc?_lander=https://evil.com", follow_redirects=False
        )
        assert response.status_code == 301
        assert response.headers["location"] == "/referrals/ABC"


@pytest.mark.asyncio
class TestGroupJoinShortUrl:
    async def test_redirects_to_group_lander(self, client: AsyncClient):
        response = await client.get("/g/xyz789", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/groups/XYZ789"

    async def test_old_f_slug_is_gone(self, client: AsyncClient):
        """ "f" was the group-plan slug before this commit reassigned it to
        "g" (owner decision 2026-09-23, nothing shipped yet so no alias)."""
        response = await client.get("/f/xyz789", follow_redirects=False)
        assert response.status_code == 404


@pytest.mark.asyncio
class TestSponsorshipShortUrl:
    async def test_redirects_to_sponsorship_lander(self, client: AsyncClient):
        # Sponsorship checkout is registry-driven like the rest, but
        # browser-only (not AASA-claimed) since it leads to Stripe checkout.
        response = await client.get("/s/abc", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/sponsorships/ABC"


@pytest.mark.asyncio
class TestAlertShortUrl:
    async def test_redirects_to_public_alert_page_uppercased(self, client: AsyncClient):
        alert_id = "0f8e2b7a-3c4d-4e5f-9a1b-2c3d4e5f6a7b"
        response = await client.get(f"/a/{alert_id}", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == f"/alerts/{alert_id.upper()}"

    async def test_uppercased_uuid_still_resolves_the_alert(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # The SMS carries the lowercase UUID; the redirect upper-cases it.
        # Python's UUID parsing must accept that — the live page renders,
        # not the "link isn't valid" card.
        owner = await create_test_user(
            db_session, phone_number="+14155559901", full_name="Ana Owner"
        )
        contact = await create_test_user(
            db_session, phone_number="+14155559902", full_name="Cody Contact"
        )
        session = Session(
            user_id=owner.id,
            expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
            status=SessionStatus.MISSED.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)
        alert = Alert(
            session_id=session.id,
            sent_to_phone_id=contact.phone_number_id,
            alert_type=AlertType.MISSED_SESSION,
            status=AlertStatus.SENT,
            message="body",
        )
        db_session.add(alert)
        await db_session.commit()
        await db_session.refresh(alert)

        redirect = await client.get(f"/a/{alert.id}", follow_redirects=False)
        assert redirect.status_code == 301
        page = await client.get(redirect.headers["location"])
        assert page.status_code == 200
        assert "Acknowledge" in page.text
        assert "isn't valid" not in page.text


@pytest.mark.asyncio
class TestCircleJoinShortUrl:
    async def test_redirects_to_circle_lander(self, client: AsyncClient):
        response = await client.get("/c/abc123", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/circles/ABC123"

    async def test_normalizes_code_to_uppercase(self, client: AsyncClient):
        response = await client.get("/c/abc", follow_redirects=False)
        assert response.headers["location"].endswith("/ABC")


@pytest.mark.asyncio
class TestCircleJoinLander:
    async def test_valid_code_shows_inviter_name(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(
            db_session,
            phone_number="+14155550150",
            full_name="Alice Smith",
            circle_invite_code="CIRCLE01",
        )
        response = await client.get("/circles/CIRCLE01")
        assert response.status_code == 200
        # First name surfaced, code echoed for manual entry after install.
        assert "Alice" in response.text
        assert "CIRCLE01" in response.text

    async def test_lookup_is_case_insensitive(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(
            db_session,
            phone_number="+14155550151",
            full_name="Bob Jones",
            circle_invite_code="CIRCLE02",
        )
        # Short-url redirect upper-cases, but hitting the lander directly
        # in mixed case must still resolve.
        response = await client.get("/circles/circle02")
        assert response.status_code == 200
        assert "Bob" in response.text

    async def test_unknown_code_renders_invalid_page(self, client: AsyncClient):
        response = await client.get("/circles/NOPE9999")
        assert response.status_code == 200
        assert "isn't valid" in response.text


class TestRegistryConsistency:
    """The short-link registry (app/web/short_links.py) is the single
    source of truth. These guard against the AASA path list and the
    mobile app-link config drifting away from it — a drift that would
    otherwise only surface as an asymmetric, platform-specific deep-link
    failure in production that no other test catches."""

    def test_aasa_paths_are_the_claimed_slugs(self):
        expected = [
            (f"/{sl.slug}/*" if sl.has_code else f"/{sl.slug}")
            for sl in SHORT_LINKS
            if sl.aasa_claimed
        ] + list(CLAIMED_APP_PATHS)
        assert expected == UNIVERSAL_LINK_PATHS
        # The IAP guard: sponsorship checkout is in the registry but NOT claimed.
        assert "/s/*" not in UNIVERSAL_LINK_PATHS

    def test_mobile_android_app_links_match_registry(self):
        """mobile/app.config.js Android intentFilters must claim exactly
        the registry's AASA-claimed paths, checked PER HOST so dropping a
        prefix/path from only one host (e.g. staging) is caught. Parses
        BOTH the coded `pathPrefix:` entries (/r/, /g/) and the exact
        `path:` entries (/sub, /plans, /subscription) — a coded claimed
        slug needs a prefix match (a code follows), a codeless one needs
        an exact match.

        (iOS associatedDomains are host-level — `applinks:madeitho.me` —
        and carry no per-path info; the iOS path set is governed
        server-side by UNIVERSAL_LINK_PATHS, covered above and in the
        well-known endpoint tests.)"""
        entries = _android_app_link_entries()

        claimed_prefixes = {
            f"/{sl.slug}/" for sl in SHORT_LINKS if sl.aasa_claimed and sl.has_code
        }
        claimed_exact = {
            f"/{sl.slug}" for sl in SHORT_LINKS if sl.aasa_claimed and not sl.has_code
        } | set(CLAIMED_APP_PATHS)

        # Group by host so single-host drift is caught — a set of all
        # prefixes would dedupe across hosts.
        by_host_prefix: dict[str, set[str]] = {}
        by_host_exact: dict[str, set[str]] = {}
        for entry in entries:
            host = entry["host"]
            by_host_prefix.setdefault(host, set())
            by_host_exact.setdefault(host, set())
            if "pathPrefix" in entry:
                by_host_prefix[host].add(entry["pathPrefix"])
            else:
                by_host_exact[host].add(entry["path"])

        for host in by_host_prefix:
            assert by_host_prefix[host] == claimed_prefixes, (
                f"Android app-link prefixes for host {host} drifted from the "
                f"short-link registry: config={by_host_prefix[host]} "
                f"registry={claimed_prefixes}"
            )
            assert by_host_exact[host] == claimed_exact, (
                f"Android app-link exact paths for host {host} drifted from the "
                f"short-link registry: config={by_host_exact[host]} "
                f"registry={claimed_exact}"
            )

    def test_android_hosts_match_ios_associated_domains(self):
        """The Android intentFilters hosts and the iOS `associatedDomains`
        (`applinks:<host>`) must be the same set — a host claimed on one
        platform only would open the app on one OS and the browser on the
        other."""
        hosts = {entry["host"] for entry in _android_app_link_entries()}
        ios_hosts = set(re.findall(r"'applinks:([^']+)'", _mobile_config_text()))
        assert ios_hosts, "no iOS associatedDomains found in app.config.js"
        assert hosts == ios_hosts, (
            f"Android app-link hosts {hosts} != iOS associatedDomains {ios_hosts}"
        )


_ALLOWED_APP_LINK_KEYS = {"scheme", "host", "path", "pathPrefix"}


def _mobile_config_text() -> str:
    config = Path(__file__).resolve().parents[2] / "mobile" / "app.config.js"
    if not config.exists():  # backend-only checkout
        pytest.skip("mobile/app.config.js not present")
    return config.read_text()


def _android_app_link_entries() -> list[dict[str, str]]:
    """Every `{ scheme, host, path|pathPrefix }` data object in
    app.config.js, parsed key-order-independently. Fails on any other key
    (`pathPattern`, `pathSuffix`, `pathAdvancedPattern`, …) — the registry
    only speaks exact paths and prefixes, so a pattern could claim paths
    this consistency check can't see — and on an entry with neither or
    both of `path` / `pathPrefix`."""
    text = _mobile_config_text()
    entries: list[dict[str, str]] = []
    for body in re.findall(r"\{([^{}]*\bhost\s*:[^{}]*)\}", text):
        keys = re.findall(r"(\w+)\s*:", body)
        pairs = dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", body))
        unknown = set(keys) - _ALLOWED_APP_LINK_KEYS
        assert not unknown, (
            f"Android app-link data entry uses {sorted(unknown)} — only "
            f"{sorted(_ALLOWED_APP_LINK_KEYS)} are allowed: {{{body.strip()}}}"
        )
        assert set(keys) == set(pairs), (
            f"Android app-link data entry has a non-literal value: {{{body.strip()}}}"
        )
        assert ("path" in pairs) != ("pathPrefix" in pairs), (
            "Android app-link data entry needs exactly one of path / "
            f"pathPrefix: {{{body.strip()}}}"
        )
        entries.append(pairs)
    assert entries, "no Android app-link data entries found in app.config.js"
    return entries
