"""Remove email and password fields - OTP only auth

Revision ID: 007
Revises: 006
Create Date: 2025-01-19

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    # Drop email-related indexes and constraints first
    op.drop_index('ix_users_email', table_name='users')

    # Drop the email column
    op.drop_column('users', 'email')

    # Drop the hashed_password column - no longer needed with OTP
    op.drop_column('users', 'hashed_password')

    # Make full_name nullable (can be set after registration)
    op.alter_column('users', 'full_name',
        existing_type=sa.String(),
        nullable=True
    )


def downgrade():
    # Re-add email column
    op.add_column('users',
        sa.Column('email', sa.String(), nullable=True)
    )

    # Re-add hashed_password column
    op.add_column('users',
        sa.Column('hashed_password', sa.String(), nullable=True)
    )

    # Recreate email index
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # Make full_name required again
    op.alter_column('users', 'full_name',
        existing_type=sa.String(),
        nullable=False
    )
