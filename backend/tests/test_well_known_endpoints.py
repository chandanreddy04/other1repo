"""Tests for the universal-link / app-link manifest endpoints.

Apple + Google reject these files silently on malformed content (no
error returned to the app), so shape regressions strand all of /r, /g,
/sub, /plans, /subscription back on the browser fallback. Explicit
shape tests.
"""

import json

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestAppleAppSiteAssociation:
    async def test_returns_404_when_team_id_unset(
        self, client: AsyncClient, monkeypatch
    ):
        """Dev installs can't sign AASA for a real Team ID; return 404
        instead of garbage so iOS cleanly falls back to the browser."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "IOS_TEAM_ID", "")
        response = await client.get("/.well-known/apple-app-site-association")
        assert response.status_code == 404

    async def test_payload_shape(self, client: AsyncClient, monkeypatch):
        """The shape Apple's parser expects: applinks.details[].appID +
        applinks.details[].paths. Missing fields → silent reject."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "IOS_TEAM_ID", "ABC1234567")
        monkeypatch.setattr(settings, "IOS_BUNDLE_ID", "com.example.app")
        response = await client.get("/.well-known/apple-app-site-association")
        assert response.status_code == 200
        # Apple's parser ALSO checks Content-Type. application/json is
        # the only accepted value for the unsigned variant.
        assert response.headers["content-type"].startswith("application/json")
        body = json.loads(response.content)
        details = body["applinks"]["details"]
        assert len(details) == 1
        assert details[0]["appID"] == "ABC1234567.com.example.app"
        # /r/ + /g/ (group-plan join, replacing /f/) get claimed, plus the
        # codeless /sub (paywall) and the app's own Stripe-return paths
        # /plans + /subscription — each opens an in-app screen, never a
        # Stripe checkout page. /s/ (sponsorship checkout) is NOT here: a
        # claimed link must never open a Stripe checkout page in-app
        # (Apple 3.1.1 / Play Billing), so sponsorship checkout stays in
        # the browser. /c/ (Circle invite)
        # is ALSO not claimed (owner decision 2026-09-23) — Circle members
        # use mobile web only, so there's no in-app accept screen to route
        # the link into.
        assert "/r/*" in details[0]["paths"]
        assert "/g/*" in details[0]["paths"]
        assert "/sub" in details[0]["paths"]
        assert "/plans" in details[0]["paths"]
        assert "/subscription" in details[0]["paths"]
        assert "/f/*" not in details[0]["paths"], (
            "/f/* was the group-plan slug before this commit reassigned it "
            "to /g/* (owner decision 2026-09-23, nothing shipped yet)."
        )
        assert "/c/*" not in details[0]["paths"], (
            "/c/* (Circle invite) is browser-only — Circle members use "
            "mobile web only, there's no in-app accept screen."
        )
        assert "/s/*" not in details[0]["paths"], (
            "/s/* is a Stripe sponsorship-checkout deep link — keeping it out "
            "of AASA is what protects the app from IAP review."
        )
        assert "/a/*" not in details[0]["paths"], (
            "/a/* (public alert-details page) is browser-only — an "
            "SMS-only contact with no app/account must still see it."
        )

    async def test_cacheable_for_15_minutes(self, client: AsyncClient, monkeypatch):
        """SMS-driven traffic bursts can hammer this endpoint; the 15-min
        cache header keeps the origin from being a bottleneck."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "IOS_TEAM_ID", "ABC1234567")
        response = await client.get("/.well-known/apple-app-site-association")
        assert "max-age=900" in response.headers["cache-control"]


@pytest.mark.asyncio
class TestAndroidAssetlinks:
    async def test_returns_404_when_fingerprints_unset(
        self, client: AsyncClient, monkeypatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ANDROID_SHA256_CERT_FINGERPRINTS", "")
        response = await client.get("/.well-known/assetlinks.json")
        assert response.status_code == 404

    async def test_payload_shape_single_fingerprint(
        self, client: AsyncClient, monkeypatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ANDROID_PACKAGE_NAME", "com.example.app")
        monkeypatch.setattr(
            settings,
            "ANDROID_SHA256_CERT_FINGERPRINTS",
            "AA:BB:CC:DD:EE:FF",
        )
        response = await client.get("/.well-known/assetlinks.json")
        assert response.status_code == 200
        body = json.loads(response.content)
        # Top-level is an ARRAY of statements (Google's parser is
        # picky — a single object would be rejected).
        assert isinstance(body, list)
        assert len(body) == 1
        target = body[0]["target"]
        assert target["namespace"] == "android_app"
        assert target["package_name"] == "com.example.app"
        assert target["sha256_cert_fingerprints"] == ["AA:BB:CC:DD:EE:FF"]
        assert body[0]["relation"] == ["delegate_permission/common.handle_all_urls"]

    async def test_payload_supports_multiple_fingerprints(
        self, client: AsyncClient, monkeypatch
    ):
        """EAS internal, EAS production, and Play App Signing all sign
        with different keys — the manifest has to list every one."""
        from app.core.config import settings

        monkeypatch.setattr(
            settings,
            "ANDROID_SHA256_CERT_FINGERPRINTS",
            "AA:BB:CC, DD:EE:FF , GG:HH:II",
        )
        response = await client.get("/.well-known/assetlinks.json")
        body = json.loads(response.content)
        assert body[0]["target"]["sha256_cert_fingerprints"] == [
            "AA:BB:CC",
            "DD:EE:FF",
            "GG:HH:II",
        ]
