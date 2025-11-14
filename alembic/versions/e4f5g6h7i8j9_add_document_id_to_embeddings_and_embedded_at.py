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
    # document_embeddings 테이블에 document_id 컬럼 추가 (IF NOT EXISTS for idempotency)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE document_embeddings ADD COLUMN document_id VARCHAR(36);
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
    """)

    # document_id 인덱스 생성 (IF NOT EXISTS for idempotency)
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_embeddings_document_id ON document_embeddings (document_id);")

    # documents 테이블에 embedded_at 컬럼 추가 (IF NOT EXISTS for idempotency)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE documents ADD COLUMN embedded_at TIMESTAMP WITH TIME ZONE;
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
    """)


def downgrade() -> None:
    # documents 테이블에서 embedded_at 컬럼 제거 (IF EXISTS for idempotency)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE documents DROP COLUMN embedded_at;
        EXCEPTION
            WHEN undefined_column THEN null;
        END $$;
    """)

    # document_embeddings 테이블에서 document_id 제거 (IF EXISTS for idempotency)
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_document_id;")
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE document_embeddings DROP COLUMN document_id;
        EXCEPTION
            WHEN undefined_column THEN null;
        END $$;
    """)
