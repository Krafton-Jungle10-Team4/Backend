"""change document_embeddings bot_id to string

Revision ID: a1b2c3d4e5f6
Revises: f7e8d9c0a1b2
Create Date: 2025-11-10 01:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '1fd7615e5ca3'  # pgvector 마이그레이션 이후
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Foreign key 제약 조건 삭제
    op.drop_constraint('document_embeddings_bot_id_fkey', 'document_embeddings', type_='foreignkey')

    # 2. bot_id 컬럼 타입 변경: Integer -> String(100)
    # 기존 데이터가 있다면 문자열로 변환
    op.execute("""
        ALTER TABLE document_embeddings
        ALTER COLUMN bot_id TYPE VARCHAR(100)
        USING bot_id::VARCHAR
    """)

    # 3. 새로운 Foreign key 추가: bots.bot_id 참조
    op.create_foreign_key(
        'document_embeddings_bot_id_fkey',
        'document_embeddings',
        'bots',
        ['bot_id'],
        ['bot_id'],
        ondelete='CASCADE'
    )


def downgrade() -> None:
    # 1. Foreign key 제약 조건 삭제
    op.drop_constraint('document_embeddings_bot_id_fkey', 'document_embeddings', type_='foreignkey')

    # 2. bot_id 컬럼 타입 복원: String -> Integer
    # 주의: 데이터 손실 가능
    op.execute("""
        ALTER TABLE document_embeddings
        ALTER COLUMN bot_id TYPE INTEGER
        USING bot_id::INTEGER
    """)

    # 3. 원래 Foreign key 복원: bots.id 참조
    op.create_foreign_key(
        'document_embeddings_bot_id_fkey',
        'document_embeddings',
        'bots',
        ['bot_id'],
        ['id'],
        ondelete='CASCADE'
    )
