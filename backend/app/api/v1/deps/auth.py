from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.core.security import decode_access_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = decode_access_token(token)
    # Reject refresh tokens (type=="refresh") on the access path — only access
    # tokens may authenticate API requests.
    if not token_data or token_data.type != "access":
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == token_data.sub))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )
    return current_user


async def get_current_user_with_profile(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Ensures user has completed their profile (has a name)"""
    if not current_user.full_name:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Profile incomplete. Please complete your profile first.",
            headers={"X-Profile-Required": "true"},
        )
    return current_user


async def require_subscription_access(db: AsyncSession, user: User) -> None:
    """Raise 402 unless the user has an active subscription or other access.

    Called inline (not as a route dependency) by session creation so the gate
    can be applied per session type — SOS is free, always: a panic press must
    never be blocked by billing. Replaces the former
    ``get_current_user_with_subscription`` dependency, which gated the whole
    ``POST /sessions`` endpoint regardless of type.
    """
    from app.services import subscription_service

    access = await subscription_service.check_access(db, user)
    if not access.has_access:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Subscription required to create sessions.",
            headers={"X-Subscription-Required": "true"},
        )


async def get_current_user_allow_soft_deleted(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    """Authenticate a user even if they are soft-deleted (within grace).

    Used exclusively by the restore endpoint so a user who signs back in
    during the 30-day grace window can clear their own `deleted_at`. All
    other endpoints continue to reject soft-deleted users via the
    standard `get_current_user` 403.

    Still rejects users that are inactive for any reason OTHER than
    soft-delete (e.g. admin disabled). The check is:
    inactive AND deleted_at IS NULL → 403.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = decode_access_token(token)
    if not token_data or token_data.type != "access":
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == token_data.sub))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active and user.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )

    return user


async def get_current_user_optional(
    db: AsyncSession,
    access_token: str | None = None,
) -> User | None:
    """Get current user from cookie token if present, returns None if not authenticated."""
    if not access_token:
        return None

    token_data = decode_access_token(access_token)
    # Only access tokens may authenticate (reject refresh tokens used as access).
    if not token_data or token_data.type != "access":
        return None

    result = await db.execute(select(User).where(User.id == token_data.sub))
    user = result.scalar_one_or_none()

    if user and user.is_active:
        return user

    return None


async def get_current_user_from_cookie(
    db: AsyncSession = Depends(get_db),
    access_token: str = Cookie(None),
) -> User | None:
    """Dependency to get current user from cookie."""
    return await get_current_user_optional(db, access_token)
