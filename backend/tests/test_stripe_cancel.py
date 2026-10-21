"""Tests for the cancel_subscription_at_period_end helper."""

from unittest.mock import patch

import pytest
import stripe

from app.services.stripe_service import cancel_subscription_at_period_end


class TestCancelAtPeriodEnd:
    @patch("app.services.stripe_service.stripe.Subscription.modify")
    def test_flips_cancel_at_period_end_flag(self, mock_modify):
        cancel_subscription_at_period_end("sub_abc123")

        mock_modify.assert_called_once_with(
            "sub_abc123", cancel_at_period_end=True
        )

    @patch("app.services.stripe_service.stripe.Subscription.modify")
    def test_propagates_stripe_error(self, mock_modify):
        """Callers must be able to react to Stripe failures (e.g. log + skip
        for the deletion orchestrator, retry for a bulk job)."""
        mock_modify.side_effect = stripe.StripeError("Stripe down")

        with pytest.raises(stripe.StripeError):
            cancel_subscription_at_period_end("sub_abc123")
