import json
import logging
import sys
from contextvars import ContextVar

from app.core.config import settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
# Set per request by ErrorHandlerMiddleware: {"method", "path", "user_id"}.
# Read by app.core.error_reporting so every event (explicit or log-forwarded)
# carries
# the request and the authenticated user.id — never more than the id.
request_context_var: ContextVar[dict[str, str | None] | None] = ContextVar(
    "request_context", default=None
)


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id:
            log_record["request_id"] = request_id

        if record.exc_info and record.exc_info[0] is not None:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record, default=str)


def setup_logging() -> None:
    """Configure logging based on environment."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Clear existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(JSONFormatter())

    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.ENVIRONMENT == "development" else logging.WARNING
    )

    init_error_reporting()


def init_error_reporting() -> None:
    """Configure Bugsnag + attach its log forwarder (no-op without an API key).

    Called from setup_logging so BOTH the web app and the worker processes
    (worker_loop.py / worker_tick.py) configure Bugsnag — the workers never
    import app.main. See app/core/error_reporting.py for what gets reported.
    """
    from app.core.error_reporting import configure

    configure(settings)
