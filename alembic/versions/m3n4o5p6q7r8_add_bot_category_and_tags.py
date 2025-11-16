"""add bot category and tags

Revision ID: m3n4o5p6q7r8
Revises: 711882fb6ed3
Create Date: 2025-11-16 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'm3n4o5p6q7r8'
down_revision = '711882fb6ed3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum 타입 생성 (존재하지 않는 경우에만)
    botcategory_enum = sa.Enum('workflow', 'chatflow', 'chatbot', 'agent', name='botcategory')
    botcategory_enum.create(op.get_bind(), checkfirst=True)

    # category 컬럼 추가
    op.add_column(
        'bots',
        sa.Column(
            'category',
            botcategory_enum,
            nullable=False,
            server_default='workflow'
        )
    )

    # tags 컬럼 추가
    op.add_column(
        'bots',
        sa.Column(
            'tags',
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb")
        )
    )

    # category 인덱스 추가
    op.create_index('ix_bots_category', 'bots', ['category'])


def downgrade() -> None:
    # 인덱스 삭제
    op.drop_index('ix_bots_category', table_name='bots')

    # 컬럼 삭제
    op.drop_column('bots', 'tags')
    op.drop_column('bots', 'category')

    # Enum 타입 삭제
    op.execute('DROP TYPE IF EXISTS botcategory')
