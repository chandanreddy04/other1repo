"""Simple tests for utility functions."""

from app.utils.phone import format_for_display, format_to_e164


class TestPhoneUtils:
    """Test phone utility functions."""

    def test_format_to_e164_us_number(self):
        """Test formatting US number to E164."""
        assert format_to_e164("(415) 555-2671") == "+14155552671"
        assert format_to_e164("415-555-2671") == "+14155552671"
        assert format_to_e164("4155552671") == "+14155552671"
        assert format_to_e164("+14155552671") == "+14155552671"

    def test_format_to_e164_invalid(self):
        """Test formatting invalid numbers."""
        assert format_to_e164("invalid") is None
        assert format_to_e164("123") is None
        assert format_to_e164("") is None

    def test_format_for_display(self):
        """Test formatting phone number for display."""
        assert format_for_display("+14155552671") == "(415) 555-2671"
        assert format_for_display("+12125551234") == "(212) 555-1234"

    def test_format_for_display_invalid(self):
        """Test formatting invalid phone number."""
        assert format_for_display("invalid") == "invalid"
        assert format_for_display("") == ""



class TestImageValidation:
    """Test image validation utilities."""

    def test_image_validation_imports(self):
        """Test that image validation module can be imported."""
        try:
            from app.utils.image_validation import validate_image

            assert validate_image is not None
        except ImportError as err:
            raise AssertionError("Could not import image validation") from err
