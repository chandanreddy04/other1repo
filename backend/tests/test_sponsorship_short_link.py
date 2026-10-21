"""Tests for the sponsorship magic-link short link (/s/p/{token}), which
replaces the old JWT-in-query-string sponsorship portal link (removed
2026-09-27). See app/web/short_links.py NESTED_SHORT_LINKS,
app/web/routes_web_sponsorships.py, app/models/sponsorship_sign_in_token.py.

The lander is split so link previewers can't burn the one-time token: GET
/sponsorships/portal/{token} only checks it and renders a one-button page;
the button's POST consumes it and redirects to Stripe.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud.sponsorship_sign_in_token import crud_sponsorship_sign_in_token
from app.services.sms import SMSResult
from app.web.short_links import NESTED_SHORT_LINKS, SHORT_LINKS, UNIVERSAL_LINK_PATHS
from tests.helpers import create_test_user


def _sms_ok() -> SMSResult:
    return SMSResult(success=True, message_id="sm_1", error=None)


class TestNestedRegistryFirstLetterRule:
    """The nested registry has its own copy of the first-letter rule
    (test_short_link_first_letter.py only covers SHORT_LINKS) — "p" must be
    the first letter of "portal", the resource segment of its lander."""

    def test_p_matches_portal(self):
        assert len(NESTED_SHORT_LINKS) == 1
        nested = NESTED_SHORT_LINKS[0]
        assert nested.parent_slug == "s"
        assert nested.slug == "p"
        resource = nested.lander.strip("/").split("/")[-1]
        assert resource == "portal"
        assert nested.slug == resource[0]

    def test_parent_slug_is_a_real_top_level_short_link(self):
        nested = NESTED_SHORT_LINKS[0]
        assert nested.parent_slug in {sl.slug for sl in SHORT_LINKS}

    def test_nested_lander_lives_under_its_parent_lander_resource(self):
        """"s" <-> sponsorships holds for the nested entry too: the nested
        lander sits under the parent slug's own lander resource."""
        nested = NESTED_SHORT_LINKS[0]
        parent = next(sl for sl in SHORT_LINKS if sl.slug == nested.parent_slug)
        parent_resource = parent.lander.strip("/").split("/")[0]
        assert nested.lander.strip("/").split("/")[0] == parent_resource
        assert nested.parent_slug == parent_resource[0]

    def test_nested_entry_is_not_aasa_claimed(self):
        assert NESTED_SHORT_LINKS[0].aasa_claimed is False


class TestAasaUnaffected:
    def test_no_s_path_in_universal_link_paths(self):
        """Neither the top-level checkout slug nor the nested portal slug
        rides in the AASA manifest — sponsorship checkout and the
        sponsorship portal are both browser-only (Stripe, IAP guideline)."""
        assert "/s/*" not in UNIVERSAL_LINK_PATHS
        assert not any(p.startswith("/s/") for p in UNIVERSAL_LINK_PATHS)


@pytest.mark.asyncio
class TestNestedShortLinkRedirect:
    async def test_valid_token_redirects_to_portal_path(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155559301")
        row = await crud_sponsorship_sign_in_token.create_for_phone(
            db_session, phone_number_id=user.phone_number_id
        )

        response = await client.get(f"/s/p/{row.token}", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == f"/sponsorships/portal/{row.token}"

    async def test_unknown_token_still_redirects(self, client: AsyncClient):
        """The short link is a dumb path-rewrite — it doesn't look the
        token up. An unknown token still 302s; the lander decides what to
        render (the "link has expired" phone stage)."""
        response = await client.get("/s/p/doesnotexist9", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/sponsorships/portal/doesnotexist9"

    async def test_url_safe_punctuation_passes_through_intact(
        self, client: AsyncClient
    ):
        """token_urlsafe draws from [A-Za-z0-9_-] — a leading "-" or an
        embedded "_" must survive the path param and the redirect."""
        response = await client.get("/s/p/-a_B-c_D-e_F", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/sponsorships/portal/-a_B-c_D-e_F"

    async def test_token_case_is_preserved_not_uppercased(self, client: AsyncClient):
        """Unlike a top-level coded slug (share/referral code), the nested
        redirect must NOT uppercase — the token is case-sensitive."""
        response = await client.get("/s/p/MiXeDcAsE01", follow_redirects=False)

        assert response.headers["location"] == "/sponsorships/portal/MiXeDcAsE01"


@pytest.mark.asyncio
class TestTopLevelSCodeUnaffected:
    async def test_eight_char_share_code_still_the_checkout_lander(
        self, client: AsyncClient
    ):
        """/s/{code} (the sponsorship-checkout short link) must keep
        working exactly as before — the nested /s/p/{token} route is an
        additional, structurally distinct path (one extra segment), not a
        replacement."""
        response = await client.get("/s/abc12345", follow_redirects=False)

        assert response.status_code == 301
        assert response.headers["location"] == "/sponsorships/ABC12345"


@pytest.mark.asyncio
class TestSignInLinkSmsCarriesShortLink:
    @patch(
        "app.web.routes_web_sponsorships.sms_opt_out.gated_send_sms",
        new_callable=AsyncMock,
    )
    async def test_sms_body_has_short_link_and_frozen_sentence(
        self, mock_sms, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155559302", full_name="Sponsor"
        )
        user.stripe_customer_id = "cus_real_short_link"
        await db_session.commit()
        mock_sms.return_value = _sms_ok()

        response = await client.post(
            "/sponsorships/sign-in-links",
            data={"phone_number": "+14155559302"},
        )

        assert response.status_code == 200
        mock_sms.assert_awaited_once()
        sent = mock_sms.await_args.kwargs["message"]

        # The sentence around the link is frozen, byte-identical — only the
        # URL changed.
        prefix = "Manage your Made It Home sponsorships: "
        suffix = " (link expires in 10 minutes)"
        assert sent.startswith(prefix)
        assert sent.endswith(suffix)

        link = sent[len(prefix) : -len(suffix)]
        expected_prefix = f"{settings.SHORT_DOMAIN}/s/p/"
        assert link.startswith(expected_prefix)
        token = link[len(expected_prefix) :]
        assert len(token) == 12
        assert "/sponsorships/portal?token=" not in sent


async def _token_used_at(db: AsyncSession, token: str):
    """Fresh column read of the token's used_at (no cached ORM instance)."""
    from sqlalchemy import select

    from app.models.sponsorship_sign_in_token import SponsorshipSignInToken

    return (
        await db.execute(
            select(SponsorshipSignInToken.used_at).where(
                SponsorshipSignInToken.token == token
            )
        )
    ).scalar_one()


async def _sponsor_token(db: AsyncSession, phone: str, customer: str) -> str:
    user = await create_test_user(db, phone_number=phone, full_name="Sponsor")
    user.stripe_customer_id = customer
    await db.commit()
    row = await crud_sponsorship_sign_in_token.create_for_phone(
        db, phone_number_id=user.phone_number_id
    )
    return row.token


@pytest.mark.asyncio
class TestPortalLanderWithToken:
    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_valid_token_get_renders_button_and_does_not_consume(
        self,
        mock_create,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Link previewers GET the SMS link on their own — a GET must render
        the one-button page, never burn the one-time token or open a Stripe
        portal session."""
        token = await _sponsor_token(db_session, "+14155559303", "cus_real_portal_token")

        response = await client.get(
            f"/sponsorships/portal/{token}", follow_redirects=False
        )

        assert response.status_code == 200
        assert "Open billing portal" in response.text
        assert 'method="POST"' in response.text
        assert await _token_used_at(db_session, token) is None
        mock_create.assert_not_called()

    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_valid_token_post_redirects_to_stripe_and_consumes(
        self,
        mock_create,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        mock_create.return_value = MagicMock(url="https://billing.stripe.com/p/tok")
        token = await _sponsor_token(db_session, "+14155559308", "cus_real_post_token")

        response = await client.post(
            f"/sponsorships/portal/{token}", follow_redirects=False
        )

        assert response.status_code == 303
        assert response.headers["location"] == "https://billing.stripe.com/p/tok"
        assert await _token_used_at(db_session, token) is not None

    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_used_token_renders_expired_stage(
        self,
        mock_create,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """After a successful POST the link is spent: a second POST and a
        later GET both land on the "link has expired" phone stage."""
        mock_create.return_value = MagicMock(url="https://billing.stripe.com/p/used")
        token = await _sponsor_token(db_session, "+14155559304", "cus_real_used_token")

        first = await client.post(
            f"/sponsorships/portal/{token}", follow_redirects=False
        )
        second = await client.post(
            f"/sponsorships/portal/{token}", follow_redirects=False
        )
        later_get = await client.get(
            f"/sponsorships/portal/{token}", follow_redirects=False
        )

        assert first.status_code == 303
        assert second.status_code == 200
        assert "link has expired" in second.text
        assert later_get.status_code == 200
        assert "link has expired" in later_get.text
        assert "Open billing portal" not in later_get.text
        mock_create.assert_called_once()

    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_unknown_token_renders_expired_stage(
        self, mock_create, client: AsyncClient
    ):
        get_resp = await client.get("/sponsorships/portal/nosuchtoken1")
        post_resp = await client.post("/sponsorships/portal/nosuchtoken1")

        for response in (get_resp, post_resp):
            assert response.status_code == 200
            assert "link has expired" in response.text
        mock_create.assert_not_called()


@pytest.mark.asyncio
class TestPortalLanderEdges:
    async def test_portal_without_token_segment_renders_expired_stage(
        self, client: AsyncClient
    ):
        """A token-less /sponsorships/portal (a truncated link) has its own
        route in web_sponsorships_router — included before web_router, so it
        is not swallowed by GET /sponsorships/{share_code} — and renders the
        same "link has expired" phone stage as an unknown token."""
        response = await client.get("/sponsorships/portal", follow_redirects=False)

        assert response.status_code == 200
        assert "link has expired" in response.text
        assert 'action="/sponsorships/sign-in-links"' in response.text

    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_full_chain_from_short_link_to_stripe(
        self, mock_create, client: AsyncClient, db_session: AsyncSession
    ):
        mock_create.return_value = MagicMock(url="https://billing.stripe.com/p/chain")
        token = await _sponsor_token(db_session, "+14155559305", "cus_real_chain")

        hop = await client.get(f"/s/p/{token}", follow_redirects=False)
        landed = await client.get(hop.headers["location"], follow_redirects=False)
        clicked = await client.post(hop.headers["location"], follow_redirects=False)

        assert landed.status_code == 200
        assert "Open billing portal" in landed.text
        assert clicked.status_code == 303
        assert clicked.headers["location"] == "https://billing.stripe.com/p/chain"

    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_stripe_failure_does_not_burn_the_link(
        self, mock_create, client: AsyncClient, db_session: AsyncSession
    ):
        """The POST consumes the token atomically before the Stripe call, but
        a Stripe failure releases it — the page re-renders the button with
        "try again in a moment", so the same link must work on the retry."""
        mock_create.side_effect = [
            RuntimeError("stripe down"),
            MagicMock(url="https://billing.stripe.com/p/retry"),
        ]
        token = await _sponsor_token(db_session, "+14155559306", "cus_real_retry")

        first = await client.post(
            f"/sponsorships/portal/{token}", follow_redirects=False
        )
        assert first.status_code == 200
        assert "open the billing portal" in first.text
        assert "Open billing portal" in first.text
        # Released: unused again, so the GET still shows the button.
        assert await _token_used_at(db_session, token) is None
        assert "Open billing portal" in (
            await client.get(f"/sponsorships/portal/{token}")
        ).text

        second = await client.post(
            f"/sponsorships/portal/{token}", follow_redirects=False
        )
        third = await client.post(
            f"/sponsorships/portal/{token}", follow_redirects=False
        )

        assert second.status_code == 303
        assert second.headers["location"] == "https://billing.stripe.com/p/retry"
        # Used once successfully -> spent.
        assert third.status_code == 200
        assert "link has expired" in third.text

    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_deletion_jwt_does_not_unlock_the_portal(
        self, mock_create, client: AsyncClient
    ):
        """Re-homed from the removed JWT tests: a token minted for another
        purpose (the /account/delete JWT) must not open the portal."""
        import uuid

        from app.services.account_deletion import mint_deletion_token

        path = f"/sponsorships/portal/{mint_deletion_token(uuid.uuid4())}"
        for response in (await client.get(path), await client.post(path)):
            assert response.status_code == 200
            assert "link has expired" in response.text
        mock_create.assert_not_called()

    async def test_overlong_token_renders_expired_not_500(self, client: AsyncClient):
        path = "/sponsorships/portal/" + "x" * 200
        for response in (await client.get(path), await client.post(path)):
            assert response.status_code == 200
            assert "link has expired" in response.text

    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_token_never_reflected_in_page(
        self, mock_create, client: AsyncClient, db_session: AsyncSession
    ):
        row = await crud_sponsorship_sign_in_token.create_for_phone(
            db_session,
            phone_number_id=(
                await create_test_user(db_session, phone_number="+14155559307")
            ).phone_number_id,
        )
        # The one-button page (GET) posts back to its own URL, so the token
        # isn't in the HTML; nor is it in the POST's not_found stage (no
        # usable Stripe customer).
        landing = await client.get(f"/sponsorships/portal/{row.token}")
        response = await client.post(f"/sponsorships/portal/{row.token}")

        assert landing.status_code == 200
        assert "Open billing portal" in landing.text
        assert row.token not in landing.text
        assert response.status_code == 200
        assert "No subscriptions found" in response.text
        assert row.token not in response.text
