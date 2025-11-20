"""add_slack_integrations_table

Revision ID: p7q8r9s0t1u2
Revises: ab5c2f8c6724
Create Date: 2025-11-20 12:34:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = 'p7q8r9s0t1u2'
down_revision = 'ab5c2f8c6724'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================
    # slack_integrations 테이블 생성
    # ==========================================
    op.create_table(
        'slack_integrations',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('bot_id', sa.String(50), sa.ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=True, index=True),
        
        # OAuth 정보 (암호화 저장)
        sa.Column('access_token', sa.Text, nullable=False),  # 암호화된 토큰
        
        # Workspace 정보
        sa.Column('workspace_id', sa.String(255), nullable=False),
        sa.Column('workspace_name', sa.String(255), nullable=False),
        sa.Column('workspace_icon', sa.String(500), nullable=True),
        
        # Bot 정보
        sa.Column('bot_user_id', sa.String(255), nullable=True),
        
        # 권한 범위
        sa.Column('scopes', JSONB, nullable=False, server_default='[]'),
        
        # 상태
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        
        # 타임스탬프
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('now()')),
        sa.Column('expires_at', sa.DateTime, nullable=True),  # 토큰 만료 시간 (있는 경우)
    )
    
    # 인덱스 생성
    op.create_index('idx_slack_integration_user', 'slack_integrations', ['user_id'])
    op.create_index('idx_slack_integration_bot', 'slack_integrations', ['bot_id'])
    op.create_index('idx_slack_integration_user_bot_active', 'slack_integrations', ['user_id', 'bot_id', 'is_active'])
    op.create_index('idx_slack_integration_workspace', 'slack_integrations', ['workspace_id'])


def downgrade() -> None:
    # 인덱스 삭제
    op.drop_index('idx_slack_integration_workspace', 'slack_integrations')
    op.drop_index('idx_slack_integration_user_bot_active', 'slack_integrations')
    op.drop_index('idx_slack_integration_bot', 'slack_integrations')
    op.drop_index('idx_slack_integration_user', 'slack_integrations')
    
    # 테이블 삭제
    op.drop_table('slack_integrations')

