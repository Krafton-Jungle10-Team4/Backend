"""merge conversation variables and schema sync

Revision ID: 711882fb6ed3
Revises: a38d586105bf, l2m3n4o5p6q7
Create Date: 2025-11-15 21:21:33.221258

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '711882fb6ed3'
down_revision = ('a38d586105bf', 'l2m3n4o5p6q7')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
