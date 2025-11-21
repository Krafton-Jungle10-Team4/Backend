"""merge slack integrations heads

Revision ID: d4c6074b550f
Revises: 0248ea7e10f5, p7q8r9s0t1u2
Create Date: 2025-11-21 13:11:33.600209

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4c6074b550f'
down_revision = ('0248ea7e10f5', 'p7q8r9s0t1u2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
