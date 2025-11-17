"""add knowledge table

Revision ID: n4o5p6q7r8s9
Revises: e1f2g3h4i5j6
Create Date: 2025-11-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'n4o5p6q7r8s9'
down_revision = 'e1f2g3h4i5j6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'knowledge',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('tags', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column('document_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_id'), 'knowledge', ['id'], unique=False)
    op.create_index(op.f('ix_knowledge_user_id'), 'knowledge', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_knowledge_user_id'), table_name='knowledge')
    op.drop_index(op.f('ix_knowledge_id'), table_name='knowledge')
    op.drop_table('knowledge')

