"""populate_phone_numbers

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-03-09 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'b6c7d8e9f0a1'
down_revision: Union[str, None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Collect all unique phone number strings from all tables
    sources = [
        "SELECT DISTINCT phone_number FROM users WHERE phone_number IS NOT NULL",
        "SELECT DISTINCT phone_number FROM subscriptions WHERE phone_number IS NOT NULL",
        "SELECT DISTINCT gifted_by_phone FROM subscriptions WHERE gifted_by_phone IS NOT NULL",
        "SELECT DISTINCT referee_phone FROM referrals WHERE referee_phone IS NOT NULL",
        "SELECT DISTINCT contact_phone_number FROM circle_of_trust_members WHERE contact_phone_number IS NOT NULL",
    ]

    all_numbers = set()
    for query in sources:
        rows = conn.execute(sa.text(query))
        for row in rows:
            all_numbers.add(row[0])

    # Insert into phone_numbers (verified=true for numbers that belong to a user)
    user_numbers = set()
    rows = conn.execute(sa.text("SELECT phone_number FROM users WHERE phone_number IS NOT NULL"))
    for row in rows:
        user_numbers.add(row[0])

    for number in all_numbers:
        verified = number in user_numbers
        conn.execute(
            sa.text(
                "INSERT INTO phone_numbers (id, number, verified, created_at) "
                "VALUES (gen_random_uuid(), :number, :verified, NOW()) "
                "ON CONFLICT (number) DO NOTHING"
            ),
            {"number": number, "verified": verified},
        )

    # Backfill FK columns
    conn.execute(sa.text(
        "UPDATE users SET phone_number_id = pn.id "
        "FROM phone_numbers pn WHERE users.phone_number = pn.number"
    ))
    conn.execute(sa.text(
        "UPDATE subscriptions SET phone_number_id = pn.id "
        "FROM phone_numbers pn WHERE subscriptions.phone_number = pn.number"
    ))
    conn.execute(sa.text(
        "UPDATE subscriptions SET gifted_by_phone_id = pn.id "
        "FROM phone_numbers pn WHERE subscriptions.gifted_by_phone = pn.number"
    ))
    conn.execute(sa.text(
        "UPDATE referrals SET referee_phone_id = pn.id "
        "FROM phone_numbers pn WHERE referrals.referee_phone = pn.number"
    ))
    conn.execute(sa.text(
        "UPDATE circle_of_trust_members SET contact_phone_number_id = pn.id "
        "FROM phone_numbers pn WHERE circle_of_trust_members.contact_phone_number = pn.number"
    ))


def downgrade() -> None:
    conn = op.get_bind()

    # Clear FK columns
    conn.execute(sa.text("UPDATE users SET phone_number_id = NULL"))
    conn.execute(sa.text("UPDATE subscriptions SET phone_number_id = NULL"))
    conn.execute(sa.text("UPDATE subscriptions SET gifted_by_phone_id = NULL"))
    conn.execute(sa.text("UPDATE referrals SET referee_phone_id = NULL"))
    conn.execute(sa.text("UPDATE circle_of_trust_members SET contact_phone_number_id = NULL"))

    # Remove all phone_number records
    conn.execute(sa.text("DELETE FROM phone_numbers"))
