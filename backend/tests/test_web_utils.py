"""Tests for web/utils.py — phone display and auth cookie."""

from unittest.mock import MagicMock

from app.web.utils import get_phone_display_value, set_auth_cookie


class TestGetPhoneDisplayValue:
    def test_us_e164(self):
        assert get_phone_display_value("+14155551234") == "4155551234"

    def test_us_without_plus(self):
        assert get_phone_display_value("14155551234") == "4155551234"

    def test_non_us(self):
        assert get_phone_display_value("+447911123456") == "+447911123456"

    def test_plain_number(self):
        assert get_phone_display_value("5551234") == "5551234"


class TestSetAuthCookie:
    def test_sets_cookie_with_defaults(self):
        response = MagicMock()
        set_auth_cookie(response, "tok123")
        response.set_cookie.assert_called_once_with(
            key="access_token",
            value="tok123",
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=604800,
        )

    def test_custom_max_age(self):
        response = MagicMock()
        set_auth_cookie(response, "tok456", max_age=3600)
        response.set_cookie.assert_called_once()
        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["max_age"] == 3600
