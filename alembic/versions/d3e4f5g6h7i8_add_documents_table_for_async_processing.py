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
    # DocumentStatus enum 타입 생성 (IF NOT EXISTS for idempotency)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE documentstatus AS ENUM ('uploaded', 'queued', 'processing', 'done', 'failed');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # documents 테이블 생성 (IF NOT EXISTS for idempotency)
    op.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id SERIAL PRIMARY KEY,
            document_id VARCHAR(36) NOT NULL,
            bot_id VARCHAR(50) NOT NULL,
            user_uuid VARCHAR(36) NOT NULL,
            original_filename VARCHAR(255) NOT NULL,
            file_extension VARCHAR(10) NOT NULL,
            file_size INTEGER NOT NULL,
            s3_uri TEXT,
            status documentstatus DEFAULT 'queued' NOT NULL,
            error_message TEXT,
            retry_count INTEGER DEFAULT 0 NOT NULL,
            chunk_count INTEGER,
            processing_time INTEGER,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE,
            queued_at TIMESTAMP WITH TIME ZONE,
            processing_started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE
        );
    """)

    # 인덱스 생성 (IF NOT EXISTS for idempotency)
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_id ON documents (id);")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_documents_document_id ON documents (document_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_bot_id ON documents (bot_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_user_uuid ON documents (user_uuid);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_status ON documents (status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_created_at ON documents (created_at);")


def downgrade() -> None:
    # 인덱스 삭제 (IF EXISTS for idempotency)
    op.execute("DROP INDEX IF EXISTS ix_documents_created_at;")
    op.execute("DROP INDEX IF EXISTS ix_documents_status;")
    op.execute("DROP INDEX IF EXISTS ix_documents_user_uuid;")
    op.execute("DROP INDEX IF EXISTS ix_documents_bot_id;")
    op.execute("DROP INDEX IF EXISTS ix_documents_document_id;")
    op.execute("DROP INDEX IF EXISTS ix_documents_id;")

    # 테이블 삭제 (IF EXISTS for idempotency)
    op.execute("DROP TABLE IF EXISTS documents CASCADE;")

    # Enum 타입 삭제 (IF EXISTS for idempotency)
    op.execute("DROP TYPE IF EXISTS documentstatus;")
