"""Public app config returned by GET /config to the mobile client.

Surfacing these values via an endpoint (rather than baking them into the
mobile bundle) lets us rotate things like the Twilio sender number or
support email without an App Store / Play Store release. The mobile
client fetches once per cold start, caches the response, and falls back
to its last-known-good values if the network is down.

Anything added here must be safe to expose without authentication —
this endpoint is hit before login.
"""

from pydantic import BaseModel


class AppConfigResponse(BaseModel):
    sms_number: str
    support_email: str
    app_domain: str
    short_domain: str
    marketing_origin: str
    privacy_url: str
    terms_url: str
