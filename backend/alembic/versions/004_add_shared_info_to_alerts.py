"""Add shared_info column to alerts table

Revision ID: 004
Revises: 003
Create Date: 2025-01-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    # Add shared_info column to alerts table
    op.add_column('alerts', sa.Column('shared_info', postgresql.JSONB(), nullable=True))

    # Create an index on shared_info for better query performance
    op.create_index('ix_alerts_shared_info', 'alerts', ['shared_info'], postgresql_using='gin')


def downgrade():
    # Drop the index
    op.drop_index('ix_alerts_shared_info', table_name='alerts')

    # Drop the shared_info column
    op.drop_column('alerts', 'shared_info')
