"""add llm usage and pricing tables

Revision ID: k0l1m2n3o4p5
Revises: j9k0l1m2n3o4
Create Date: 2025-11-14 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP

# revision identifiers, used by Alembic.
revision = 'k0l1m2n3o4p5'
down_revision = '9850cdd58948'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. model_pricing 테이블 생성
    op.create_table(
        'model_pricing',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('provider', sa.String(length=50), nullable=False, index=True),
        sa.Column('model_name', sa.String(length=100), nullable=False, index=True),
        sa.Column('input_price_per_1k', sa.Float(), nullable=False),
        sa.Column('output_price_per_1k', sa.Float(), nullable=False),
        sa.Column('cache_write_price_per_1k', sa.Float(), nullable=True),
        sa.Column('cache_read_price_per_1k', sa.Float(), nullable=True),
        sa.Column('region', sa.String(length=50), nullable=True),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', TIMESTAMP(timezone=True), onupdate=sa.text('now()'), nullable=True),
    )

    # model_pricing 유니크 제약 (provider + model_name)
    op.create_index(
        'idx_provider_model_unique',
        'model_pricing',
        ['provider', 'model_name'],
        unique=True
    )

    # 2. llm_usage_logs 테이블 생성
    op.create_table(
        'llm_usage_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, index=True),
        sa.Column('bot_id', sa.String(length=100), sa.ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('provider', sa.String(length=50), nullable=False, index=True),
        sa.Column('model_name', sa.String(length=100), nullable=False, index=True),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cache_read_tokens', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('cache_write_tokens', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('input_cost', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('output_cost', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_cost', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('request_id', sa.String(length=100), nullable=True, index=True),
        sa.Column('session_id', sa.String(length=100), nullable=True, index=True),
        sa.Column('created_at', TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True, index=True),
    )

    # llm_usage_logs 복합 인덱스 (성능 최적화)
    op.create_index(
        'idx_bot_created',
        'llm_usage_logs',
        ['bot_id', 'created_at']
    )
    op.create_index(
        'idx_user_created',
        'llm_usage_logs',
        ['user_id', 'created_at']
    )
    op.create_index(
        'idx_provider_model_created',
        'llm_usage_logs',
        ['provider', 'model_name', 'created_at']
    )


def downgrade() -> None:
    # llm_usage_logs 인덱스 삭제
    op.drop_index('idx_provider_model_created', table_name='llm_usage_logs')
    op.drop_index('idx_user_created', table_name='llm_usage_logs')
    op.drop_index('idx_bot_created', table_name='llm_usage_logs')

    # llm_usage_logs 테이블 삭제
    op.drop_table('llm_usage_logs')

    # model_pricing 인덱스 삭제
    op.drop_index('idx_provider_model_unique', table_name='model_pricing')

    # model_pricing 테이블 삭제
    op.drop_table('model_pricing')
