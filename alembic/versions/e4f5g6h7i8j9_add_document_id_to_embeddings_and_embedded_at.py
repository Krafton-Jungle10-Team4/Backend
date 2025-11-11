"""add document_id to embeddings and embedded_at to documents

Revision ID: e4f5g6h7i8j9
Revises: d3e4f5g6h7i8
Create Date: 2025-11-11 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e4f5g6h7i8j9'
down_revision = 'd3e4f5g6h7i8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # document_embeddings 테이블에 document_id 컬럼 추가
    op.add_column('document_embeddings',
        sa.Column('document_id', sa.String(length=36), nullable=True, comment='documents 테이블의 document_id')
    )
    op.create_index(
        op.f('ix_document_embeddings_document_id'),
        'document_embeddings',
        ['document_id'],
        unique=False
    )

    # documents 테이블에 embedded_at 컬럼 추가
    op.add_column('documents',
        sa.Column('embedded_at', sa.DateTime(timezone=True), nullable=True, comment='임베딩 완료 시간 (Workflow에서 실행)')
    )


def downgrade() -> None:
    # documents 테이블에서 embedded_at 컬럼 제거
    op.drop_column('documents', 'embedded_at')

    # document_embeddings 테이블에서 document_id 컬럼 제거
    op.drop_index(op.f('ix_document_embeddings_document_id'), table_name='document_embeddings')
    op.drop_column('document_embeddings', 'document_id')
