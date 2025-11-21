"""convert bots json columns to jsonb

Revision ID: 87e900e595e3
Revises: 0248ea7e10f5
Create Date: 2025-11-21 14:23:22.105663

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '87e900e595e3'
down_revision = '0248ea7e10f5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # bots 테이블의 tags 컬럼을 json → jsonb로 변경
    op.alter_column(
        'bots',
        'tags',
        type_=postgresql.JSONB(),
        existing_type=sa.JSON(),
        existing_nullable=False,
        existing_server_default=sa.text("'[]'::jsonb"),
        postgresql_using='tags::jsonb'
    )

    # bots 테이블의 workflow 컬럼을 json → jsonb로 변경
    op.alter_column(
        'bots',
        'workflow',
        type_=postgresql.JSONB(),
        existing_type=sa.JSON(),
        existing_nullable=True,
        postgresql_using='workflow::jsonb'
    )

    # bots 테이블의 legacy_workflow 컬럼을 json → jsonb로 변경
    op.alter_column(
        'bots',
        'legacy_workflow',
        type_=postgresql.JSONB(),
        existing_type=sa.JSON(),
        existing_nullable=True,
        postgresql_using='legacy_workflow::jsonb'
    )

    # tags 컬럼에 GIN 인덱스 추가 (성능 향상)
    op.execute('CREATE INDEX IF NOT EXISTS idx_bots_tags_gin ON bots USING GIN (tags)')


def downgrade() -> None:
    # GIN 인덱스 제거
    op.execute('DROP INDEX IF EXISTS idx_bots_tags_gin')

    # bots 테이블의 legacy_workflow 컬럼을 jsonb → json으로 변경
    op.alter_column(
        'bots',
        'legacy_workflow',
        type_=sa.JSON(),
        existing_type=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using='legacy_workflow::json'
    )

    # bots 테이블의 workflow 컬럼을 jsonb → json으로 변경
    op.alter_column(
        'bots',
        'workflow',
        type_=sa.JSON(),
        existing_type=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using='workflow::json'
    )

    # bots 테이블의 tags 컬럼을 jsonb → json으로 변경
    op.alter_column(
        'bots',
        'tags',
        type_=sa.JSON(),
        existing_type=postgresql.JSONB(),
        existing_nullable=False,
        existing_server_default=sa.text("'[]'::jsonb"),
        postgresql_using='tags::json'
    )
