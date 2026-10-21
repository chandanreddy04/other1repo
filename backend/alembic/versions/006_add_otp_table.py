"""Add OTP table for phone authentication

Revision ID: 006
Revises: 005
Create Date: 2025-01-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    # Create OTP table
    op.create_table('otps',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('phone_number', sa.String(), nullable=False),
        sa.Column('otp_code', sa.String(6), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=True, default=0),
        sa.Column('is_used', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_verified', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_otps')
    )

    # Create indexes for faster lookups
    op.create_index('ix_otps_phone_number', 'otps', ['phone_number'])
    op.create_index('ix_otps_created_at', 'otps', ['created_at'])

    # Make phone_number unique and not null in users table (if not already)
    # First, ensure no duplicate phone numbers exist
    op.execute("""
        UPDATE users
        SET phone_number = CONCAT(phone_number, '_', id::text)
        WHERE phone_number IN (
            SELECT phone_number
            FROM users
            GROUP BY phone_number
            HAVING COUNT(*) > 1
        )
    """)

    # Add unique constraint to phone_number
    op.create_unique_constraint('uq_users_phone_number', 'users', ['phone_number'])


def downgrade():
    op.drop_constraint('uq_users_phone_number', 'users', type_='unique')
    op.drop_index('ix_otps_created_at', table_name='otps')
    op.drop_index('ix_otps_phone_number', table_name='otps')
    op.drop_table('otps')
