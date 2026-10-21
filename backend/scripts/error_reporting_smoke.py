"""Send test events to Bugsnag from a developer machine — the pre-deploy check.

    BUGSNAG_API_KEY=<key> python scripts/error_reporting_smoke.py [--stage staging]
    BUGSNAG_API_KEY=<key> make error-reporting-smoke [STAGE=staging]

Exercises BOTH delivery paths the app uses — an explicit ``notify()`` and a
``logger.error`` through the root-logger forwarder — with synchronous delivery,
so a bad key (401), a DNS/egress problem or a misconfigured client fails HERE
with the SDK's own message instead of vanishing. On success, two events appear
in the Bugsnag dashboard under the chosen release stage within a minute.

``--stage`` defaults to ``staging`` because only production/staging are
delivered (app/core/error_reporting.py NOTIFY_RELEASE_STAGES); it never uses the
``development`` stage, which is filtered by design.

Related: app/core/error_reporting.py, Makefile ``error-reporting-smoke``, docs/deployment.md,
mobile/scripts/error-reporting-smoke.js (the mobile counterpart).
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import socket
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--stage",
        default="staging",
        choices=("staging", "production"),
        help="release stage to report under (default: staging)",
    )
    args = parser.parse_args()

    if not os.environ.get("BUGSNAG_API_KEY"):
        sys.stderr.write("✗ BUGSNAG_API_KEY is not set in the environment.\n")
        return 2

    # Settings read the environment at import time — set the stage first.
    os.environ["ENVIRONMENT"] = args.stage
    # Settings refuse the default SECRET_KEY outside development; this one-off
    # process never signs anything, so a throwaway strong key is fine.
    os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(48))

    import bugsnag

    from app.core.config import settings
    from app.core.error_reporting import ErrorReportingSmokeTestError, configure, notify
    from app.core.version import git_sha

    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout, format="%(name)s: %(message)s"
    )

    problems: list[str] = []

    class _CaptureSdkWarnings(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            # The SDK logs under "bugsnag" / "bugsnag.*" — not this script's own logger.
            is_sdk = record.name == "bugsnag" or record.name.startswith("bugsnag.")
            if is_sdk and record.levelno >= logging.WARNING:
                problems.append(record.getMessage())

    logging.getLogger().addHandler(_CaptureSdkWarnings())

    if not configure(settings):
        sys.stderr.write("✗ configure() declined — is BUGSNAG_API_KEY blank?\n")
        return 1
    # Deliver inline so a failed POST surfaces as an SDK warning right here.
    bugsnag.configure(asynchronous=False)

    sent = notify(
        ErrorReportingSmokeTestError("smoke: explicit notify()"),
        context="scripts.error_reporting_smoke",
        severity="info",
        metadata={"smoke": {"host": socket.gethostname(), "stage": args.stage}},
    )
    logging.getLogger("error_reporting_smoke").error(
        "smoke: root-logger forwarder (logger.error)", extra={"session_id": "smoke"}
    )

    if not sent or problems:
        sys.stderr.write("✗ Bugsnag delivery failed:\n")
        for line in problems or ["notify() returned False"]:
            sys.stderr.write(f"  - {line}\n")
        return 1

    sys.stdout.write(
        f"✓ 2 events delivered — check Bugsnag for release stage '{args.stage}', "
        f"app_version '{git_sha()}' (ErrorReportingSmokeTestError + LogERROR).\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
