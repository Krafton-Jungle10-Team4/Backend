"""merge marketplace and api deployment

Revision ID: ab5c2f8c6724
Revises: 71cd2ed7f42f, 5d1c6b07edb3
Create Date: 2025-11-20 03:09:34.601601

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ab5c2f8c6724'
down_revision = ('71cd2ed7f42f', '5d1c6b07edb3')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
