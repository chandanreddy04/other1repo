"""add unique constraint on alerts session recipient type

Revision ID: 17ef24d04e9d
Revises: a9e65bd54068
Create Date: 2026-05-24 12:31:40.523919

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '17ef24d04e9d'
down_revision: Union[str, None] = 'a9e65bd54068'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: if the alerts table already held duplicate
    # (session_id, sent_to_user_id, alert_type) rows, this would fail — they'd
    # need de-duping first. Safe here as the table has no such duplicates.
    op.create_unique_constraint(
        "uq_alerts_session_recipient_type",
        "alerts",
        ["session_id", "sent_to_user_id", "alert_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_alerts_session_recipient_type", "alerts", type_="unique"
    )
