"""Test auth endpoints with high coverage."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
class TestAuthEndpoints:
    """Test authentication endpoints."""

    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = MagicMock(spec=User)
        user.id = "user-123"
        user.phone_number = "+14155552671"
        user.full_name = "Test User"
        user.is_active = True
        return user

    async def test_request_otp_success(self, client: AsyncClient):
        """Test requesting OTP successfully."""
        with patch("app.api.v1.endpoints.auth.otp_service.send_otp") as mock_send:
            mock_send.return_value = (True, "OTP sent successfully")

            response = await client.post(
                "/api/v1/auth/request-otp", json={"phone_number": "+14155552671"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "sent" in data["message"].lower()
            mock_send.assert_called_once()

    async def test_request_otp_invalid_phone(self, client: AsyncClient):
        """Test requesting OTP with invalid phone."""
        with patch("app.api.v1.endpoints.auth.format_to_e164") as mock_format:
            mock_format.return_value = None

            response = await client.post(
                "/api/v1/auth/request-otp", json={"phone_number": "invalid"}
            )

            assert response.status_code == 400
            assert "Invalid phone number" in response.json()["detail"]

    async def test_request_otp_rejected_for_opted_out_phone(
        self, client: AsyncClient, db_session
    ):
        """Phone that previously texted STOP gets a structured 400 with
        `code: phone_opted_out` so mobile can render the START recovery
        flow rather than a generic delivery failure."""
        from app.services import sms_opt_out
        from tests.helpers import create_test_user

        await create_test_user(db_session, phone_number="+14155558899")
        await sms_opt_out.record_opt_out(db_session, "+14155558899")

        with patch("app.api.v1.endpoints.auth.otp_service.send_otp") as mock_send:
            response = await client.post(
                "/api/v1/auth/request-otp",
                json={"phone_number": "+14155558899"},
            )

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["code"] == "phone_opted_out"
        assert "support_number" in detail
        mock_send.assert_not_called()

    async def test_request_otp_per_ip_rate_limit_blocks_enumeration(
        self, client: AsyncClient, monkeypatch
    ):
        """A single client (IP) can request OTP for at most 5 phones per
        minute. Without this cap, the timing difference between the
        phone_opted_out early-return and the full send path would let
        an attacker enumerate opted-out numbers by iterating phones."""
        from app.core.rate_limit import limiter

        # Limiter is disabled in test env by default — turn it on for
        # this test so we actually exercise the cap.
        monkeypatch.setattr(limiter, "enabled", True)
        limiter.reset()
        try:
            with patch(
                "app.api.v1.endpoints.auth.otp_service.send_otp"
            ) as mock_send:
                mock_send.return_value = (True, "ok")
                # 5 distinct probes succeed.
                for i in range(5):
                    response = await client.post(
                        "/api/v1/auth/request-otp",
                        json={"phone_number": f"+14155560{i:03}"},
                    )
                    assert response.status_code == 200, (
                        f"probe {i} unexpectedly rate-limited"
                    )
                # 6th probe is capped — even though it's a new phone, the
                # same IP just made 5 requests.
                response = await client.post(
                    "/api/v1/auth/request-otp",
                    json={"phone_number": "+14155560006"},
                )
                assert response.status_code == 429
        finally:
            limiter.reset()

    async def test_request_otp_opt_in_unblocks_after_start(
        self, client: AsyncClient, db_session
    ):
        """Once START clears the opt-out, OTP send works again."""
        from app.services import sms_opt_out
        from tests.helpers import create_test_user

        await create_test_user(db_session, phone_number="+14155558800")
        await sms_opt_out.record_opt_out(db_session, "+14155558800")
        await sms_opt_out.record_opt_in(db_session, "+14155558800")

        with patch("app.api.v1.endpoints.auth.otp_service.send_otp") as mock_send:
            mock_send.return_value = (True, "OTP sent successfully")
            response = await client.post(
                "/api/v1/auth/request-otp",
                json={"phone_number": "+14155558800"},
            )

        assert response.status_code == 200
        mock_send.assert_called_once()

    async def test_request_otp_rate_limited(self, client: AsyncClient):
        """Test OTP rate limiting returns 429 with retry_after."""
        with (
            patch("app.api.v1.endpoints.auth.otp_service.send_otp") as mock_send,
            patch(
                "app.api.v1.endpoints.auth.otp_service.get_resend_wait_seconds"
            ) as mock_wait,
        ):
            mock_send.return_value = (
                False,
                "Please wait 30 seconds before requesting a new code",
            )
            mock_wait.return_value = 30

            response = await client.post(
                "/api/v1/auth/request-otp", json={"phone_number": "+14155552671"}
            )

            assert response.status_code == 429
            body = response.json()
            assert body["detail"]["retry_after"] == 30
            assert "wait" in body["detail"]["message"].lower()

    async def test_verify_otp_success_new_user(self, client: AsyncClient):
        """Test OTP verification for new user."""
        with patch("app.api.v1.endpoints.auth.otp_service.verify_otp") as mock_verify:
            mock_verify.return_value = (True, "Verified successfully")

            with patch("app.api.v1.endpoints.auth.format_to_e164") as mock_format:
                mock_format.return_value = "+14155552671"

                response = await client.post(
                    "/api/v1/auth/verify-otp",
                    json={"phone_number": "+14155552671", "otp_code": "123456"},
                )

                assert response.status_code == 200
                data = response.json()
                assert "access_token" in data
                assert data["token_type"] == "bearer"
                assert data["is_new_user"] is True

    async def test_verify_otp_success_existing_user(
        self, client: AsyncClient, db_session, test_user
    ):
        """Test OTP verification for existing user."""
        # test_user fixture creates a user with phone +1234567890
        with patch("app.api.v1.endpoints.auth.otp_service.verify_otp") as mock_verify:
            mock_verify.return_value = (True, "Verified successfully")

            with patch("app.api.v1.endpoints.auth.format_to_e164") as mock_format:
                mock_format.return_value = test_user.phone_number

                response = await client.post(
                    "/api/v1/auth/verify-otp",
                    json={"phone_number": test_user.phone_number, "otp_code": "123456"},
                )

                assert response.status_code == 200
                data = response.json()
                assert "access_token" in data
                assert data["is_new_user"] is False

    async def test_verify_otp_invalid_code(self, client: AsyncClient):
        """Test OTP verification with invalid code."""
        with patch("app.api.v1.endpoints.auth.otp_service.verify_otp") as mock_verify:
            mock_verify.return_value = (False, "Invalid code")

            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": "+14155552671", "otp_code": "999999"},
            )

            assert response.status_code == 400
            assert "Invalid" in response.json()["detail"]

    async def test_verify_otp_expired(self, client: AsyncClient):
        """Test OTP verification with expired code."""
        with patch("app.api.v1.endpoints.auth.otp_service.verify_otp") as mock_verify:
            mock_verify.return_value = (False, "OTP has expired")

            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": "+14155552671", "otp_code": "123456"},
            )

            assert response.status_code == 400
            assert "expired" in response.json()["detail"].lower()

    async def test_verify_otp_invalid_phone_format(self, client: AsyncClient):
        """Test OTP verification with invalid phone format."""
        with patch("app.api.v1.endpoints.auth.format_to_e164") as mock_format:
            mock_format.return_value = None

            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": "invalid", "otp_code": "123456"},
            )

            assert response.status_code == 400
            assert "Invalid phone" in response.json()["detail"]

    async def test_verify_otp_too_many_attempts(self, client: AsyncClient):
        """Test OTP verification with too many attempts."""
        with patch("app.api.v1.endpoints.auth.otp_service.verify_otp") as mock_verify:
            mock_verify.return_value = (
                False,
                "Too many attempts. Please request a new code.",
            )

            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": "+14155552671", "otp_code": "123456"},
            )

            assert response.status_code == 400
            assert "attempts" in response.json()["detail"].lower()

    async def test_refresh_token_success(self, client: AsyncClient, test_user):
        """Test token refresh."""
        from app.core.security import create_refresh_token

        refresh_token = create_refresh_token(str(test_user.id))

        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_verify_otp_service_error(self, client: AsyncClient):
        """Test OTP verification with service error."""
        with patch("app.api.v1.endpoints.auth.otp_service.verify_otp") as mock_verify:
            # OTP service catches exceptions and returns False with error message
            mock_verify.return_value = (False, "An error occurred during verification")

            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": "+14155552671", "otp_code": "123456"},
            )

            # Service errors return 400 with the error message
            assert response.status_code == 400
            assert "error occurred" in response.json()["detail"].lower()
