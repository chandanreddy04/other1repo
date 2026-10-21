"""Stripe checkout/portal URLs point at the merged native plan/subscription
routes (2026-09-23 owner decision — one plans page, one subscription page).

Success/cancel land on `/plans` with a `checkout` query param (`success` /
`canceled`) instead of the old dedicated `/subscribed` and `/subscribe`
screens; the portal's default return lands on `/subscription` instead of
`/account`. All three are built on SHORT_DOMAIN (the short-link host the app
claims as a universal link / app link — `CLAIMED_APP_PATHS` in
app/web/short_links.py), NOT APP_DOMAIN, which the app doesn't claim. A
return MAY hand back to the app; the confirming step's foreground re-check
is the reliable path. Without the app, the browser gets the store/marketing
fallback (tests/test_app_path_fallbacks.py).

Related: app/services/stripe_service.py, app/plans.tsx, app/subscription.tsx.
"""

from unittest.mock import MagicMock, patch

from app.models.subscription import PlanType
from app.services.stripe_service import (
    create_day_pass_checkout_session,
    create_portal_session,
    create_subscription_checkout_session,
)


class TestSubscriptionCheckoutUrls:
    @patch("app.services.stripe_service.stripe.checkout.Session.create")
    @patch("app.services.stripe_service.settings")
    def test_success_and_cancel_urls(self, mock_settings, mock_create):
        mock_settings.SHORT_DOMAIN = "https://s.example.com"
        mock_settings.STRIPE_PRICE_ID_MONTHLY = "price_monthly"
        mock_create.return_value = MagicMock()

        create_subscription_checkout_session(
            customer_id="cus_123", plan_type=PlanType.MONTHLY, user_id="user_1"
        )

        kwargs = mock_create.call_args.kwargs
        assert kwargs["success_url"] == (
            "https://s.example.com/plans?checkout=success"
            "&session_id={CHECKOUT_SESSION_ID}"
        )
        assert kwargs["cancel_url"] == "https://s.example.com/plans?checkout=canceled"


class TestDayPassCheckoutUrls:
    @patch("app.services.stripe_service.stripe.checkout.Session.create")
    @patch("app.services.stripe_service.settings")
    def test_success_and_cancel_urls(self, mock_settings, mock_create):
        mock_settings.SHORT_DOMAIN = "https://s.example.com"
        mock_settings.STRIPE_PRICE_ID_DAY_PASS = "price_day_pass"
        mock_create.return_value = MagicMock()

        create_day_pass_checkout_session(customer_id="cus_123", user_id="user_1")

        kwargs = mock_create.call_args.kwargs
        assert kwargs["success_url"] == (
            "https://s.example.com/plans?checkout=success"
            "&session_id={CHECKOUT_SESSION_ID}"
        )
        assert kwargs["cancel_url"] == "https://s.example.com/plans?checkout=canceled"


class TestPortalReturnUrl:
    @patch("app.services.stripe_service.stripe.billing_portal.Session.create")
    @patch("app.services.stripe_service.settings")
    def test_default_return_url_is_subscription(self, mock_settings, mock_create):
        mock_settings.SHORT_DOMAIN = "https://s.example.com"
        mock_create.return_value = MagicMock()

        create_portal_session(customer_id="cus_123")

        kwargs = mock_create.call_args.kwargs
        assert kwargs["return_url"] == "https://s.example.com/subscription"

    @patch("app.services.stripe_service.stripe.billing_portal.Session.create")
    @patch("app.services.stripe_service.settings")
    def test_explicit_return_url_overrides_default(self, mock_settings, mock_create):
        mock_settings.SHORT_DOMAIN = "https://s.example.com"
        mock_create.return_value = MagicMock()

        create_portal_session(
            customer_id="cus_123",
            return_url="https://app.example.com/sponsorships?status=saved",
        )

        kwargs = mock_create.call_args.kwargs
        assert (
            kwargs["return_url"] == "https://app.example.com/sponsorships?status=saved"
        )
