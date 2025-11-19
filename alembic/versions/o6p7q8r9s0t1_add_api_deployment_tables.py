"""add_api_deployment_tables

Revision ID: o6p7q8r9s0t1
Revises: 814181797c5f
Create Date: 2025-11-19 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = 'o6p7q8r9s0t1'
down_revision = '814181797c5f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================
    # 1. bot_api_keys 테이블 생성
    # ==========================================
    op.create_table(
        'bot_api_keys',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('bot_id', sa.String(50), sa.ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workflow_version_id', UUID(as_uuid=True), sa.ForeignKey('bot_workflow_versions.id', ondelete='SET NULL'), nullable=True),
        
        # API Key Information
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('key_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('key_prefix', sa.String(12), nullable=False),
        sa.Column('key_suffix', sa.String(4), nullable=False),
        
        # Permissions
        sa.Column('permissions', JSONB, nullable=False, server_default='{"run": true, "read": true, "stop": true}'),
        
        # Rate Limits
        sa.Column('rate_limit_per_minute', sa.Integer, nullable=False, server_default='60'),
        sa.Column('rate_limit_per_hour', sa.Integer, nullable=False, server_default='1000'),
        sa.Column('rate_limit_per_day', sa.Integer, nullable=False, server_default='10000'),
        
        # Quotas
        sa.Column('monthly_request_quota', sa.Integer, nullable=True),
        sa.Column('monthly_token_quota', sa.Integer, nullable=True),
        
        # Lifecycle
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        
        # Binding
        sa.Column('bind_to_latest_published', sa.Boolean, nullable=False, server_default='true'),
        
        # Metadata
        sa.Column('allowed_ips', JSONB, nullable=True),
        sa.Column('metadata', JSONB, nullable=False, server_default='{}'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    
    # bot_api_keys 인덱스
    op.create_index('idx_bot_api_key_hash', 'bot_api_keys', ['key_hash'])
    op.create_index('idx_bot_api_key_bot_active', 'bot_api_keys', ['bot_id', 'is_active'])
    op.create_index('idx_bot_api_key_user', 'bot_api_keys', ['user_id'])

    # ==========================================
    # 2. api_key_usage 테이블 생성
    # ==========================================
    op.create_table(
        'api_key_usage',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('api_key_id', UUID(as_uuid=True), sa.ForeignKey('bot_api_keys.id', ondelete='CASCADE'), nullable=False),
        sa.Column('timestamp_hour', sa.DateTime(timezone=True), nullable=False),
        
        # Request Metrics
        sa.Column('total_requests', sa.Integer, nullable=False, server_default='0'),
        sa.Column('successful_requests', sa.Integer, nullable=False, server_default='0'),
        sa.Column('failed_requests', sa.Integer, nullable=False, server_default='0'),
        
        # Workflow Execution Metrics
        sa.Column('workflow_runs_created', sa.Integer, nullable=False, server_default='0'),
        sa.Column('workflow_runs_completed', sa.Integer, nullable=False, server_default='0'),
        sa.Column('workflow_runs_failed', sa.Integer, nullable=False, server_default='0'),
        
        # Token Usage
        sa.Column('prompt_tokens', sa.Integer, nullable=False, server_default='0'),
        sa.Column('completion_tokens', sa.Integer, nullable=False, server_default='0'),
        sa.Column('total_tokens', sa.Integer, nullable=False, server_default='0'),
        
        # Performance
        sa.Column('avg_latency_ms', sa.Integer, nullable=True),
        sa.Column('p95_latency_ms', sa.Integer, nullable=True),
    )
    
    # api_key_usage 인덱스
    op.create_index('idx_usage_key_time', 'api_key_usage', ['api_key_id', 'timestamp_hour'])
    op.create_index('uq_usage_key_hour', 'api_key_usage', ['api_key_id', 'timestamp_hour'], unique=True)

    # ==========================================
    # 3. workflow_execution_runs 테이블에 컬럼 추가
    # ==========================================
    op.add_column('workflow_execution_runs', 
        sa.Column('api_key_id', UUID(as_uuid=True), sa.ForeignKey('bot_api_keys.id', ondelete='SET NULL'), nullable=True)
    )
    op.add_column('workflow_execution_runs', 
        sa.Column('api_request_id', sa.String(64), nullable=True)
    )
    op.create_index('idx_execution_api_key', 'workflow_execution_runs', ['api_key_id'])
    op.create_index('idx_execution_api_request_id', 'workflow_execution_runs', ['api_request_id'])

    # ==========================================
    # 4. bot_workflow_versions 테이블에 API 배포 필드 추가
    # ==========================================
    op.add_column('bot_workflow_versions', 
        sa.Column('api_endpoint_alias', sa.String(100), nullable=True)
    )
    op.add_column('bot_workflow_versions', 
        sa.Column('api_default_response_mode', sa.String(20), nullable=False, server_default='blocking')
    )
    
    # partial unique index for api_endpoint_alias (NULL 제외)
    op.create_index(
        'idx_workflow_version_alias', 
        'bot_workflow_versions', 
        ['api_endpoint_alias'], 
        unique=True, 
        postgresql_where=sa.text("api_endpoint_alias IS NOT NULL")
    )


def downgrade() -> None:
    # bot_workflow_versions 인덱스 및 컬럼 삭제
    op.drop_index('idx_workflow_version_alias', 'bot_workflow_versions')
    op.drop_column('bot_workflow_versions', 'api_default_response_mode')
    op.drop_column('bot_workflow_versions', 'api_endpoint_alias')
    
    # workflow_execution_runs 인덱스 및 컬럼 삭제
    op.drop_index('idx_execution_api_request_id', 'workflow_execution_runs')
    op.drop_index('idx_execution_api_key', 'workflow_execution_runs')
    op.drop_column('workflow_execution_runs', 'api_request_id')
    op.drop_column('workflow_execution_runs', 'api_key_id')
    
    # api_key_usage 테이블 삭제
    op.drop_index('uq_usage_key_hour', 'api_key_usage')
    op.drop_index('idx_usage_key_time', 'api_key_usage')
    op.drop_table('api_key_usage')
    
    # bot_api_keys 테이블 삭제
    op.drop_index('idx_bot_api_key_user', 'bot_api_keys')
    op.drop_index('idx_bot_api_key_bot_active', 'bot_api_keys')
    op.drop_index('idx_bot_api_key_hash', 'bot_api_keys')
    op.drop_table('bot_api_keys')

