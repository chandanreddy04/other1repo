"""Application-level HTTP exceptions with an explicit reporting signal.

``UpstreamUnavailable`` is the designed "try again in a moment" 5xx: a payment
or storage provider didn't answer. It is raised ``from`` the provider error so
the cause is attached, and the 5xx reporter in app/main.py sends it at WARNING
severity — a provider blip is not a defect in this code, but it must still be
visible. A plain ``HTTPException(5xx)`` raised ``from`` an exception, or any
bare 500, is reported as an ERROR.

Related: app/main.py (_report_5xx_http_exceptions), app/core/error_reporting.py,
app/api/v1/endpoints/subscriptions.py (the Stripe call sites).
"""

from fastapi import HTTPException, status


class UpstreamUnavailable(HTTPException):
    """A dependency (Stripe, S3, ...) failed; the client should retry."""

    def __init__(
        self,
        detail: str = "Service temporarily unavailable. Please try again in a moment.",
        status_code: int = status.HTTP_502_BAD_GATEWAY,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
