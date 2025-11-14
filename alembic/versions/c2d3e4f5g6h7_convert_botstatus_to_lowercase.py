"""convert botstatus to lowercase

Revision ID: c2d3e4f5g6h7
Revises: b2c3d4e5f6g7
Create Date: 2025-11-10 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2d3e4f5g6h7'
down_revision = 'b2c3d4e5f6g7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    botstatus enum 값을 대문자에서 소문자로 변환

    단계:
    0. 기존 기본값 제거 (타입 변환을 위해)
    1. 기존 enum 타입을 botstatus_old로 이름 변경
    2. 소문자 값으로 새 botstatus enum 생성
    3. bots.status 컬럼을 새 타입으로 변환 (기존 데이터는 소문자로 변환)
    4. 기존 botstatus_old 타입 삭제
    5. 기본값을 'draft'로 재설정
    """

    # 0. 기본값 제거 (타입 변환 전에 필요)
    op.execute("ALTER TABLE bots ALTER COLUMN status DROP DEFAULT")

    # 1. 기존 타입을 botstatus_old로 rename
    op.execute("ALTER TYPE botstatus RENAME TO botstatus_old")

    # 2. 소문자 값으로 새 enum 생성
    op.execute("CREATE TYPE botstatus AS ENUM ('draft', 'active', 'inactive', 'error')")

    # 3. bots.status 컬럼을 새 타입으로 변환 (기존 값을 소문자로)
    op.execute("""
        ALTER TABLE bots
        ALTER COLUMN status TYPE botstatus
        USING lower(status::text)::botstatus
    """)

    # 4. 기존 타입 삭제
    op.execute("DROP TYPE botstatus_old")

    # 5. 기본값 재설정
    op.execute("ALTER TABLE bots ALTER COLUMN status SET DEFAULT 'draft'::botstatus")


def downgrade() -> None:
    """
    소문자에서 대문자로 롤백

    주의: 이 작업은 기존 데이터를 대문자로 변환합니다.
    """

    # 0. 기본값 제거 (타입 변환 전에 필요)
    op.execute("ALTER TABLE bots ALTER COLUMN status DROP DEFAULT")

    # 1. 기존 타입을 botstatus_old로 rename
    op.execute("ALTER TYPE botstatus RENAME TO botstatus_old")

    # 2. 대문자 값으로 새 enum 생성
    op.execute("CREATE TYPE botstatus AS ENUM ('DRAFT', 'ACTIVE', 'INACTIVE', 'ERROR')")

    # 3. bots.status 컬럼을 새 타입으로 변환 (기존 값을 대문자로)
    op.execute("""
        ALTER TABLE bots
        ALTER COLUMN status TYPE botstatus
        USING upper(status::text)::botstatus
    """)

    # 4. 기존 타입 삭제
    op.execute("DROP TYPE botstatus_old")

    # 5. 기본값 재설정
    op.execute("ALTER TABLE bots ALTER COLUMN status SET DEFAULT 'DRAFT'::botstatus")
