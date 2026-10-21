"""rename family plan to group plan

Renames the family_plans / family_plan_members tables (and every
constraint, index, and the family_plan_id FK column) to their group_plan
equivalents, and migrates the subscriptions.plan_type values
family_monthly/family_annual -> group_monthly/group_annual. Pure rebrand;
no behavioural change. plan_type is a plain String column (no native PG
enum), so the value change is a CHECK-constraint swap + data UPDATE.

Constraint/index names follow the metadata naming convention in
app/db/base.py (pk_/fk_/uq_/ck_ prefixes; the ck convention wraps the
explicit name, hence the doubled ck_..._ck_... names). The targets here
match exactly what Base.metadata.create_all produces for the renamed
models, so the migrated schema and the test schema stay identical.

Revision ID: f7a3d9e1c8b2
Revises: 69bb7b6ae2f0
Create Date: 2026-07-19 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f7a3d9e1c8b2'
down_revision: Union[str, None] = '69bb7b6ae2f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (from_name, to_name) for every renamed constraint/index. Constraint
# renames (pk/fk/uq/ck) go through ALTER TABLE ... RENAME CONSTRAINT (which
# also renames the backing index for pk/uq); plain indexes go through
# ALTER INDEX ... RENAME.
_GROUP_PLANS_CONSTRAINTS = [
    ("pk_family_plans", "pk_group_plans"),
    ("fk_family_plans_owner_user_id_users", "fk_group_plans_owner_user_id_users"),
    ("fk_family_plans_subscription_id_subscriptions", "fk_group_plans_subscription_id_subscriptions"),
    ("uq_family_plans_subscription", "uq_group_plans_subscription"),
    ("uq_family_plans_invite_code", "uq_group_plans_invite_code"),
]
_GROUP_PLAN_MEMBERS_CONSTRAINTS = [
    ("pk_family_plan_members", "pk_group_plan_members"),
    ("fk_family_plan_members_family_plan_id_family_plans", "fk_group_plan_members_group_plan_id_group_plans"),
    ("fk_family_plan_members_user_id_users", "fk_group_plan_members_user_id_users"),
    ("uq_fpm_plan_user", "uq_gpm_plan_user"),
    ("ck_family_plan_members_ck_family_plan_members_role", "ck_group_plan_members_ck_group_plan_members_role"),
]
_INDEXES = [
    ("ix_fpm_plan_left", "ix_gpm_plan_left"),
    ("ix_fpm_one_active_per_user", "ix_gpm_one_active_per_user"),
    ("ix_family_plan_members_user_id", "ix_group_plan_members_user_id"),
]

_CK_SUBS = "ck_subscriptions_ck_subscriptions_plan_type"
_CK_OLD = "plan_type IN ('monthly','annual','family_monthly','family_annual','day_pass')"
_CK_NEW = "plan_type IN ('monthly','annual','group_monthly','group_annual','day_pass')"


def _rename_constraint(table: str, old: str, new: str) -> None:
    op.execute(f'ALTER TABLE {table} RENAME CONSTRAINT "{old}" TO "{new}"')


def _rename_index(old: str, new: str) -> None:
    op.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')


def upgrade() -> None:
    # 1. plan_type values: drop CHECK, migrate data, re-add CHECK with new values.
    op.execute(f'ALTER TABLE subscriptions DROP CONSTRAINT "{_CK_SUBS}"')
    op.execute(
        "UPDATE subscriptions SET plan_type = 'group_monthly' "
        "WHERE plan_type = 'family_monthly'"
    )
    op.execute(
        "UPDATE subscriptions SET plan_type = 'group_annual' "
        "WHERE plan_type = 'family_annual'"
    )
    op.execute(f'ALTER TABLE subscriptions ADD CONSTRAINT "{_CK_SUBS}" CHECK ({_CK_NEW})')

    # 2. Rename tables (FK references follow automatically).
    op.rename_table("family_plans", "group_plans")
    op.rename_table("family_plan_members", "group_plan_members")

    # 3. Rename the FK column on the members table.
    op.alter_column(
        "group_plan_members", "family_plan_id", new_column_name="group_plan_id"
    )

    # 4. Rename constraints + indexes to match the renamed models.
    for old, new in _GROUP_PLANS_CONSTRAINTS:
        _rename_constraint("group_plans", old, new)
    for old, new in _GROUP_PLAN_MEMBERS_CONSTRAINTS:
        _rename_constraint("group_plan_members", old, new)
    for old, new in _INDEXES:
        _rename_index(old, new)


def downgrade() -> None:
    for old, new in _INDEXES:
        _rename_index(new, old)
    for old, new in _GROUP_PLAN_MEMBERS_CONSTRAINTS:
        _rename_constraint("group_plan_members", new, old)
    for old, new in _GROUP_PLANS_CONSTRAINTS:
        _rename_constraint("group_plans", new, old)

    op.alter_column(
        "group_plan_members", "group_plan_id", new_column_name="family_plan_id"
    )
    op.rename_table("group_plan_members", "family_plan_members")
    op.rename_table("group_plans", "family_plans")

    op.execute(f'ALTER TABLE subscriptions DROP CONSTRAINT "{_CK_SUBS}"')
    op.execute(
        "UPDATE subscriptions SET plan_type = 'family_monthly' "
        "WHERE plan_type = 'group_monthly'"
    )
    op.execute(
        "UPDATE subscriptions SET plan_type = 'family_annual' "
        "WHERE plan_type = 'group_annual'"
    )
    op.execute(f'ALTER TABLE subscriptions ADD CONSTRAINT "{_CK_SUBS}" CHECK ({_CK_OLD})')
