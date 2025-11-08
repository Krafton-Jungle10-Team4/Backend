"""add pgvector support

Revision ID: 1fd7615e5ca3
Revises: f7e8d9c0a1b2
Create Date: 2025-11-09 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1fd7615e5ca3'
down_revision: Union[str, None] = 'f7e8d9c0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector 확장 활성화 (이미 활성화되어 있으면 무시)
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # document_embeddings 테이블 생성
    op.create_table(
        'document_embeddings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bot_id', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False, comment='분할된 텍스트 청크'),
        sa.Column('chunk_index', sa.Integer(), nullable=False, comment='청크 인덱스 (순서)'),
        sa.Column('embedding', postgresql.ARRAY(sa.Float()), nullable=False, comment='1024차원 임베딩 벡터'),
        sa.Column('metadata', sa.JSON(), nullable=True, comment='소스 파일명, 페이지 번호 등'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 인덱스 생성
    op.create_index(op.f('ix_document_embeddings_bot_id'), 'document_embeddings', ['bot_id'], unique=False)

    # 벡터 검색 인덱스 생성 (HNSW - 빠른 근사 검색)
    # pgvector의 vector 타입을 사용하려면 먼저 컬럼 타입을 변경해야 함
    op.execute("""
        ALTER TABLE document_embeddings
        ALTER COLUMN embedding TYPE vector(1024)
        USING embedding::vector(1024)
    """)

    # HNSW 인덱스 생성 (코사인 유사도 검색)
    op.execute("""
        CREATE INDEX ON document_embeddings
        USING hnsw (embedding vector_cosine_ops)
    """)


def downgrade() -> None:
    # 테이블 삭제
    op.drop_index(op.f('ix_document_embeddings_bot_id'), table_name='document_embeddings')
    op.drop_table('document_embeddings')

    # pgvector 확장 제거 (주의: 다른 테이블에서 사용 중이면 실패)
    # 개발 환경에서만 실행하고, 프로덕션에서는 수동으로 처리 권장
    # op.execute('DROP EXTENSION IF EXISTS vector')
