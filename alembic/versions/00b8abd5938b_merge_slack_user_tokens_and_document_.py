"""merge slack user tokens and document embeddings bot_id nullable

Revision ID: 00b8abd5938b
Revises: c9d8e7f6a5b4, u1s2t3u4v5w6
Create Date: 2025-11-25 04:16:17.201079

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '00b8abd5938b'
down_revision = ('c9d8e7f6a5b4', 'u1s2t3u4v5w6')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
