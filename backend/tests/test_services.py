"""Unit tests for backend services, utilities, and auth dependencies."""

import io
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from app.core.security import create_access_token
from app.models.session import Session, SessionStatus
from app.services.otp import OTPService
from tests.helpers import create_test_user

# ---------------------------------------------------------------------------
# OTP Service Tests (uses real db_session from conftest)
# ---------------------------------------------------------------------------


class TestOTPServiceSendOTP:
    """Tests for OTPService.send_otp()."""

    @pytest.mark.asyncio
    async def test_send_otp_success(self, db_session):
        service = OTPService()
        success, message = await service.send_otp(db_session, "+14155552671")

        assert success is True
        assert "sent" in message.lower()

        # Verify OTP was saved in the database
        otp = await service.get_active_otp(db_session, "+14155552671")
        assert otp is not None
        assert otp.phone_number == "+14155552671"
        assert len(otp.otp_code) == 6
        assert otp.is_used is False

    @pytest.mark.asyncio
    async def test_send_otp_invalid_phone(self, db_session):
        service = OTPService()
        success, message = await service.send_otp(db_session, "not-a-phone")

        assert success is False
        assert "invalid" in message.lower()

    @pytest.mark.asyncio
    async def test_send_otp_rate_limited(self, db_session):
        service = OTPService()

        # Send first OTP
        success1, _ = await service.send_otp(db_session, "+14155552671")
        assert success1 is True

        # Immediately request another — should be rate limited
        success2, message2 = await service.send_otp(db_session, "+14155552671")
        assert success2 is False
        assert "wait" in message2.lower()

    @pytest.mark.asyncio
    async def test_send_otp_force_resend_bypasses_rate_limit(self, db_session):
        service = OTPService()

        await service.send_otp(db_session, "+14155552671")

        # Force resend should bypass rate limit
        success, message = await service.send_otp(
            db_session, "+14155552671", force_resend=True
        )
        assert success is True
        assert "sent" in message.lower()

    @pytest.mark.asyncio
    async def test_send_otp_expires_old_otps(self, db_session):
        service = OTPService()

        # Send first OTP
        await service.send_otp(db_session, "+14155552671")
        first_otp = await service.get_active_otp(db_session, "+14155552671")
        first_code = first_otp.otp_code

        # Force-send a second OTP (bypasses rate limit)
        await service.send_otp(db_session, "+14155552671", force_resend=True)

        # The first OTP should now be expired (no active OTP with old code)
        await db_session.refresh(first_otp)
        assert first_otp.expires_at <= datetime.now(UTC)

        # Only the new OTP should be active
        active_otp = await service.get_active_otp(db_session, "+14155552671")
        assert active_otp is not None
        assert active_otp.otp_code != first_code


class TestOTPServiceVerifyOTP:
    """Tests for OTPService.verify_otp()."""

    @pytest.mark.asyncio
    async def test_verify_otp_correct_code(self, db_session):
        service = OTPService()
        await service.send_otp(db_session, "+14155552671")

        otp = await service.get_active_otp(db_session, "+14155552671")
        success, message = await service.verify_otp(
            db_session, "+14155552671", otp.otp_code
        )

        assert success is True
        assert "verified" in message.lower()

        await db_session.refresh(otp)
        assert otp.is_verified is True
        assert otp.is_used is True
        assert otp.verified_at is not None

    @pytest.mark.asyncio
    async def test_verify_otp_wrong_code(self, db_session):
        service = OTPService()
        await service.send_otp(db_session, "+14155552671")

        success, message = await service.verify_otp(
            db_session, "+14155552671", "000000"
        )

        assert success is False
        assert "invalid code" in message.lower()
        assert "attempts remaining" in message.lower()

    @pytest.mark.asyncio
    async def test_verify_otp_not_found(self, db_session):
        service = OTPService()

        # No OTP was sent for this number
        success, message = await service.verify_otp(
            db_session, "+14155552671", "123456"
        )

        assert success is False
        assert "invalid or expired" in message.lower()

    @pytest.mark.asyncio
    async def test_verify_otp_expired(self, db_session):
        service = OTPService()
        await service.send_otp(db_session, "+14155552671")

        # Manually expire the OTP
        otp = await service.get_active_otp(db_session, "+14155552671")
        otp.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db_session.commit()

        success, message = await service.verify_otp(
            db_session, "+14155552671", otp.otp_code
        )

        assert success is False
        assert "invalid or expired" in message.lower()

    @pytest.mark.asyncio
    async def test_verify_otp_max_attempts_exceeded(self, db_session):
        service = OTPService()
        await service.send_otp(db_session, "+14155552671")

        otp = await service.get_active_otp(db_session, "+14155552671")

        # Exhaust attempts with wrong codes
        for _ in range(service.max_attempts):
            await service.verify_otp(db_session, "+14155552671", "000000")

        # Next attempt should fail with "too many attempts"
        success, message = await service.verify_otp(
            db_session, "+14155552671", otp.otp_code
        )

        assert success is False
        assert "too many attempts" in message.lower()

    @pytest.mark.asyncio
    async def test_verify_otp_invalid_phone(self, db_session):
        service = OTPService()
        success, message = await service.verify_otp(db_session, "not-a-phone", "123456")

        assert success is False
        assert "invalid" in message.lower()


class TestOTPServiceGetActiveOTP:
    """Tests for OTPService.get_active_otp()."""

    @pytest.mark.asyncio
    async def test_get_active_otp_exists(self, db_session):
        service = OTPService()
        await service.send_otp(db_session, "+14155552671")

        active = await service.get_active_otp(db_session, "+14155552671")
        assert active is not None
        assert active.phone_number == "+14155552671"
        assert active.is_used is False

    @pytest.mark.asyncio
    async def test_get_active_otp_none(self, db_session):
        service = OTPService()

        active = await service.get_active_otp(db_session, "+14155552671")
        assert active is None

    @pytest.mark.asyncio
    async def test_get_active_otp_expired_returns_none(self, db_session):
        service = OTPService()
        await service.send_otp(db_session, "+14155552671")

        otp = await service.get_active_otp(db_session, "+14155552671")
        otp.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db_session.commit()

        active = await service.get_active_otp(db_session, "+14155552671")
        assert active is None


# ---------------------------------------------------------------------------
# Stripe Service Tests (fully mocked, no DB needed)
# ---------------------------------------------------------------------------


class TestStripeService:
    """Tests for stripe_service functions."""

    @patch("app.services.stripe_service.settings")
    @patch("app.services.stripe_service.stripe")
    def test_create_gift_checkout_session_monthly(self, mock_stripe, mock_settings):
        mock_settings.STRIPE_PRICE_ID_MONTHLY = "price_monthly_123"
        mock_settings.STRIPE_PRICE_ID_ANNUAL = "price_annual_456"

        mock_session = MagicMock()
        mock_stripe.checkout.Session.create.return_value = mock_session

        from app.services.stripe_service import create_gift_checkout_session

        result = create_gift_checkout_session(
            recipient_phone="+14155552671",
            plan_type="monthly",
            gifter_phone="+14155552672",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        assert result == mock_session
        mock_stripe.checkout.Session.create.assert_called_once()
        call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
        assert call_kwargs["line_items"] == [
            {"price": "price_monthly_123", "quantity": 1}
        ]
        assert call_kwargs["mode"] == "payment"
        assert call_kwargs["metadata"]["plan_type"] == "monthly"
        assert call_kwargs["metadata"]["recipient_phone"] == "+14155552671"
        assert call_kwargs["metadata"]["gifter_phone"] == "+14155552672"
        assert call_kwargs["metadata"]["type"] == "gift_subscription"

    @patch("app.services.stripe_service.settings")
    @patch("app.services.stripe_service.stripe")
    def test_create_gift_checkout_session_annual(self, mock_stripe, mock_settings):
        mock_settings.STRIPE_PRICE_ID_MONTHLY = "price_monthly_123"
        mock_settings.STRIPE_PRICE_ID_ANNUAL = "price_annual_456"

        mock_session = MagicMock()
        mock_stripe.checkout.Session.create.return_value = mock_session

        from app.services.stripe_service import create_gift_checkout_session

        result = create_gift_checkout_session(
            recipient_phone="+14155552671",
            plan_type="annual",
            gifter_phone="+14155552673",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        assert result == mock_session
        call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
        assert call_kwargs["line_items"] == [
            {"price": "price_annual_456", "quantity": 1}
        ]
        assert call_kwargs["metadata"]["plan_type"] == "annual"

    @patch("app.services.stripe_service.settings")
    @patch("app.services.stripe_service.stripe")
    def test_construct_webhook_event_valid(self, mock_stripe, mock_settings):
        mock_settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
        mock_event = MagicMock()
        mock_stripe.Webhook.construct_event.return_value = mock_event

        from app.services.stripe_service import construct_webhook_event

        result = construct_webhook_event(b"payload", "sig_header")

        assert result == mock_event
        mock_stripe.Webhook.construct_event.assert_called_once_with(
            b"payload", "sig_header", "whsec_test"
        )

    @patch("app.services.stripe_service.settings")
    @patch("app.services.stripe_service.stripe")
    def test_construct_webhook_event_invalid_signature(
        self, mock_stripe, mock_settings
    ):
        mock_settings.STRIPE_WEBHOOK_SECRET = "whsec_test"

        import stripe as stripe_lib

        mock_stripe.error.SignatureVerificationError = (
            stripe_lib.error.SignatureVerificationError
        )
        mock_stripe.Webhook.construct_event.side_effect = (
            stripe_lib.error.SignatureVerificationError("bad sig", "sig_header")
        )

        from app.services.stripe_service import construct_webhook_event

        with pytest.raises(stripe_lib.error.SignatureVerificationError):
            construct_webhook_event(b"payload", "bad_sig")


# ---------------------------------------------------------------------------
# Image Validation Tests (no DB needed)
# ---------------------------------------------------------------------------


def _make_image_bytes(fmt: str = "JPEG", width: int = 100, height: int = 100) -> bytes:
    """Create minimal valid image bytes for testing."""
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _make_upload_file(
    content: bytes, content_type: str = "image/jpeg", filename: str = "test.jpg"
) -> UploadFile:
    """Create an UploadFile from bytes."""
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers={"content-type": content_type},
    )


class TestImageValidation:
    """Tests for validate_image()."""

    @pytest.mark.asyncio
    async def test_valid_jpeg(self):
        from app.utils.image_validation import validate_image

        data = _make_image_bytes("JPEG", 200, 200)
        upload = _make_upload_file(data, "image/jpeg")

        result = await validate_image(upload)
        assert result == data

    @pytest.mark.asyncio
    async def test_valid_png(self):
        from app.utils.image_validation import validate_image

        data = _make_image_bytes("PNG", 200, 200)
        upload = _make_upload_file(data, "image/png", "test.png")

        result = await validate_image(upload)
        assert result == data

    @pytest.mark.asyncio
    async def test_invalid_content_type(self):
        from app.utils.image_validation import validate_image

        data = b"not-an-image"
        upload = _make_upload_file(data, "application/pdf", "test.pdf")

        with pytest.raises(HTTPException) as exc_info:
            await validate_image(upload)
        assert exc_info.value.status_code == 400
        assert "not allowed" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_file_too_large(self):
        from app.utils.image_validation import validate_image

        # Create a 1MB image and set max to something tiny
        data = _make_image_bytes("JPEG", 200, 200)
        # Pad data beyond 1MB limit
        padded = data + b"\x00" * (2 * 1024 * 1024)
        upload = _make_upload_file(padded, "image/jpeg")

        with pytest.raises(HTTPException) as exc_info:
            await validate_image(upload, max_size_mb=1)
        assert exc_info.value.status_code == 400
        assert "size" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_image_dimensions_too_large(self):
        from app.utils.image_validation import validate_image

        data = _make_image_bytes("JPEG", 5000, 5000)
        upload = _make_upload_file(data, "image/jpeg")

        with pytest.raises(HTTPException) as exc_info:
            await validate_image(upload)
        assert exc_info.value.status_code == 400
        assert "dimensions" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Auth Dependency Tests (via API endpoints using client fixture)
# ---------------------------------------------------------------------------


class TestAuthGetCurrentUser:
    """Tests for get_current_user dependency via /api/v1/users/me."""

    @pytest.mark.asyncio
    async def test_invalid_token(self, client):
        response = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert response.status_code == 401
        assert "could not validate credentials" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_user_not_found(self, client):
        # Create a valid token for a non-existent user
        fake_user_id = str(uuid.uuid4())
        token = create_access_token(fake_user_id)

        response = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_inactive_user(self, client, db_session):
        inactive_user = await create_test_user(
            db_session,
            phone_number="+18135559999",
            full_name="Inactive",
            is_active=False,
        )
        token = create_access_token(str(inactive_user.id))
        response = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403
        assert "inactive" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_valid_user(self, client, test_user):
        token = create_access_token(str(test_user.id))
        response = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["phone_number"] == test_user.phone_number
        assert data["full_name"] == test_user.full_name


class TestAuthGetCurrentUserWithProfile:
    """Tests for get_current_user_with_profile dependency.

    Uses /api/v1/circle/members which requires a completed profile.
    """

    @pytest.mark.asyncio
    async def test_user_without_full_name_returns_428(self, client, db_session):
        user_no_name = await create_test_user(
            db_session, phone_number="+18005551234", full_name=None
        )
        token = create_access_token(str(user_no_name.id))
        response = await client.get(
            "/api/v1/circle/members",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 428
        assert "profile incomplete" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_user_with_full_name_passes(self, client, test_user):
        token = create_access_token(str(test_user.id))
        response = await client.get(
            "/api/v1/circle/members",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Should not be 428; actual status depends on endpoint logic (200 expected)
        assert response.status_code != 428


class TestAuthGetCurrentUserWithSubscription:
    """Tests for get_current_user_with_subscription dependency.

    Uses POST /api/v1/sessions which requires an active subscription.
    """

    @pytest.mark.asyncio
    async def test_user_without_access_returns_402(self, client, db_session):
        user = await create_test_user(
            db_session, phone_number="+18005559999", full_name="No Sub User"
        )
        # Consume free trial
        db_session.add(
            Session(
                user_id=user.id,
                expected_return_time=datetime.now(UTC) - timedelta(hours=1),
                actual_return_time=datetime.now(UTC),
                status=SessionStatus.COMPLETED.value,
            )
        )
        await db_session.commit()

        token = create_access_token(str(user.id))
        response = await client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=2)
                ).isoformat(),
            },
        )
        assert response.status_code == 402
        assert "subscription required" in response.json()["detail"].lower()


class TestAuthGetCurrentUserOptional:
    """Tests for get_current_user_optional (direct unit tests, not via API)."""

    @pytest.mark.asyncio
    async def test_no_token_returns_none(self, db_session):
        from app.api.v1.deps.auth import get_current_user_optional

        result = await get_current_user_optional(db_session, access_token=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self, db_session):
        from app.api.v1.deps.auth import get_current_user_optional

        result = await get_current_user_optional(
            db_session, access_token="invalid.jwt.token"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self, db_session, test_user):
        from app.api.v1.deps.auth import get_current_user_optional

        token = create_access_token(str(test_user.id))
        result = await get_current_user_optional(db_session, access_token=token)

        assert result is not None
        assert result.id == test_user.id

    @pytest.mark.asyncio
    async def test_valid_token_nonexistent_user_returns_none(self, db_session):
        from app.api.v1.deps.auth import get_current_user_optional

        token = create_access_token(str(uuid.uuid4()))
        result = await get_current_user_optional(db_session, access_token=token)
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_token_inactive_user_returns_none(self, db_session):
        from app.api.v1.deps.auth import get_current_user_optional

        inactive_user = await create_test_user(
            db_session,
            phone_number="+18005550000",
            full_name="Inactive Optional",
            is_active=False,
        )
        token = create_access_token(str(inactive_user.id))
        result = await get_current_user_optional(db_session, access_token=token)
        assert result is None
