"""add_user_uuid

Revision ID: c1a2b3c4d5e6
Revises: 9b654bea4bf6
Create Date: 2025-11-08 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
import uuid

# revision identifiers, used by Alembic.
revision = 'c1a2b3c4d5e6'
down_revision = '9b654bea4bf6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """User 테이블에 uuid 컬럼 추가"""
    # 1. uuid 컬럼 추가 (nullable=True로 시작)
    op.add_column('users',
        sa.Column('uuid', sa.String(length=36), nullable=True)
    )

    # 2. 기존 사용자에게 UUID 생성
    connection = op.get_bind()
    result = connection.execute(text("SELECT id FROM users"))

    for row in result:
        user_uuid = str(uuid.uuid4())
        connection.execute(
            text("UPDATE users SET uuid = :uuid WHERE id = :id"),
            {"uuid": user_uuid, "id": row.id}
        )

    # 3. NOT NULL 제약 조건 설정
    op.alter_column('users', 'uuid', nullable=False)

    # 4. UNIQUE 인덱스 생성
    op.create_index(op.f('ix_users_uuid'), 'users', ['uuid'], unique=True)


def downgrade() -> None:
    """uuid 컬럼 제거"""
    op.drop_index(op.f('ix_users_uuid'), table_name='users')
    op.drop_column('users', 'uuid')
