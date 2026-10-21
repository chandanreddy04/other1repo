"""Guard against invalid US phone fixtures in test files.

The 555-area-code reserved range and other non-NANP-conforming numbers
silently get rejected by `phonenumbers` — and any service code that
calls `format_to_e164` on them returns None, which means setup steps
in tests can no-op without anyone noticing. We learned this the hard
way during the STOP-flow audit (see [[test-db-via-docker-compose]]
memory if curious).

Scans every test file for `"+1NNNNNNNNNN"` string literals and
validates them through the same path the production code uses. Any
literal that doesn't round-trip fails the test, so the next person
who adds an invalid literal (e.g. ``+15550000123``) to a fixture gets a clear "use a valid
range" signal at CI time instead of a mystery silent no-op.
"""

import re
from pathlib import Path

import pytest

from app.utils.phone import format_to_e164

TESTS_DIR = Path(__file__).parent

# Phone literals like "+14155550100" — three-digit-country-code US format
# is the only shape this repo's fixtures use today, so we anchor on +1.
_PHONE_RE = re.compile(r'"(\+1\d{10})"')

# Honest exclusions: numbers that exist on purpose to test that we
# REJECT them (invalid formats, etc.). Keep the list tight — every
# entry is a footgun.
_INTENTIONAL_INVALID: set[str] = set()

# Pre-existing invalid fixtures across the test tree. These ratchet
# down — never add to this set, only remove. As of the audit cleanup
# the set is empty; the comment + structure stay so a future migration
# (a new ratchet) can use the same pattern.
_LEGACY_INVALID: set[str] = set()


def _all_phone_literals() -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for path in TESTS_DIR.rglob("test_*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            for match in _PHONE_RE.finditer(line):
                out.append((path, lineno, match.group(1)))
    return out


@pytest.mark.parametrize(
    "phone",
    sorted(
        {p for _, _, p in _all_phone_literals()}
        - _INTENTIONAL_INVALID
        - _LEGACY_INVALID
    ),
)
def test_test_phone_literal_validates(phone: str) -> None:
    """Each unique `+1NNNNNNNNNN` literal across the tests/ tree must
    survive `format_to_e164` — otherwise fixtures silently no-op."""
    assert format_to_e164(phone) == phone, (
        f"{phone!r} fails US E164 validation via phonenumbers. "
        f"Use a valid 415/212/310/202 area code with a 555-01xx subscriber, "
        f"e.g. +14155550001, not the 555-area-code reserved range."
    )


def test_legacy_invalid_set_is_only_actually_used() -> None:
    """Ratchet: every entry in _LEGACY_INVALID must still appear in the
    test tree. Lets the set shrink naturally as tests get cleaned up —
    if you fix a fixture you can delete the entry, and if the entry
    rots away without the fixture being fixed, this catches it."""
    actually_used = {p for _, _, p in _all_phone_literals()}
    stale = _LEGACY_INVALID - actually_used
    assert not stale, (
        f"_LEGACY_INVALID has entries no longer present in any test: "
        f"{sorted(stale)}. Delete them from the set."
    )
