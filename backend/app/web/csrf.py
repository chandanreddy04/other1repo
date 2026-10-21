"""CSRF protection using the double-submit cookie pattern.

A random token is set in an HttpOnly cookie and also rendered as a hidden
form field. On POST, the two values must match.
"""

import secrets

from fastapi import HTTPException, Request, Response, status

CSRF_COOKIE_NAME = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_TOKEN_BYTES = 32


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def get_or_create_csrf_token(request: Request) -> str:
    """Return the existing CSRF token from the cookie, or generate a new one."""
    existing = request.cookies.get(CSRF_COOKIE_NAME)
    if existing:
        return existing
    return generate_csrf_token()


def set_csrf_cookie(response: Response, token: str) -> None:
    from app.core.config import settings

    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="strict",
        secure=settings.ENVIRONMENT != "development",
        path="/admin",
    )


async def validate_csrf_token(request: Request) -> None:
    """Compare the cookie token with the form-submitted token.

    Raises HTTPException 403 if they don't match or are missing.
    """
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing CSRF cookie",
        )

    form_data = await request.form()
    form_token = form_data.get(CSRF_FORM_FIELD)
    if not form_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing CSRF token in form",
        )

    if not secrets.compare_digest(cookie_token, str(form_token)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token mismatch",
        )
