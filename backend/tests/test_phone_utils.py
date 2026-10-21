"""Test phone number utilities."""

from app.utils.phone import format_to_e164


class TestPhoneUtils:
    """Test phone number utility functions."""

    def test_format_to_e164_with_us_number(self):
        """Test formatting US number to E164."""
        # With country code
        assert format_to_e164("+14155552671") == "+14155552671"

        # Without country code (US default)
        assert format_to_e164("4155552671") == "+14155552671"
        assert format_to_e164("(415) 555-2671") == "+14155552671"
        assert format_to_e164("415-555-2671") == "+14155552671"
        assert format_to_e164("415.555.2671") == "+14155552671"

    def test_format_to_e164_invalid_number(self):
        """Test formatting invalid numbers returns None."""
        assert format_to_e164("123") is None
        assert format_to_e164("invalid") is None
        assert format_to_e164("") is None
        assert format_to_e164("555-CALL-NOW") is None

        # Invalid but looks like a number
        assert format_to_e164("1234567890123456789") is None

    def test_format_various_input_formats(self):
        """Test various input formats are handled correctly."""
        test_cases = [
            ("415.555.2671", "+14155552671"),
            ("415 555 2671", "+14155552671"),
            ("(415)5552671", "+14155552671"),
            ("1-415-555-2671", "+14155552671"),
            ("+1-415-555-2671", "+14155552671"),
        ]

        for input_num, expected in test_cases:
            result = format_to_e164(input_num)
            assert result == expected, f"Failed for input: {input_num}"

    def test_edge_cases(self):
        """Test edge cases for phone utilities."""
        # Number with extension (not supported)
        # Note: phonenumbers may parse this but ignore the extension
        result = format_to_e164("+14155552671x123")
        assert result is None or result == "+14155552671"

        # Toll-free numbers
        assert format_to_e164("+18005551234") == "+18005551234"
