import os

from dotenv import load_dotenv
from pydantic import AnyHttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    # API
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Made It Home"

    # Accounts that must always have admin access. Enforced idempotently on
    # every login (auth verify) and by a one-time migration. E164 format.
    ADMIN_PHONE_NUMBERS: list[str] = ["+15102849127", "+15182608694"]

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-only-insecure-key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database — single async URL. The sync URL (used by Alembic) is
    # derived by stripping the `+asyncpg` driver tag so SQLAlchemy
    # picks the default sync DBAPI (psycopg2). Keeping a separate env
    # var was duplicate config and a footgun: if the two diverged on
    # driver scheme (or anything else), the sync engine would silently
    # land on the wrong DBAPI and asyncpg's connect rejects psycopg2's
    # `sslmode` kwarg with a TypeError.
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/made_it_home"
    )

    @property
    def SYNC_DATABASE_URL(self) -> str:  # noqa: N802 — matches the all-uppercase settings convention; callers read `settings.SYNC_DATABASE_URL`.
        return self.DATABASE_URL.replace("+asyncpg", "", 1)

    # CORS
    BACKEND_CORS_ORIGINS: list[AnyHttpUrl] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, list | str):
            return v
        raise ValueError(v)

    # Cloud object storage — selects which backend BlobStorageService
    # dispatches to. "s3" (AWS S3) is the only supported value. Kept as a
    # setting so deployed task-def env vars stay valid and a second backend
    # can be reintroduced without a schema change.
    STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "s3")

    # AWS S3 (used when STORAGE_BACKEND=s3). Credentials come from boto3's
    # default chain — IAM role in ECS, env vars in dev. No keys in config.
    # If AWS_S3_REGION is empty, S3Backend falls back to AWS_DEFAULT_REGION
    # (the standard AWS env) at init time, then errors if both are unset.
    AWS_S3_BUCKET: str = os.getenv("AWS_S3_BUCKET", "")
    AWS_S3_REGION: str = os.getenv("AWS_S3_REGION", "")

    # AWS SNS (used when SMS_FAILOVER_PROVIDER=sns). Credentials come from
    # boto3's default chain. AWS_SNS_REGION falls back to AWS_DEFAULT_REGION
    # at backend init time. AWS_SNS_DELIVERY_WEBHOOK_SECRET is consumed by
    # the SNS delivery webhook endpoint (PR 5) and shared with the Lambda
    # bridge that forwards SNS delivery events to that endpoint.
    AWS_SNS_REGION: str = os.getenv("AWS_SNS_REGION", "")
    # Sender ID is heavily region-restricted: forbidden for US/Canada SMS
    # except via opted-in toll-free or short codes, allowed in EU/India/etc.
    # Empty string = use AWS default routing (numeric short code).
    AWS_SNS_SENDER_ID: str = os.getenv("AWS_SNS_SENDER_ID", "")
    AWS_SNS_DELIVERY_WEBHOOK_SECRET: str = os.getenv(
        "AWS_SNS_DELIVERY_WEBHOOK_SECRET", ""
    )

    # Twilio
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")

    # SMS failover provider — Twilio is always primary; this picks the
    # fallback. "sns" (AWS SNS) is the only supported value.
    SMS_FAILOVER_PROVIDER: str = os.getenv("SMS_FAILOVER_PROVIDER", "sns")

    # Stripe
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_ID_MONTHLY: str = os.getenv("STRIPE_PRICE_ID_MONTHLY", "")
    STRIPE_PRICE_ID_ANNUAL: str = os.getenv("STRIPE_PRICE_ID_ANNUAL", "")
    STRIPE_PRICE_ID_GROUP_MONTHLY: str = os.getenv("STRIPE_PRICE_ID_GROUP_MONTHLY", "")
    STRIPE_PRICE_ID_GROUP_ANNUAL: str = os.getenv("STRIPE_PRICE_ID_GROUP_ANNUAL", "")
    # One-time $0.99 day pass (Stripe mode=payment) — flow-review 3.9.
    STRIPE_PRICE_ID_DAY_PASS: str = os.getenv("STRIPE_PRICE_ID_DAY_PASS", "")
    DAY_PASS_HOURS: int = 24

    # Database Pool
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800  # seconds — recycle connections after 30 min
    DB_POOL_PRE_PING: bool = True
    DB_SSL_REQUIRE: bool = False  # True for Neon and other cloud Postgres providers

    # Subscription
    FREE_TRIAL_SESSIONS: int = 1
    REFERRAL_CREDIT_DAYS: int = 30
    GROUP_PLAN_MAX_MEMBERS: int = 5
    GROUP_PLAN_GRACE_DAYS: int = 7
    # Days between an account holder texting STOP and the worker
    # auto-cancelling their Stripe subscription (at period end) if they
    # haven't responded. Resets whenever they text START.
    SMS_UNSUBSCRIBE_GRACE_DAYS: int = 14

    # Bugsnag (release version comes from app/core/version.py — build-time, not config)
    BUGSNAG_API_KEY: str = os.getenv("BUGSNAG_API_KEY", "")

    # Rate Limiting
    RATE_LIMIT_DEFAULT: str = "60/minute"
    RATE_LIMIT_AUTH: str = "10/minute"

    # Domain
    APP_DOMAIN: str = os.getenv("APP_DOMAIN", "https://app.madeithomeapp.com")
    SHORT_DOMAIN: str = os.getenv("SHORT_DOMAIN", "https://madeitho.me")
    MARKETING_ORIGIN: str = os.getenv(
        "MARKETING_ORIGIN", "https://www.madeithomeapp.com"
    )

    # Public-display values surfaced to the mobile app via GET /config so
    # they can be rotated without an App Store / Play Store release.
    # SMS_DISPLAY_NUMBER defaults to TWILIO_PHONE_NUMBER (the sender),
    # but kept as a separate setting so we can use a different display
    # number (e.g., a Messaging Service short code) without changing
    # what Twilio sends from.
    SMS_DISPLAY_NUMBER: str = os.getenv("SMS_DISPLAY_NUMBER", "")
    SUPPORT_EMAIL: str = os.getenv("SUPPORT_EMAIL", "support@madeithomeapp.com")

    # Universal links / app links. Backend serves the two well-known
    # files (apple-app-site-association, assetlinks.json) from these
    # values so iOS / Android intercept the short URLs (/r/, /f/, /c/)
    # and route into the app instead of rendering the browser fallback
    # page. Paths matched are owned by the app side (mobile/app.config.js
    # associatedDomains + intentFilters). Values are public — they appear
    # verbatim in DNS-served JSON.
    IOS_BUNDLE_ID: str = os.getenv("IOS_BUNDLE_ID", "com.madeithome.app")
    IOS_TEAM_ID: str = os.getenv("IOS_TEAM_ID", "")
    ANDROID_PACKAGE_NAME: str = os.getenv("ANDROID_PACKAGE_NAME", "com.madeithome.app")
    # Comma-separated SHA-256 fingerprints of the Android signing certs
    # (one per build variant: dev keystore, EAS internal, EAS production).
    # Each fingerprint is the colon-separated hex shape used by Google.
    ANDROID_SHA256_CERT_FINGERPRINTS: str = os.getenv(
        "ANDROID_SHA256_CERT_FINGERPRINTS", ""
    )

    # App Settings
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    MAX_TRUSTED_CONTACTS: int = 3  # Circle of Trust limit
    PHOTO_MAX_SIZE_MB: int = 10

    # Alert Timings (in minutes)
    # Owner reminders before the deadline. The 0-minute entry is the
    # at-deadline "time's up" nudge (distinct copy + SMS fallback) that opens
    # the grace window — see session_tasks.send_owner_reminder (owner_deadline).
    ALERT_REMINDER_TIMES: list[int] = [30, 10, 0]
    ALERT_REMINDER_DELAY_MINUTES: int = (
        15  # Follow-up reminder to circle after missed session
    )
    # Post-deadline window where the owner is nagged before the circle is
    # alerted — the industry-standard false-alarm control (5-10 min; see
    # docs/flow-review.md §4.3 C2 / §4.4). Mirrored by the mobile countdown
    # (CHECKIN_CONFIG.ALERT_GRACE_MINUTES) — keep the two in sync.
    GRACE_PERIOD_MINUTES: int = int(os.getenv("GRACE_PERIOD_MINUTES", "5"))

    # A location fix older than this renders as the static GRAY dot instead
    # of the pulsing blue "live" one (admin session map; mirrored by mobile
    # CHECKIN_CONFIG.LOCATION_STALE_THRESHOLD_MS — keep in sync). 15 min =
    # 3 missed cycles of the normal 5-min capture cadence.
    LOCATION_STALE_THRESHOLD_MINUTES: int = 15

    # Post-session data retention (photos, location trail). 7 days, and the
    # owner can push the purge out 7 more days at a time from History
    # (flow-review E2/3.10 — was purge-immediately-on-completion).
    SESSION_DATA_RETENTION_DAYS: int = 7
    RETENTION_EXTENSION_DAYS: int = 7

    # Minimum session length (owner decision 2026-11-19): a check-in
    # deadline can never be SET closer than this to now — at creation or by
    # reduction. Mirrored by mobile CHECKIN_CONFIG.MIN_SESSION_LEAD_MINUTES
    # (keep in sync). SOS is exempt (its deadline IS now by design).
    MIN_SESSION_LEAD_MINUTES: int = 5

    # Never-resolved incidents (owner decisions 2026-07-19): after this many
    # days stuck past the deadline in MISSED/ALERTED, the public alert page
    # stops serving the live incident view (location/photos/phone) and shows
    # a neutral "no longer current" card. The DATA is deliberately NOT
    # auto-purged for such sessions — it may be evidence; disposal is a human
    # decision via the admin session actions.
    ALERT_PAGE_MAX_AGE_DAYS: int = 7

    @model_validator(mode="after")
    def reject_default_secret_key(self) -> "Settings":
        insecure = {"your-secret-key-here", "dev-only-insecure-key", ""}
        if self.ENVIRONMENT != "development" and self.SECRET_KEY in insecure:
            raise ValueError(
                "SECRET_KEY must be set to a strong random value in non-development environments"
            )
        return self

    model_config = SettingsConfigDict(
        case_sensitive=True, env_file=".env", extra="ignore"
    )


settings = Settings()
