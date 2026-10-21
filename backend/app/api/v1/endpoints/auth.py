import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
)
from app.crud import crud_user
from app.crud.account_grant import crud_account_grant
from app.crud.phone_number import crud_phone_number
from app.schemas.auth import RefreshTokenRequest, Token
from app.schemas.user import User
from app.services import sms_opt_out, subscription_service
from app.services.account_deletion import scheduled_purge_at
from app.services.otp import otp_service
from app.utils.phone import format_to_e164

logger = logging.getLogger(__name__)

router = APIRouter()


# OTP Request/Response schemas
class OTPRequest(BaseModel):
    phone_number: str = Field(..., description="Phone number to send OTP to")


class OTPVerification(BaseModel):
    phone_number: str = Field(..., description="Phone number that received OTP")
    otp_code: str = Field(
        ..., min_length=6, max_length=6, description="6-digit OTP code"
    )


class OTPResponse(BaseModel):
    success: bool
    message: str


class PhoneLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    is_new_user: bool
    user: User | None = None
    # Set when the user signs back in during the soft-delete grace.
    # Mobile uses this to render the Welcome Back screen and offer
    # restore vs. sign-out. The issued tokens still work — but only the
    # restore endpoint will accept them; all other endpoints 403.
    deletion_pending: bool = False
    scheduled_deletion_at: str | None = None


# Legacy endpoints - kept for backward compatibility but deprecated
# All new auth should use OTP flow


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = decode_access_token(request.refresh_token)
    if not token_data or token_data.type != "refresh":
        raise credentials_exception

    # Get user
    user = await crud_user.get(db, id=token_data.sub)
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )

    # Reject a refresh token whose version is below the user's current one
    # (revoke-all-sessions). Tokens issued before this feature carry tv=0.
    if token_data.tv < user.token_version:
        raise credentials_exception

    # Create new tokens
    access_token = create_access_token(user.id)
    new_refresh_token = create_refresh_token(user.id, token_version=user.token_version)

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


@router.post("/request-otp", response_model=OTPResponse)
@limiter.limit("5/minute")
async def request_otp(
    request: Request,
    body: OTPRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request OTP for phone number authentication.

    Per-IP rate limit (5/min) caps how many distinct phones a single
    client can probe. The existing per-phone OTP cooldown stops repeat
    requests for the SAME number, but didn't stop someone iterating
    through a phone list to enumerate opted-out numbers via the timing
    difference between the `phone_opted_out` early-return and the
    full OTP-send path. 5/min is generous for legitimate users (one
    OTP per sign-in, occasional resend) and ~1000x too slow for
    enumeration.
    """
    # Refuse to send if the recipient texted STOP. The structured
    # `code` lets mobile render the specific "text START to {our
    # number}" recovery flow rather than a generic delivery failure.
    if await sms_opt_out.is_opted_out(db, body.phone_number):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "phone_opted_out",
                "support_number": settings.TWILIO_PHONE_NUMBER,
            },
        )

    success, message = await otp_service.send_otp(db, body.phone_number)

    if not success:
        wait_seconds = await otp_service.get_resend_wait_seconds(db, body.phone_number)
        if wait_seconds > 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"message": message, "retry_after": wait_seconds},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return OTPResponse(success=True, message=message)


@router.post("/verify-otp", response_model=PhoneLoginResponse)
async def verify_otp(
    request: OTPVerification,
    db: AsyncSession = Depends(get_db),
):
    """Verify OTP and login/register user"""
    # Verify the OTP
    success, message = await otp_service.verify_otp(
        db, request.phone_number, request.otp_code
    )

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    # Format phone number to E164 using phonenumbers library
    clean_phone = format_to_e164(request.phone_number)
    if not clean_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid phone number format",
        )

    # Get or create user
    user, is_new_user = await crud_user.get_or_create_by_phone(
        db,
        phone_number=clean_phone,
        share_code=subscription_service.generate_share_code(),
        circle_invite_code=subscription_service.generate_circle_invite_code(),
    )

    # Soft-deleted users get tokens + the deletion_pending signal so the
    # mobile app can render the Welcome Back screen. We skip downstream
    # bootstrap work (stripe customer, gift resolution, phone-verified
    # flip) — those happen on restore, not on a re-auth attempt during
    # grace. The issued tokens are only usable against /me/restore; all
    # other endpoints continue to 403.
    if user.deleted_at is not None:
        access_token = create_access_token(str(user.id))
        refresh_token = create_refresh_token(
            str(user.id), token_version=user.token_version
        )
        return PhoneLoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            is_new_user=False,
            user=None,
            deletion_pending=True,
            scheduled_deletion_at=scheduled_purge_at(user.deleted_at).isoformat(),
        )

    # Invariants enforced for every active account on each login (idempotent):
    #  - a circle invite code: older accounts predate get_or_create setting it,
    #    and without one the shared /c/{code} link resolves to nothing
    #    ("Invalid circle invite code").
    #  - designated admin accounts stay admin.
    account_dirty = False
    if not user.circle_invite_code:
        user.circle_invite_code = subscription_service.generate_circle_invite_code()
        account_dirty = True
    if not user.share_code:
        user.share_code = subscription_service.generate_share_code()
        account_dirty = True
    if clean_phone in settings.ADMIN_PHONE_NUMBERS and not user.is_admin:
        user.is_admin = True
        account_dirty = True
    if account_dirty:
        await db.commit()
        await db.refresh(user)

    if is_new_user:
        logger.info("New user registered via OTP: %s", user.id)
        # Phase 9 re-attachment: look for an existing Stripe Customer
        # with this phone (likely left behind by a prior delete + purge
        # cycle). If found, attach it instead of creating a fresh one,
        # and stamp `had_prior_billing_history` so the access check
        # denies free trial on a re-signed-up user that already billed.
        try:
            from app.services.stripe_service import (
                customer_has_subscription_history,
                find_existing_customer_by_phone,
                get_or_create_stripe_customer,
            )

            existing = find_existing_customer_by_phone(clean_phone)
            if existing is not None:
                # Both Stripe SDK objects and plain dicts (used in tests)
                # support `[]` access; `.attr` would AttributeError on a
                # plain dict.
                existing_id = existing["id"]
                user.stripe_customer_id = existing_id
                user.had_prior_billing_history = customer_has_subscription_history(
                    existing_id
                )
                await db.commit()
                await db.refresh(user)
                logger.info(
                    "Re-attached existing Stripe Customer %s on signup for %s "
                    "(prior_history=%s)",
                    existing_id,
                    user.id,
                    user.had_prior_billing_history,
                )
            else:
                await get_or_create_stripe_customer(db, user)
        except Exception:
            # Retried by the worker (retry_pending_stripe_customers) — still worth seeing.
            logger.exception(
                "Stripe customer setup failed at signup",
                extra={"user_id": str(user.id)},
            )

    # Mark phone number as verified (OTP was delivered and confirmed)
    phone, _ = await crud_phone_number.get_or_create(db, number=clean_phone)
    if not phone.verified:
        await crud_phone_number.mark_verified(db, phone=phone)

    # Resolve any pending gift subscriptions for this phone number
    await subscription_service.resolve_pending_gifts(db, clean_phone, user.id)

    # Admin-managed grant (store reviewers, comps): grant lifetime comp access
    # so the account can reach subscription-gated check-in (idempotent).
    grant = await crud_account_grant.get_enabled_by_phone(db, phone_number=clean_phone)
    if grant:
        await subscription_service.ensure_comp_access(db, clean_phone, user.id)

    # Create tokens
    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id), token_version=user.token_version)

    # Prepare user data for response
    user_data = User.model_validate(user) if not is_new_user else None

    return PhoneLoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        is_new_user=is_new_user,
        user=user_data,
    )


@router.post("/resend-otp", response_model=OTPResponse)
@limiter.limit("5/minute")
async def resend_otp(
    request: Request,
    body: OTPRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resend OTP to phone number.

    Carries the same per-IP rate limit and opt-out gate as request-otp —
    without them this endpoint was an unthrottled SMS-flood / toll-fraud
    vector to any number. force_resend bypasses the per-phone cooldown so an
    explicit user resend still goes through; the 5/min/IP cap bounds abuse.
    """
    if await sms_opt_out.is_opted_out(db, body.phone_number):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "phone_opted_out",
                "support_number": settings.TWILIO_PHONE_NUMBER,
            },
        )

    success, message = await otp_service.send_otp(
        db, body.phone_number, force_resend=True
    )

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return OTPResponse(success=True, message=message)
