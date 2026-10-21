"""Rename notification kind alert_claimed -> alert_acknowledged.

The product vocabulary is "acknowledge" (owner decision 2026-07-18): the
button is Acknowledge, the copy never says "claim"/"on it", and the DB's
Alert state was always ACKNOWLEDGED. This renames the one remaining
claim-flavored value, the notification_kind_enum member, so code and data
agree. Existing delivery rows are updated in place by the enum rename;
historical dedupe_key strings keep the old prefix (they're only identity).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-18 00:00:00
"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE notification_kind_enum "
        "RENAME VALUE 'alert_claimed' TO 'alert_acknowledged'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TYPE notification_kind_enum "
        "RENAME VALUE 'alert_acknowledged' TO 'alert_claimed'"
    )
