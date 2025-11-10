"""add draft status to bot

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2025-11-10 17:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL enum에 'draft' 추가 (소문자)
    # 참고: 초기 마이그레이션에서 이미 소문자로 생성되므로
    # 이 마이그레이션은 기존 환경을 위한 것입니다.
    op.execute("ALTER TYPE botstatus ADD VALUE IF NOT EXISTS 'draft'")


def downgrade() -> None:
    # PostgreSQL enum에서 값을 제거하는 것은 복잡하므로 경고만 출력
    # 실제로는 새로운 enum을 만들고 데이터를 마이그레이션해야 함
    pass
