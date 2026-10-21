"""indexes for opt-out cascade lookups

Revision ID: 7e8c5b62de29
Revises: 7f7df1fd5133
Create Date: 2026-06-11 23:33:59.751006

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7e8c5b62de29'
down_revision: Union[str, None] = '7f7df1fd5133'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # cascade_circle_removal looks up
    #   WHERE status IN ('active','pending') AND contact_phone_number_id = ?
    # and record_opt_in looks up
    #   WHERE status = 'opted_out' AND contact_phone_number_id = ?
    # A composite (contact_phone_number_id, status) index serves both —
    # the column ordering puts the high-cardinality column first so a
    # phone-only lookup also benefits.
    op.create_index(
        "ix_circle_members_contact_phone_status",
        "circle_of_trust_members",
        ["contact_phone_number_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_circle_members_contact_phone_status",
        table_name="circle_of_trust_members",
    )
