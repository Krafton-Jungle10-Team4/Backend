"""merge to latest head

Revision ID: 450d3700bc71
Revises: 66c5b911825c, m3n4o5p6q7r8
Create Date: 2025-11-16 15:43:56.641377

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '450d3700bc71'
down_revision = ('66c5b911825c', 'm3n4o5p6q7r8')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
