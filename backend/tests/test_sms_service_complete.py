"""Complete test coverage for SMS service."""

from unittest.mock import MagicMock, patch

import pytest
from twilio.base.exceptions import TwilioException

from app.services.sms import SMSService


@pytest.mark.asyncio
class TestSMSServiceComplete:
    """Complete test coverage for SMS service."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings for testing."""
        with patch("app.services.sms.settings") as mock:
            mock.TWILIO_ACCOUNT_SID = "test_sid"
            mock.TWILIO_AUTH_TOKEN = "test_token"
            mock.TWILIO_PHONE_NUMBER = "+12065551234"
            mock.ENVIRONMENT = "production"
            mock.BASE_URL = "https://madeitho.me"
            # Failover wiring — SNS (unconfigured) so the factory works.
            mock.SMS_FAILOVER_PROVIDER = "sns"
            mock.AWS_SNS_REGION = ""
            mock.AWS_SNS_SENDER_ID = ""
            yield mock

    @pytest.fixture
    def mock_twilio_client(self):
        """Mock Twilio client."""
        with patch("app.services.sms.Client") as mock_client:
            client_instance = MagicMock()
            mock_client.return_value = client_instance
            yield client_instance

    @pytest.fixture
    def sms_service_with_client(self, mock_settings, mock_twilio_client):
        """Create SMS service with mocked Twilio client."""
        service = SMSService()
        service.twilio.client = mock_twilio_client
        # Expose the underlying twilio client as `service.client` for legacy assertions
        service.client = mock_twilio_client  # type: ignore[attr-defined]
        return service

    @pytest.fixture
    def sms_service_without_client(self):
        """Create SMS service without any backend configured."""
        service = SMSService()
        service.twilio.client = None
        # `failover` is the active failover backend (SNS).
        service.failover.client = None
        return service

    def test_init_with_valid_credentials(self, mock_settings, mock_twilio_client):
        """Twilio client gets initialized when valid credentials present."""
        service = SMSService()
        assert service.twilio.client is not None

    def test_init_with_placeholder_credentials(self):
        """Placeholder credentials are treated as unconfigured."""
        with patch("app.services.sms.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = "your-account-sid"
            mock_settings.TWILIO_AUTH_TOKEN = "your-auth-token"
            mock_settings.AWS_SNS_REGION = ""
            mock_settings.AWS_SNS_SENDER_ID = ""
            mock_settings.SMS_FAILOVER_PROVIDER = "sns"
            service = SMSService()
            assert service.twilio.client is None

    def test_init_with_no_credentials(self):
        """Empty credentials → no Twilio client."""
        with patch("app.services.sms.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = None
            mock_settings.TWILIO_AUTH_TOKEN = None
            mock_settings.AWS_SNS_REGION = ""
            mock_settings.AWS_SNS_SENDER_ID = ""
            mock_settings.SMS_FAILOVER_PROVIDER = "sns"
            service = SMSService()
            assert service.twilio.client is None

    def test_init_with_client_error(self, mock_settings):
        """Twilio client creation failure leaves client unset."""
        with patch(
            "app.services.sms.Client", side_effect=Exception("Connection failed")
        ):
            service = SMSService()
            assert service.twilio.client is None

    async def test_send_sms_success(self, sms_service_with_client, mock_settings):
        """Test simple SMS sending."""
        mock_message = MagicMock()
        mock_message.sid = "MSG999"
        sms_service_with_client.client.messages.create.return_value = mock_message

        result = await sms_service_with_client.send_sms(
            to_phone="+14155552671", message="Test message"
        )

        assert result.success is True
        sms_service_with_client.client.messages.create.assert_called_once()

    async def test_send_sms_no_client(self, sms_service_without_client):
        """Test SMS without client (dev mode)."""
        result = await sms_service_without_client.send_sms(
            to_phone="+14155552671", message="Test message"
        )

        # In dev mode, it returns success
        assert result.success is True

    async def test_send_sms_twilio_error(self, sms_service_with_client):
        """Test SMS with Twilio error."""
        sms_service_with_client.client.messages.create.side_effect = TwilioException(
            "Failed"
        )

        result = await sms_service_with_client.send_sms(
            to_phone="+14155552671", message="Test"
        )

        assert result.success is False

