"""add workflow v2 tables

Revision ID: j9k0l1m2n3o4
Revises: d3e4f5g6h7i8
Create Date: 2025-11-13 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = 'j9k0l1m2n3o4'
down_revision = 'e4f5g6h7i8j9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Bot 테이블에 V2 필드 추가
    op.add_column('bots', sa.Column('use_workflow_v2', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('bots', sa.Column('legacy_workflow', JSONB, nullable=True))

    # 2. 워크플로우 버전 테이블 생성
    op.create_table(
        'bot_workflow_versions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('bot_id', sa.String(length=50), sa.ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),

        sa.Column('graph', JSONB, nullable=False),
        sa.Column('environment_variables', JSONB, server_default='{}'),
        sa.Column('conversation_variables', JSONB, server_default='{}'),
        sa.Column('features', JSONB, server_default='{}'),

        sa.Column('created_by', sa.String(length=36), sa.ForeignKey('users.uuid')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),

        sa.UniqueConstraint('bot_id', 'version', name='uq_bot_workflow_version')
    )

    op.create_index('idx_bot_workflow_versions_bot_id', 'bot_workflow_versions', ['bot_id'])
    op.create_index('idx_bot_workflow_versions_status', 'bot_workflow_versions', ['bot_id', 'status'])

    # 3. 실행 기록 테이블 생성
    op.create_table(
        'workflow_execution_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('bot_id', sa.String(length=50), sa.ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False),
        sa.Column('workflow_version_id', UUID(as_uuid=True), sa.ForeignKey('bot_workflow_versions.id')),
        sa.Column('session_id', sa.String(255)),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('users.uuid')),

        sa.Column('graph_snapshot', JSONB, nullable=False),
        sa.Column('inputs', JSONB),
        sa.Column('outputs', JSONB),

        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error_message', sa.Text),

        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('elapsed_time', sa.Integer),
        sa.Column('total_tokens', sa.Integer, server_default='0'),
        sa.Column('total_steps', sa.Integer, server_default='0'),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )

    op.create_index('idx_workflow_runs_bot_id', 'workflow_execution_runs', ['bot_id'])
    op.create_index('idx_workflow_runs_session', 'workflow_execution_runs', ['session_id'])
    op.create_index('idx_workflow_runs_created_at', 'workflow_execution_runs', ['created_at'], postgresql_using='btree')

    # 4. 노드 실행 기록 테이블
    op.create_table(
        'workflow_node_executions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workflow_run_id', UUID(as_uuid=True), sa.ForeignKey('workflow_execution_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.String(255), nullable=False),
        sa.Column('node_type', sa.String(50), nullable=False),
        sa.Column('execution_order', sa.Integer),

        sa.Column('inputs', JSONB),
        sa.Column('outputs', JSONB),
        sa.Column('process_data', JSONB),

        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error_message', sa.Text),

        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('elapsed_time', sa.Integer),
        sa.Column('tokens_used', sa.Integer, server_default='0'),

        sa.Column('is_truncated', sa.Boolean, server_default='false'),
        sa.Column('truncated_fields', JSONB),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )

    op.create_index('idx_node_exec_run_id', 'workflow_node_executions', ['workflow_run_id'])


def downgrade() -> None:
    op.drop_table('workflow_node_executions')
    op.drop_table('workflow_execution_runs')
    op.drop_table('bot_workflow_versions')
    op.drop_column('bots', 'legacy_workflow')
    op.drop_column('bots', 'use_workflow_v2')
