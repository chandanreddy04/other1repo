"""Guard: every value of a StrEnum stored in a CHECK-constrained String column
must appear in the model's CheckConstraint.

These columns store enums as plain strings validated only by a CHECK (see
migration d4a42709f995). Adding an enum member (e.g. SubscriptionSource.COMP)
without widening the CHECK ships a constraint that rejects the new value at
INSERT time in staging/production — invisible to create_all-based tests. This
asserts the model's enums and CHECK stay in lockstep.
"""

import pytest
from sqlalchemy import CheckConstraint

from app.models.subscription import (
    PlanType,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)


def _check_text_for_column(model, column: str) -> str:
    """Return the CHECK constraint text guarding ``column`` (matched by the
    column reference, not the name — the naming convention rewrites .name)."""
    for arg in model.__table_args__:
        if isinstance(arg, CheckConstraint) and f"{column} IN" in str(arg.sqltext):
            return str(arg.sqltext)
    raise AssertionError(f"No CHECK constraint on {model.__name__}.{column}")


@pytest.mark.parametrize(
    "enum_cls, column",
    [
        (SubscriptionSource, "source"),
        (PlanType, "plan_type"),
        (SubscriptionStatus, "status"),
    ],
)
def test_enum_values_covered_by_check_constraint(enum_cls, column):
    text = _check_text_for_column(Subscription, column)
    missing = [e.value for e in enum_cls if f"'{e.value}'" not in text]
    assert not missing, (
        f"{enum_cls.__name__} values {missing} are missing from the CHECK on "
        f"subscriptions.{column} — widen the CheckConstraint (and add a migration)."
    )
