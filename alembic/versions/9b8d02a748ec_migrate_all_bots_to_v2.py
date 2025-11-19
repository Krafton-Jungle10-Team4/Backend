"""migrate_all_bots_to_v2

Revision ID: 9b8d02a748ec
Revises: f87ec3d41e29
Create Date: 2025-11-19 02:49:20.178324

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9b8d02a748ec'
down_revision = 'f87ec3d41e29'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    모든 봇을 V2 워크플로우로 마이그레이션
    1. 기존 봇들의 use_workflow_v2를 True로 변경
    2. use_workflow_v2 컬럼의 기본값을 True로 변경
    """
    # 기존 봇들의 use_workflow_v2를 True로 업데이트
    op.execute("""
        UPDATE bots
        SET use_workflow_v2 = TRUE
        WHERE use_workflow_v2 = FALSE OR use_workflow_v2 IS NULL
    """)

    # use_workflow_v2 컬럼의 기본값을 True로 변경
    op.alter_column('bots', 'use_workflow_v2',
                    existing_type=sa.Boolean(),
                    server_default='true',
                    nullable=False)


def downgrade() -> None:
    """
    롤백 시 use_workflow_v2 기본값을 False로 복원
    (데이터는 복원하지 않음 - V2로 전환된 상태 유지)
    """
    op.alter_column('bots', 'use_workflow_v2',
                    existing_type=sa.Boolean(),
                    server_default='false',
                    nullable=False)
