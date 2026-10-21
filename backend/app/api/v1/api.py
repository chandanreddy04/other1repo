from fastapi import APIRouter

from app.api.v1.endpoints import (
    app_config,
    auth,
    circle_of_trust,
    circle_settings,
    group_plans,
    referrals,
    sessions,
    sponsorship_requests,
    subscriptions,
    users,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(
    circle_of_trust.router, prefix="/circle/members", tags=["circle"]
)
api_router.include_router(circle_settings.router, prefix="/circle", tags=["circle"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(
    subscriptions.router, prefix="/subscriptions", tags=["subscriptions"]
)
api_router.include_router(referrals.router, prefix="/referrals", tags=["referrals"])
api_router.include_router(
    sponsorship_requests.router,
    prefix="/sponsorship-requests",
    tags=["sponsorship-requests"],
)
api_router.include_router(group_plans.router, prefix="/groups", tags=["groups"])
api_router.include_router(app_config.router, prefix="/config", tags=["config"])
# Note: inbound webhooks (Stripe, Twilio/SNS delivery) are NOT mounted here.
# They are server-to-server event sinks, not versioned client API, so they are
# mounted at the top-level /webhooks namespace directly on the app in main.py.
