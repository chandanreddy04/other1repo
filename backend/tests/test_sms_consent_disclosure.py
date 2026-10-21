"""Twilio A2P 10DLC consent-disclosure rendering tests.

Every public web surface that collects a phone number for SMS must render the
explicit opt-in consent form (`fragments/sms_consent.html`): an unchecked,
`required` consent checkbox plus the message-type / frequency / data-rate /
HELP-STOP disclosures and Terms/Privacy links.

Related: backend/app/web/templates/fragments/sms_consent.html,
mobile/constants/config.ts (SMS_CONSENT_COPY), docs/twilio-a2p-consent.md.
"""

import pytest
from httpx import AsyncClient

# Substrings that together prove all required Twilio consent elements are
# present. Ampersands render HTML-escaped in the response, so match around them.
REQUIRED_DISCLOSURE_PHRASES = [
    'name="sms_consent"',  # the consent checkbox field
    "required",  # checkbox is hard-gated (must be actively checked)
    "I agree to receive automated text messages",  # explicit opt-in language
    "Message frequency varies",  # frequency disclosure
    "data rates may apply",  # message & data rates disclaimer
    "Text HELP for assistance with the app or STOP to cancel",  # HELP/STOP instructions
    "never sell your number",  # no-sell / no-spam promise
    "/terms",  # Terms link
    "/privacy",  # Privacy Policy link
]


def _assert_consent_rendered(html: str) -> None:
    for phrase in REQUIRED_DISCLOSURE_PHRASES:
        assert phrase in html, f"consent disclosure missing: {phrase!r}"
    # The opt-in must NOT be pre-checked.
    assert "checkbox" in html
    assert 'name="sms_consent" checked' not in html
    assert "checked>" not in html


class TestConsentDisclosureRendered:
    async def test_login_page_renders_consent(self, client: AsyncClient):
        """The primary public phone-entry surface renders the full disclosure."""
        response = await client.get("/login")
        assert response.status_code == 200
        _assert_consent_rendered(response.text)


@pytest.mark.parametrize(
    "fragment",
    [
        "fragments/auth_form.html",
        "fragments/sponsorship_auth_form.html",
        "fragments/referral_auth_form.html",
        # fragments/phone_form.html was an orphan (no route/template
        # rendered it) and was deleted 2026-09-23 with the other backend
        # marketing-page templates — see test_removed_feature_tombstones.py.
    ],
)
def test_phone_forms_include_consent_partial(fragment: str):
    """Each phone-entry form must include the shared consent partial so the
    disclosure can never be dropped from one surface by accident."""
    from pathlib import Path

    template_dir = Path(__file__).resolve().parent.parent / "app" / "web" / "templates"
    contents = (template_dir / fragment).read_text()
    assert "fragments/sms_consent.html" in contents, (
        f"{fragment} does not include the SMS consent partial"
    )
