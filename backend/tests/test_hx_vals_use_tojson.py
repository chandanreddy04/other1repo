"""Tests for the hx-vals |tojson conversion and referral-code normalisation.

security.md: hx-vals must be built with `|tojson`, never by interpolating
values into a literal JSON string in the template — the browser decodes
autoescaped `&#34;` back to `"` before htmx parses the attribute, so a
quote in a phone number or next_url used to be able to break out of the
hx-vals JSON. All seven legacy sites (fragments/auth_form.html,
otp_verification.html, referral_auth_form.html, circle_invite.html) were
converted; this file pins that with a static scan (a) and an escaping
round-trip (b).

routes_htmx_referral.py's three Form-based referral_code entry points now
run the raw value through `_normalise_referral_code` (8-char uppercase
alphanumeric — the real User.share_code format,
subscription_service.generate_share_code) before it reaches a query or a
template. (c) pins that a malformed code renders the flow's existing
invalid-code state instead of a 422, and is never echoed back raw.
"""

import html
import json
import re
from pathlib import Path

import pytest
from httpx import AsyncClient
from markupsafe import escape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.otp import OTP
from app.services.otp import otp_service
from app.web.routes_htmx_auth import templates as auth_templates
from tests.helpers import create_test_user

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "web" / "templates"

# Every hx-vals attribute must be EXACTLY one single-quoted Jinja
# expression ending in `|tojson`: `hx-vals='{{ <expr>|tojson }}'`. That
# rules out, in one check: a literal JSON object (the old broken shape), a
# literal object with a partial `{{ v|tojson }}` inside it, a double-quoted
# attribute (`|tojson` leaves `"` raw, so it would end the attribute), and
# an attribute split over several lines.
_HX_VALS_ATTR = re.compile(r"""\b(?:data-)?hx-vals\s*=""")
_SAFE_HX_VALS = re.compile(r"""(?:data-)?hx-vals='\{\{(?:(?!\}\}|').)*\|tojson\s*\}\}'""")


def _unsafe_hx_vals(text: str) -> list[str]:
    """Return a snippet for every hx-vals attribute not in the safe shape."""
    offenders = []
    for m in _HX_VALS_ATTR.finditer(text):
        if not _SAFE_HX_VALS.match(text, m.start()):
            offenders.append(text[m.start() : m.start() + 80])
    return offenders


class TestHxValsUseTojson:
    """(a) Static scan: every template hx-vals is a single-quoted
    `{{ ...|tojson }}` expression."""

    def test_every_hx_vals_attribute_is_a_single_tojson_expression(self):
        offenders = []
        for path in TEMPLATES_DIR.rglob("*.html"):
            for snippet in _unsafe_hx_vals(path.read_text()):
                offenders.append(f"{path.relative_to(TEMPLATES_DIR)}: {snippet}")
        assert offenders == []

    def test_scan_finds_the_templates_hx_vals_sites(self):
        # Guard against the scan silently matching nothing (a renamed
        # directory or attribute would make the test above vacuous).
        total = sum(
            len(_HX_VALS_ATTR.findall(p.read_text()))
            for p in TEMPLATES_DIR.rglob("*.html")
        )
        assert total >= 7

    @pytest.mark.parametrize(
        "bad",
        [
            """hx-vals='{"k": "{{ v }}"}'""",
            """hx-vals='{ "k": {{ v|tojson }} }'""",
            """hx-vals="{{ {"k": v}|tojson }}\"""",
            """hx-vals='{{ {"k": v} }}'""",
            """data-hx-vals='{"k": 1}'""",
        ],
    )
    def test_scan_flags_unsafe_shapes(self, bad: str):
        assert _unsafe_hx_vals(f"<button {bad}>") != []

    def test_scan_accepts_the_safe_shape(self):
        assert _unsafe_hx_vals("""<b hx-vals='{{ {"k": v, "n": 1}|tojson }}'>""") == []


class TestOtpFragmentHxValsEscaping:
    """(b) The rendered hx-vals attribute round-trips exactly through JSON
    for values containing `'`, `"` and a `</script>` breakout attempt."""

    def test_hx_vals_survives_hostile_phone_and_next_url(self):
        phone_number = """attacker"'</script><script>alert(1)</script>"""
        next_url = """/x?a=1&b="'<>"""

        rendered = auth_templates.env.get_template(
            "fragments/otp_verification.html"
        ).render(
            request=None,
            phone_number=phone_number,
            next_url=next_url,
            show_resend=True,
            resend_wait_seconds=0,
        )

        match = re.search(r"hx-vals='([^']*)'", rendered)
        assert match, "hx-vals attribute not found in rendered fragment"

        parsed = json.loads(html.unescape(match.group(1)))
        assert parsed == {
            "phone_number": phone_number,
            "next_url": next_url,
            "is_resend": True,
        }

        # The breakout payload must never appear outside the JSON-encoded
        # (and therefore inert) hx-vals value.
        outside_hx_vals = rendered.replace(match.group(0), "")
        assert "<script>alert(1)</script>" not in outside_hx_vals


def _assert_not_echoed(text: str, bad_code: str) -> None:
    """The raw code must not appear in any encoding a template could emit:
    as-is, HTML-escaped (a `value="..."` attribute), or JSON-encoded (an
    hx-vals `|tojson`)."""
    assert bad_code not in text
    assert str(escape(bad_code)) not in text
    assert json.dumps(bad_code)[1:-1] not in text
    assert str(escape(json.dumps(bad_code)[1:-1])) not in text


@pytest.mark.asyncio
class TestReferralCodeNormalisation:
    """(c) A malformed referral_code renders the invalid-code state — never
    a 422, never echoed back raw — across all three
    routes_htmx_referral.py entry points."""

    @pytest.mark.parametrize("bad_code", ["../x", 'ABC"D', "X" * 40])
    async def test_request_otp_rejects_malformed_code(
        self, client: AsyncClient, bad_code: str
    ):
        response = await client.post(
            "/htmx/referrals/request-otp",
            data={"phone_number": "+14155591000", "referral_code": bad_code},
        )
        assert response.status_code == 200
        assert "Invalid referral code" in response.text
        _assert_not_echoed(response.text, bad_code)

    @pytest.mark.parametrize(
        "phone,bad_code",
        [
            ("+14155591010", "../x"),
            ("+14155591011", 'ABC"D'),
            ("+14155591012", "X" * 40),
        ],
    )
    async def test_verify_otp_rejects_malformed_code(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        phone: str,
        bad_code: str,
    ):
        # A valid OTP so the failure we observe is the referral-code
        # rejection, not an unrelated OTP error.
        await otp_service.send_otp(db_session, phone)
        result = await db_session.execute(
            select(OTP).where(OTP.phone_number == phone)
        )
        otp = result.scalars().first()
        assert otp is not None

        response = await client.post(
            "/htmx/referrals/verify-otp",
            data={
                "phone_number": phone,
                "otp_code": otp.otp_code,
                "referral_code": bad_code,
            },
        )
        assert response.status_code == 200
        assert "Invalid referral code" in response.text
        _assert_not_echoed(response.text, bad_code)

    @pytest.mark.parametrize(
        "phone,bad_code",
        [
            ("+14155591020", "../x"),
            ("+14155591021", 'ABC"D'),
            ("+14155591022", "X" * 40),
        ],
    )
    async def test_claim_from_invite_rejects_malformed_code(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        phone: str,
        bad_code: str,
    ):
        from app.core.security import create_access_token

        user = await create_test_user(db_session, phone_number=phone)
        response = await client.post(
            "/htmx/referrals/claim-from-invite",
            data={"referral_code": bad_code},
            cookies={"access_token": create_access_token(str(user.id))},
        )
        assert response.status_code == 200
        assert "Unable to apply referral" in response.text
        _assert_not_echoed(response.text, bad_code)

    @pytest.mark.parametrize("bad_code", ["../x", 'ABC"D'])
    async def test_verify_otp_failure_does_not_echo_malformed_code(
        self, client: AsyncClient, bad_code: str
    ):
        # No OTP was sent for this phone, so verification fails and the
        # form is re-rendered — the path that used to echo the raw code
        # into the hidden input and the Resend hx-vals.
        response = await client.post(
            "/htmx/referrals/verify-otp",
            data={
                "phone_number": "+14155591030",
                "otp_code": "000000",
                "referral_code": bad_code,
            },
        )
        assert response.status_code == 200
        assert 'name="otp_code"' in response.text
        _assert_not_echoed(response.text, bad_code)


    async def test_resubmit_after_malformed_code_never_422s(
        self, client: AsyncClient
    ):
        # The invalid-code state re-renders the form with an empty hidden
        # referral_code; submitting that form again (request-otp) or the
        # OTP form (verify-otp) must land in the invalid-code state, not a
        # 422 for a "missing" required field.
        first = await client.post(
            "/htmx/referrals/request-otp",
            data={"phone_number": "+14155591060", "referral_code": "../x"},
        )
        assert 'name="referral_code" value=""' in first.text

        again = await client.post(
            "/htmx/referrals/request-otp",
            data={"phone_number": "+14155591060", "referral_code": ""},
        )
        assert again.status_code == 200
        assert "Invalid referral code" in again.text

        verify = await client.post(
            "/htmx/referrals/verify-otp",
            data={
                "phone_number": "+14155591061",
                "otp_code": "000000",
                "referral_code": "",
            },
        )
        assert verify.status_code == 200
        assert 'name="otp_code"' in verify.text

@pytest.mark.asyncio
class TestReferralCodeNormalisationParity:
    """A valid code still works end to end — normalised (strip + upper),
    and carried through an OTP-failure retry."""

    async def test_verify_otp_failure_carries_normalised_valid_code(
        self, client: AsyncClient
    ):
        response = await client.post(
            "/htmx/referrals/verify-otp",
            data={
                "phone_number": "+14155591040",
                "otp_code": "000000",
                "referral_code": " goodcod1 ",
            },
        )
        assert response.status_code == 200
        assert 'name="referral_code" value="GOODCOD1"' in response.text
        match = re.search(r"hx-vals='([^']*)'", response.text)
        assert match
        assert json.loads(html.unescape(match.group(1)))["referral_code"] == "GOODCOD1"

    async def test_claim_from_invite_applies_lowercase_valid_code(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.core.security import create_access_token
        from app.models.subscription import Referral

        referrer = await create_test_user(
            db_session, phone_number="+14155591050", share_code="PARITY01"
        )
        user = await create_test_user(db_session, phone_number="+14155591051")
        response = await client.post(
            "/htmx/referrals/claim-from-invite",
            data={"referral_code": " parity01 "},
            cookies={"access_token": create_access_token(str(user.id))},
        )
        assert response.status_code == 200
        assert "You got 30 days free!" in response.text
        referral = (
            await db_session.execute(
                select(Referral).where(Referral.referee_user_id == user.id)
            )
        ).scalar_one()
        assert referral.referrer_user_id == referrer.id
        assert referral.referral_code == "PARITY01"
