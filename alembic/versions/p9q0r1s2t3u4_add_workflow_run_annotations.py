"""add workflow run annotations

Revision ID: p9q0r1s2t3u4
Revises: ('n4o5p6q7r8s9', 'f7e8d9c0a1b2')
Create Date: 2025-02-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = 'p9q0r1s2t3u4'
down_revision = ('n4o5p6q7r8s9', 'f7e8d9c0a1b2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workflow_run_annotations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workflow_run_id', UUID(as_uuid=True), sa.ForeignKey('workflow_execution_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('bot_id', sa.String(length=50), sa.ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('annotation', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('workflow_run_id', 'user_id', name='uq_workflow_run_annotations_user')
    )

    op.create_index(
        'ix_workflow_run_annotations_run_id',
        'workflow_run_annotations',
        ['workflow_run_id']
    )
    op.create_index(
        'ix_workflow_run_annotations_bot_id',
        'workflow_run_annotations',
        ['bot_id']
    )


def downgrade() -> None:
    op.drop_index('ix_workflow_run_annotations_bot_id', table_name='workflow_run_annotations')
    op.drop_index('ix_workflow_run_annotations_run_id', table_name='workflow_run_annotations')
    op.drop_table('workflow_run_annotations')
