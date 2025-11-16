"""merge_duplicate_merges

Revision ID: 66c5b911825c
Revises: 711882fb6ed3, 8777a63928bf
Create Date: 2025-11-16 12:22:42.136247

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '66c5b911825c'
down_revision = ('711882fb6ed3', '8777a63928bf')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
