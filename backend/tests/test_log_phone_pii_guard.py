"""Guard against raw phone PII in log calls (f-string / positional form).

The existing test_no_phone_in_log_extras.py covers `extra=` dict literals.
This complements it: error/warning/exception logs in the SMS + auth layers
must not interpolate a raw phone variable (it would ship to Bugsnag, which
must only ever receive user.id). Phone values must go through phone_tag().

Related: app/services/sms.py, app/services/sms_sns.py, app/utils/phone.py,
         .claude/rules/security.md.
"""

import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"

# Raw `{to_phone}` / `{from_phone}` / `{phone_number}` inside an f-string is the
# leak; `{phone_tag(to_phone)}` is OK because the brace directly wraps
# `phone_tag(...)`, not the bare variable.
RAW_PHONE_IN_FSTRING = re.compile(r"\{(to_phone|from_phone|phone_number)\}")

# Only the Bugsnag-forwarding levels matter (see app/core/logging.py); info/debug
# stay local, so dev-mode SMS echo logs are fine.
BUGSNAG_LEVEL = re.compile(r"logger\.(error|warning|exception|critical)\(")

SCAN = [
    "services/sms.py",
    "services/sms_sns.py",
    "web/routes_htmx_auth.py",
    "api/v1/endpoints/inbound_sms.py",
]


@pytest.mark.parametrize("rel", SCAN)
def test_no_raw_phone_in_log_fstrings(rel: str):
    text = (APP / rel).read_text()
    offenders = [
        line.strip()
        for line in text.splitlines()
        if BUGSNAG_LEVEL.search(line) and RAW_PHONE_IN_FSTRING.search(line)
    ]
    assert not offenders, (
        f"{rel}: raw phone interpolated in a log call (use phone_tag()): {offenders}"
    )
