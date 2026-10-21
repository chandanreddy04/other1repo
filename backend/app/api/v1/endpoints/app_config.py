"""Public app config for the mobile client.

GET /config returns display values the mobile app surfaces (SMS sender,
support email, marketing URLs). Lets us rotate these without an App
Store / Play Store release. Mobile caches the response and falls back
to last-known-good when offline; see mobile/services/runtimeConfig.ts.

Endpoint is public — these values are shown to users before login (auth
screens read SUPPORT_EMAIL, terms URLs, etc.), so requiring auth would
break the bootstrap path.
"""

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.app_config import AppConfigResponse

router = APIRouter()


@router.get("", response_model=AppConfigResponse)
async def get_app_config() -> AppConfigResponse:
    return AppConfigResponse(
        # SMS_DISPLAY_NUMBER is intentionally distinct from
        # TWILIO_PHONE_NUMBER (the sender). Fall back to the sender
        # when unset so a deploy without explicit display config still
        # surfaces a usable number.
        sms_number=settings.SMS_DISPLAY_NUMBER or settings.TWILIO_PHONE_NUMBER,
        support_email=settings.SUPPORT_EMAIL,
        app_domain=settings.APP_DOMAIN,
        short_domain=settings.SHORT_DOMAIN,
        marketing_origin=settings.MARKETING_ORIGIN,
        privacy_url=f"{settings.MARKETING_ORIGIN}/privacy",
        terms_url=f"{settings.MARKETING_ORIGIN}/terms",
    )
