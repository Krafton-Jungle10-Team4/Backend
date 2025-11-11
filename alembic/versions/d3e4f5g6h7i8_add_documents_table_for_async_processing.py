"""add documents table for async processing

Revision ID: d3e4f5g6h7i8
Revises: c2d3e4f5g6h7
Create Date: 2025-11-11 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'd3e4f5g6h7i8'
down_revision = 'c2d3e4f5g6h7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DocumentStatus enum 타입 생성
    documentstatus_enum = postgresql.ENUM(
        'uploaded', 'queued', 'processing', 'done', 'failed',
        name='documentstatus'
    )
    documentstatus_enum.create(op.get_bind(), checkfirst=True)

    # documents 테이블 생성
    op.create_table(
        'documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.String(length=36), nullable=False),
        sa.Column('bot_id', sa.String(length=50), nullable=False),
        sa.Column('user_uuid', sa.String(length=36), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('file_extension', sa.String(length=10), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('s3_uri', sa.Text(), nullable=True),
        sa.Column('status', documentstatus_enum, nullable=False, server_default='queued'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('chunk_count', sa.Integer(), nullable=True),
        sa.Column('processing_time', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # 인덱스 생성
    op.create_index('ix_documents_id', 'documents', ['id'])
    op.create_index('ix_documents_document_id', 'documents', ['document_id'], unique=True)
    op.create_index('ix_documents_bot_id', 'documents', ['bot_id'])
    op.create_index('ix_documents_user_uuid', 'documents', ['user_uuid'])
    op.create_index('ix_documents_status', 'documents', ['status'])
    op.create_index('ix_documents_created_at', 'documents', ['created_at'])


def downgrade() -> None:
    # 인덱스 삭제
    op.drop_index('ix_documents_created_at', table_name='documents')
    op.drop_index('ix_documents_status', table_name='documents')
    op.drop_index('ix_documents_user_uuid', table_name='documents')
    op.drop_index('ix_documents_bot_id', table_name='documents')
    op.drop_index('ix_documents_document_id', table_name='documents')
    op.drop_index('ix_documents_id', table_name='documents')

    # 테이블 삭제
    op.drop_table('documents')

    # Enum 타입 삭제
    documentstatus_enum = postgresql.ENUM(
        'uploaded', 'queued', 'processing', 'done', 'failed',
        name='documentstatus'
    )
    documentstatus_enum.drop(op.get_bind(), checkfirst=True)
