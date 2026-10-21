"""circle-of-trust: phone-keyed identity, drop per-row code

Makes (user_id, contact_phone_number_id) the identity of a trusted-contact
relationship, drops the per-row invitation_code and the derived-anyway
contact_user_id, drops the vestigial priority_level, renames contact_name ->
nickname, and adds a REMOVED status. Also enforces one active account per phone
(users.phone_number_id WHERE deleted_at IS NULL) so the contact's app account
can be derived from their phone.

Revision ID: f1a2b3c4d5e6
Revises: c5f8b2a1e9d4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "c5f8b2a1e9d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "circle_of_trust_members"


def upgrade() -> None:
    # 1. New status value. ALTER TYPE ... ADD VALUE cannot run in a transaction;
    #    it is only added to the type here (not used as a literal same-run).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE contact_status_enum ADD VALUE IF NOT EXISTS 'removed'")

    conn = op.get_bind()

    # 2. Backfill the phone identity for app-user rows that only carried
    #    contact_user_id, then drop any row that has no phone at all (can't be
    #    keyed — legacy bad data).
    conn.execute(
        sa.text(
            f"UPDATE {TABLE} m SET contact_phone_number_id = u.phone_number_id "
            "FROM users u WHERE m.contact_user_id = u.id "
            "AND m.contact_phone_number_id IS NULL"
        )
    )
    conn.execute(
        sa.text(f"DELETE FROM {TABLE} WHERE contact_phone_number_id IS NULL")
    )

    # 3. Collapse duplicate (owner, contact phone) rows, keeping the newest.
    conn.execute(
        sa.text(
            f"DELETE FROM {TABLE} a USING {TABLE} b "
            "WHERE a.user_id = b.user_id "
            "AND a.contact_phone_number_id = b.contact_phone_number_id "
            "AND (a.created_at < b.created_at "
            "OR (a.created_at = b.created_at AND a.ctid < b.ctid))"
        )
    )

    # 4. Schema changes.
    op.add_column(
        TABLE, sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column(TABLE, "contact_name", new_column_name="nickname")

    # Drops the app-user partial unique (depends on contact_user_id) and the
    # column's FK along with the column.
    op.drop_index("uq_user_contact_pair_app_users", table_name=TABLE)
    op.drop_column(TABLE, "contact_user_id")
    op.drop_column(TABLE, "invitation_code")
    op.drop_column(TABLE, "priority_level")
    op.execute("DROP TYPE IF EXISTS priority_level_enum")

    op.alter_column(TABLE, "contact_phone_number_id", nullable=False)
    op.create_unique_constraint(
        "uq_cot_members_user_phone", TABLE, ["user_id", "contact_phone_number_id"]
    )

    # 5. One active account per phone — lets the contact's app account be
    #    derived from contact_phone_number_id (used by dispatch, is_app_user).
    op.create_index(
        "uq_users_phone_active",
        "users",
        ["phone_number_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_users_phone_active", table_name="users")
    op.drop_constraint("uq_cot_members_user_phone", TABLE, type_="unique")

    op.add_column(
        TABLE,
        sa.Column(
            "contact_user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "circle_of_trust_members_contact_user_id_fkey",
        TABLE,
        "users",
        ["contact_user_id"],
        ["id"],
    )
    op.add_column(TABLE, sa.Column("invitation_code", sa.String(), nullable=True))
    op.create_unique_constraint(
        "circle_of_trust_members_invitation_code_key", TABLE, ["invitation_code"]
    )
    priority_enum = sa.Enum("primary", "secondary", name="priority_level_enum")
    priority_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        TABLE,
        sa.Column(
            "priority_level", priority_enum, server_default="primary", nullable=False
        ),
    )
    op.alter_column(TABLE, "contact_phone_number_id", nullable=True)
    op.alter_column(TABLE, "nickname", new_column_name="contact_name")
    op.drop_column(TABLE, "removed_at")
    # The 'removed' enum value is left in place (Postgres can't drop enum values).
