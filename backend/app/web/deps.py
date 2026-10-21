from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.auth import get_current_user_optional
from app.api.v1.deps.db import get_db
from app.models.user import User


async def get_current_admin(
    db: AsyncSession = Depends(get_db),
    access_token: str = Cookie(None),
) -> User:
    """Require an authenticated admin user, or redirect/deny."""
    user = await get_current_user_optional(db, access_token)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
