"""Make document_embeddings.bot_id nullable for user-level uploads

Revision ID: c9d8e7f6a5b4
Revises: f7e8d9c0a1b2, d5adbd4a6a0c
Create Date: 2025-11-24 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9d8e7f6a5b4'
down_revision = ('f7e8d9c0a1b2', 'd5adbd4a6a0c')
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow document_embeddings.bot_id to be NULL for user-level knowledge uploads."""
    op.alter_column(
        'document_embeddings',
        'bot_id',
        existing_type=sa.String(length=100),
        nullable=True
    )


def downgrade() -> None:
    """Revert bot_id column back to NOT NULL."""
    op.alter_column(
        'document_embeddings',
        'bot_id',
        existing_type=sa.String(length=100),
        nullable=False
    )
