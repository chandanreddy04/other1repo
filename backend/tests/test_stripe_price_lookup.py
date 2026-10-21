"""Tests for get_stripe_price_id plan-type lookup."""

from unittest.mock import patch

import pytest

from app.models.subscription import PlanType
from app.services.stripe_service import get_stripe_price_id


class TestGetStripePriceId:
    @patch("app.services.stripe_service.settings")
    def test_monthly(self, mock_settings):
        mock_settings.STRIPE_PRICE_ID_MONTHLY = "price_monthly"
        mock_settings.STRIPE_PRICE_ID_ANNUAL = ""
        mock_settings.STRIPE_PRICE_ID_GROUP_MONTHLY = ""
        mock_settings.STRIPE_PRICE_ID_GROUP_ANNUAL = ""
        assert get_stripe_price_id(PlanType.MONTHLY) == "price_monthly"

    @patch("app.services.stripe_service.settings")
    def test_annual(self, mock_settings):
        mock_settings.STRIPE_PRICE_ID_MONTHLY = ""
        mock_settings.STRIPE_PRICE_ID_ANNUAL = "price_annual"
        mock_settings.STRIPE_PRICE_ID_GROUP_MONTHLY = ""
        mock_settings.STRIPE_PRICE_ID_GROUP_ANNUAL = ""
        assert get_stripe_price_id(PlanType.ANNUAL) == "price_annual"

    @patch("app.services.stripe_service.settings")
    def test_group_monthly(self, mock_settings):
        mock_settings.STRIPE_PRICE_ID_MONTHLY = ""
        mock_settings.STRIPE_PRICE_ID_ANNUAL = ""
        mock_settings.STRIPE_PRICE_ID_GROUP_MONTHLY = "price_fam_mo"
        mock_settings.STRIPE_PRICE_ID_GROUP_ANNUAL = ""
        assert get_stripe_price_id(PlanType.GROUP_MONTHLY) == "price_fam_mo"

    @patch("app.services.stripe_service.settings")
    def test_group_annual(self, mock_settings):
        mock_settings.STRIPE_PRICE_ID_MONTHLY = ""
        mock_settings.STRIPE_PRICE_ID_ANNUAL = ""
        mock_settings.STRIPE_PRICE_ID_GROUP_MONTHLY = ""
        mock_settings.STRIPE_PRICE_ID_GROUP_ANNUAL = "price_fam_yr"
        assert get_stripe_price_id(PlanType.GROUP_ANNUAL) == "price_fam_yr"

    @patch("app.services.stripe_service.settings")
    def test_unconfigured_raises(self, mock_settings):
        mock_settings.STRIPE_PRICE_ID_MONTHLY = ""
        mock_settings.STRIPE_PRICE_ID_ANNUAL = ""
        mock_settings.STRIPE_PRICE_ID_GROUP_MONTHLY = ""
        mock_settings.STRIPE_PRICE_ID_GROUP_ANNUAL = ""
        with pytest.raises(ValueError, match="No Stripe price ID configured"):
            get_stripe_price_id(PlanType.MONTHLY)
