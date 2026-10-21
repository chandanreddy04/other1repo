"""Tests for the public app config endpoint.

Mobile depends on this endpoint shape being stable — adding fields is
safe, renaming or removing breaks deployed app installs that can't
upgrade until users hit the store. Hence the explicit assertions on
field presence (rather than letting Pydantic drift silently).

Related: backend/app/api/v1/endpoints/app_config.py,
mobile/services/runtimeConfig.ts.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestAppConfigEndpoint:
    async def test_returns_all_expected_fields(self, client: AsyncClient):
        """Mobile bundles a fallback for each field; any missing field
        in the response means the runtime config can't replace it.
        """
        response = await client.get("/api/v1/config")
        assert response.status_code == 200
        body = response.json()
        for field in (
            "sms_number",
            "support_email",
            "app_domain",
            "short_domain",
            "marketing_origin",
            "privacy_url",
            "terms_url",
        ):
            assert field in body, f"missing field: {field}"

    async def test_no_auth_required(self, client: AsyncClient):
        """The endpoint is hit by mobile BEFORE login (auth screens
        need TERMS_URL etc.), so it must not require a token.
        """
        # No Authorization header on the client by default — this is
        # what an uninitialized install looks like.
        response = await client.get("/api/v1/config")
        assert response.status_code == 200

    async def test_sms_number_falls_back_to_twilio_phone_number(
        self, client: AsyncClient, monkeypatch
    ):
        """When SMS_DISPLAY_NUMBER is empty, surface TWILIO_PHONE_NUMBER
        instead so a deploy without explicit display config still
        gives mobile a usable number to show.
        """
        from app.core.config import settings

        monkeypatch.setattr(settings, "SMS_DISPLAY_NUMBER", "")
        monkeypatch.setattr(settings, "TWILIO_PHONE_NUMBER", "+14155550100")
        response = await client.get("/api/v1/config")
        assert response.json()["sms_number"] == "+14155550100"

    async def test_sms_display_number_wins_over_twilio_phone_number(
        self, client: AsyncClient, monkeypatch
    ):
        """When SMS_DISPLAY_NUMBER is set explicitly (e.g., a Messaging
        Service short code distinct from the sender), it takes
        precedence.
        """
        from app.core.config import settings

        monkeypatch.setattr(settings, "SMS_DISPLAY_NUMBER", "+12125550101")
        monkeypatch.setattr(settings, "TWILIO_PHONE_NUMBER", "+14155550100")
        response = await client.get("/api/v1/config")
        assert response.json()["sms_number"] == "+12125550101"

    async def test_legal_urls_derived_from_marketing_origin(
        self, client: AsyncClient, monkeypatch
    ):
        """Privacy + terms URLs are derived server-side from
        MARKETING_ORIGIN — single source of truth, no risk of mobile
        and backend pointing at different origins.
        """
        from app.core.config import settings

        monkeypatch.setattr(settings, "MARKETING_ORIGIN", "https://example.com")
        response = await client.get("/api/v1/config")
        body = response.json()
        assert body["marketing_origin"] == "https://example.com"
        assert body["privacy_url"] == "https://example.com/privacy"
        assert body["terms_url"] == "https://example.com/terms"
