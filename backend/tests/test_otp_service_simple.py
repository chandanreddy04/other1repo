"""Simple OTP service tests that actually work."""

from app.services.otp import OTPService


class TestOTPServiceSimple:
    """Simple tests for OTP service."""

    def test_generate_otp_code(self):
        """Test OTP code generation."""
        service = OTPService()
        code = service.generate_otp_code()

        # Should be 6 digits
        assert len(code) == 6
        assert code.isdigit()

    def test_generate_unique_codes(self):
        """Test that OTP codes are reasonably unique."""
        service = OTPService()
        codes = set()

        for _ in range(100):
            code = service.generate_otp_code()
            codes.add(code)

        # Should generate mostly unique codes
        assert len(codes) > 90  # At least 90% unique

    def test_format_phone_number(self):
        """Test phone number formatting."""
        from app.utils.phone import format_to_e164

        # US number
        assert format_to_e164("(415) 555-2671", "US") == "+14155552671"
        assert format_to_e164("4155552671", "US") == "+14155552671"
        assert format_to_e164("+14155552671", "US") == "+14155552671"
