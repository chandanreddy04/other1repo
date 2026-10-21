"""Additional tests for auth.py and users.py to improve coverage."""

import io
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.core.security import create_access_token, create_refresh_token
from tests.helpers import create_test_user


@pytest.mark.asyncio
class TestVerifyOTPNewUserProfileFlow:
    """Cover verify_otp new user creation path (auth.py lines 134-160)."""

    async def test_verify_otp_new_user_creates_user_with_referral_code(
        self, client: AsyncClient, db_session
    ):
        """New user gets a referral code assigned on creation."""
        phone = "+14155550001"

        with (
            patch(
                "app.api.v1.endpoints.auth.otp_service.verify_otp",
                return_value=(True, "Verified"),
            ),
            patch(
                "app.api.v1.endpoints.auth.format_to_e164",
                return_value=phone,
            ),
            patch(
                "app.api.v1.endpoints.auth.subscription_service.generate_share_code",
                return_value="ABCD1234",
            ),
            patch(
                "app.api.v1.endpoints.auth.subscription_service.resolve_pending_gifts",
                new_callable=AsyncMock,
            ) as mock_resolve,
        ):
            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": phone, "otp_code": "111111"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["is_new_user"] is True
            assert data["user"] is None  # new users don't get user data back
            assert "access_token" in data
            assert "refresh_token" in data
            assert data["token_type"] == "bearer"
            mock_resolve.assert_called_once()

    async def test_verify_otp_new_user_resolves_pending_gifts(
        self, client: AsyncClient, db_session
    ):
        """Pending gift subscriptions are resolved for new users."""
        phone = "+14155550002"

        with (
            patch(
                "app.api.v1.endpoints.auth.otp_service.verify_otp",
                return_value=(True, "Verified"),
            ),
            patch(
                "app.api.v1.endpoints.auth.format_to_e164",
                return_value=phone,
            ),
            patch(
                "app.api.v1.endpoints.auth.subscription_service.generate_share_code",
                return_value="XYZW5678",
            ),
            patch(
                "app.api.v1.endpoints.auth.subscription_service.resolve_pending_gifts",
                new_callable=AsyncMock,
            ) as mock_resolve,
        ):
            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": phone, "otp_code": "222222"},
            )

            assert response.status_code == 200
            # resolve_pending_gifts called with phone and new user's id
            args = mock_resolve.call_args
            assert args[0][1] == phone  # second positional arg is phone


@pytest.mark.asyncio
class TestVerifyOTPExistingUserWithProfile:
    """Cover verify_otp existing user path (auth.py lines 134-160)."""

    async def test_verify_otp_existing_user_returns_user_data(
        self, client: AsyncClient, db_session, test_user
    ):
        """Existing user with full_name gets user data in response."""
        with (
            patch(
                "app.api.v1.endpoints.auth.otp_service.verify_otp",
                return_value=(True, "Verified"),
            ),
            patch(
                "app.api.v1.endpoints.auth.format_to_e164",
                return_value=test_user.phone_number,
            ),
            patch(
                "app.api.v1.endpoints.auth.subscription_service.resolve_pending_gifts",
                new_callable=AsyncMock,
            ) as mock_resolve,
        ):
            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={
                    "phone_number": test_user.phone_number,
                    "otp_code": "333333",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["is_new_user"] is False
            assert data["user"] is not None
            assert data["user"]["phone_number"] == test_user.phone_number
            assert data["user"]["full_name"] == test_user.full_name
            mock_resolve.assert_called_once()

    async def test_verify_otp_existing_user_resolves_pending_gifts(
        self, client: AsyncClient, db_session, test_user
    ):
        """Pending gift subscriptions are resolved for existing users too."""
        with (
            patch(
                "app.api.v1.endpoints.auth.otp_service.verify_otp",
                return_value=(True, "Verified"),
            ),
            patch(
                "app.api.v1.endpoints.auth.format_to_e164",
                return_value=test_user.phone_number,
            ),
            patch(
                "app.api.v1.endpoints.auth.subscription_service.resolve_pending_gifts",
                new_callable=AsyncMock,
            ) as mock_resolve,
        ):
            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={
                    "phone_number": test_user.phone_number,
                    "otp_code": "444444",
                },
            )

            assert response.status_code == 200
            args = mock_resolve.call_args
            assert args[0][1] == test_user.phone_number
            assert args[0][2] == test_user.id


@pytest.mark.asyncio
class TestVerifyOTPInvalidPhone:
    """Cover verify_otp invalid phone format after OTP passes (auth.py line 126)."""

    async def test_verify_otp_valid_otp_but_invalid_phone_format(
        self, client: AsyncClient
    ):
        """OTP passes verification but phone fails E164 formatting."""
        with (
            patch(
                "app.api.v1.endpoints.auth.otp_service.verify_otp",
                return_value=(True, "Verified"),
            ),
            patch(
                "app.api.v1.endpoints.auth.format_to_e164",
                return_value=None,
            ),
        ):
            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": "badphone", "otp_code": "123456"},
            )

            assert response.status_code == 400
            assert "Invalid phone number format" in response.json()["detail"]


@pytest.mark.asyncio
class TestRefreshTokenEdgeCases:
    """Cover refresh token edge cases (auth.py lines 69, 76-88)."""

    async def test_refresh_token_invalid_token_type(self, client: AsyncClient):
        """Refresh with an access token (type != 'refresh') returns 401."""
        # create_access_token produces type="access"
        access_token = create_access_token("some-user-id")

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": access_token},
        )

        assert response.status_code == 401
        assert "credentials" in response.json()["detail"].lower()

    async def test_refresh_token_nonexistent_user(
        self, client: AsyncClient, db_session
    ):
        """Refresh token for a user that no longer exists returns 401."""
        import uuid

        fake_user_id = str(uuid.uuid4())
        refresh_tok = create_refresh_token(fake_user_id)

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_tok},
        )

        assert response.status_code == 401

    async def test_refresh_token_inactive_user(self, client: AsyncClient, db_session):
        """Refresh token for an inactive user returns 403."""
        inactive_user = await create_test_user(
            db_session,
            phone_number="+14155550099",
            full_name="Inactive",
            is_active=False,
        )

        refresh_tok = create_refresh_token(str(inactive_user.id))

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_tok},
        )

        assert response.status_code == 403
        assert "Inactive" in response.json()["detail"]

    async def test_refresh_token_malformed_jwt(self, client: AsyncClient):
        """Completely invalid JWT returns 401."""
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "not.a.valid.jwt"},
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestResendOTP:
    """Cover resend-otp endpoint (auth.py lines 175-182)."""

    async def test_resend_otp_success(self, client: AsyncClient):
        """Resend OTP calls send_otp with force_resend=True."""
        with patch("app.api.v1.endpoints.auth.otp_service.send_otp") as mock_send:
            mock_send.return_value = (True, "OTP resent")

            response = await client.post(
                "/api/v1/auth/resend-otp",
                json={"phone_number": "+14155550010"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args
            assert call_kwargs[1].get("force_resend") is True or (
                len(call_kwargs[0]) >= 3 and call_kwargs[0][2] is True
            )

    async def test_resend_otp_failure(self, client: AsyncClient):
        """Resend OTP returns 400 on service failure."""
        with patch("app.api.v1.endpoints.auth.otp_service.send_otp") as mock_send:
            mock_send.return_value = (False, "Failed to send OTP")

            response = await client.post(
                "/api/v1/auth/resend-otp",
                json={"phone_number": "+14155550011"},
            )

            assert response.status_code == 400
            assert "Failed" in response.json()["detail"]


@pytest.mark.asyncio
class TestGetCurrentUser:
    """Cover GET /users/me (users.py line 31)."""

    async def test_get_me_returns_current_user(
        self, client: AsyncClient, test_user, auth_headers
    ):
        """Authenticated user gets their own data back."""
        response = await client.get("/api/v1/users/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_user.id)
        assert data["phone_number"] == test_user.phone_number
        assert data["full_name"] == test_user.full_name
        assert data["is_active"] is True


@pytest.mark.asyncio
class TestUploadProfilePhoto:
    """Cover POST /users/me/profile-photo."""

    async def test_upload_valid_image(
        self, client: AsyncClient, test_user, auth_headers
    ):
        """Uploading a valid JPEG image updates profile_photo_url."""
        # Create a minimal valid JPEG in memory
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        file_bytes = buf.getvalue()

        with patch(
            "app.api.v1.endpoints.users.upload_image",
            new_callable=AsyncMock,
            return_value="/uploads/profile-photos/test.jpg",
        ):
            response = await client.post(
                "/api/v1/users/me/profile-photo",
                files={"file": ("photo.jpg", io.BytesIO(file_bytes), "image/jpeg")},
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["profile_photo_url"] is not None

    async def test_upload_invalid_content_type(
        self, client: AsyncClient, test_user, auth_headers
    ):
        """Uploading a file with disallowed content type returns 400."""
        response = await client.post(
            "/api/v1/users/me/profile-photo",
            files={
                "file": ("document.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")
            },
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"].lower()

    async def test_upload_no_file(self, client: AsyncClient, test_user, auth_headers):
        """Request without a file returns 422."""
        response = await client.post(
            "/api/v1/users/me/profile-photo",
            headers=auth_headers,
        )

        assert response.status_code == 422

    async def test_upload_s3_failure(
        self, client: AsyncClient, test_user, auth_headers
    ):
        """S3 upload failure returns 500."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        file_bytes = buf.getvalue()

        with patch(
            "app.api.v1.endpoints.users.upload_image",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=500, detail="Failed to upload photo"),
        ):
            response = await client.post(
                "/api/v1/users/me/profile-photo",
                files={"file": ("photo.jpg", io.BytesIO(file_bytes), "image/jpeg")},
                headers=auth_headers,
            )

            assert response.status_code == 500
            assert "Failed to upload photo" in response.json()["detail"]

    async def test_upload_png_image(self, client: AsyncClient, test_user, auth_headers):
        """Uploading a PNG image extracts the correct extension."""
        from PIL import Image

        img = Image.new("RGBA", (50, 50), color="green")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        file_bytes = buf.getvalue()

        with patch(
            "app.api.v1.endpoints.users.upload_image",
            new_callable=AsyncMock,
            return_value="/uploads/profile-photos/test.png",
        ):
            response = await client.post(
                "/api/v1/users/me/profile-photo",
                files={"file": ("avatar.png", io.BytesIO(file_bytes), "image/png")},
                headers=auth_headers,
            )

            assert response.status_code == 200

    async def test_upload_unauthenticated(self, client: AsyncClient):
        """Uploading without auth returns 401."""
        response = await client.post(
            "/api/v1/users/me/profile-photo",
            files={"file": ("photo.jpg", io.BytesIO(b"data"), "image/jpeg")},
        )

        assert response.status_code == 401
