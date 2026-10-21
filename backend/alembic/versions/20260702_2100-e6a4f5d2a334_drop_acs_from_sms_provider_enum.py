"""drop 'acs' from sms_provider_enum (AWS-only deployment)

Azure Communication Services was removed as the SMS failover provider on
2026-07-02 (deployment went AWS-only; SNS is the sole failover). Postgres
can't remove a value from an enum in place, so recreate the type. Safe:
pre-launch, no rows carry 'acs'; the upgrade nulls any that hypothetically
do rather than failing mid-migration.

Revision ID: e6a4f5d2a334
Revises: d5f3e4c1f223
Create Date: 2026-07-02 21:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e6a4f5d2a334'
down_revision: str | None = 'd5f3e4c1f223'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE alerts SET sms_provider = NULL WHERE sms_provider = 'acs'")
    op.execute("ALTER TYPE sms_provider_enum RENAME TO sms_provider_enum_old")
    op.execute("CREATE TYPE sms_provider_enum AS ENUM ('twilio', 'sns')")
    op.execute(
        "ALTER TABLE alerts ALTER COLUMN sms_provider TYPE sms_provider_enum "
        "USING sms_provider::text::sms_provider_enum"
    )
    op.execute("DROP TYPE sms_provider_enum_old")


def downgrade() -> None:
    op.execute("ALTER TYPE sms_provider_enum RENAME TO sms_provider_enum_old")
    op.execute("CREATE TYPE sms_provider_enum AS ENUM ('twilio', 'acs', 'sns')")
    op.execute(
        "ALTER TABLE alerts ALTER COLUMN sms_provider TYPE sms_provider_enum "
        "USING sms_provider::text::sms_provider_enum"
    )
    op.execute("DROP TYPE sms_provider_enum_old")
