"""add conversation variables table

Revision ID: l2m3n4o5p6q7
Revises: k0l1m2n3o4p5
Create Date: 2025-01-17 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'l2m3n4o5p6q7'
down_revision = 'k0l1m2n3o4p5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'conversation_variables',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', sa.String(length=255), nullable=False),
        sa.Column('bot_id', sa.String(length=50), nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['bot_id'], ['bots.bot_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id', 'bot_id', 'key', name='uq_conversation_variable_key')
    )
    op.create_index('ix_conversation_variables_conversation', 'conversation_variables', ['conversation_id'])
    op.create_index('ix_conversation_variables_bot', 'conversation_variables', ['bot_id'])


def downgrade() -> None:
    op.drop_index('ix_conversation_variables_bot', table_name='conversation_variables')
    op.drop_index('ix_conversation_variables_conversation', table_name='conversation_variables')
    op.drop_table('conversation_variables')
