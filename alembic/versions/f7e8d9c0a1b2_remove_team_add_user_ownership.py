"""remove_team_add_user_ownership

Revision ID: f7e8d9c0a1b2
Revises: c1a2b3c4d5e6
Create Date: 2025-11-08 10:30:00.000000

⚠️ 실행 전 필수 조건:
1. alembic upgrade c1a2b3c4d5e6 완료 (User.uuid 추가됨)
2. python Backend/scripts/migrate_vector_collections.py 실행 완료
3. VectorStore 컬렉션 마이그레이션 성공 확인

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f7e8d9c0a1b2'
down_revision = 'c1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """팀 관련 테이블 제거 및 user_id 기반으로 전환"""
    connection = op.get_bind()

    print("\n" + "=" * 70)
    print("팀 제거 마이그레이션 시작")
    print("=" * 70)

    # ========== 1. bots 테이블 수정 ==========
    print("\n[1/5] bots 테이블 수정 중...")

    # 1-1. user_id 컬럼 추가
    op.add_column('bots',
        sa.Column('user_id', sa.Integer(), nullable=True)
    )
    print("  ✅ bots.user_id 컬럼 추가")

    # 1-2. Bot user_id 매핑 (owner 우선)
    result = connection.execute(text("""
        UPDATE bots b
        SET user_id = (
            SELECT tm.user_id
            FROM team_members tm
            WHERE tm.team_id = b.team_id
            AND tm.role = 'OWNER'
            LIMIT 1
        )
    """))
    print(f"  ✅ Bot user_id 매핑 완료 (owner 기준)")

    # 1-3. 예외: owner 없는 팀 → 첫 멤버
    result = connection.execute(text("""
        UPDATE bots b
        SET user_id = (
            SELECT tm.user_id
            FROM team_members tm
            WHERE tm.team_id = b.team_id
            ORDER BY tm.joined_at ASC
            LIMIT 1
        )
        WHERE b.user_id IS NULL
    """))
    print(f"  ✅ Owner 없는 팀 처리 완료 (첫 멤버로 매핑)")

    # 1-4. 검증: 고아 Bot 확인
    result = connection.execute(text("SELECT COUNT(*) FROM bots WHERE user_id IS NULL"))
    orphan_count = result.scalar()
    if orphan_count > 0:
        raise Exception(f"❌ 마이그레이션 실패: {orphan_count}개 Bot에 user_id 할당 실패")
    print(f"  ✅ 고아 Bot 없음 확인")

    # 1-5. FK 및 인덱스 설정
    op.alter_column('bots', 'user_id', nullable=False)
    op.create_foreign_key(
        'fk_bots_user_id',
        'bots', 'users',
        ['user_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_index(op.f('ix_bots_user_id'), 'bots', ['user_id'])
    print("  ✅ bots.user_id FK 및 인덱스 생성")

    # 1-6. team_id 제거
    op.drop_constraint('bots_team_id_fkey', 'bots', type_='foreignkey')
    op.drop_column('bots', 'team_id')
    print("  ✅ bots.team_id 제거 완료")

    # ========== 2. api_keys 테이블 수정 ==========
    print("\n[2/5] api_keys 테이블 수정 중...")

    # 2-1. user_id 컬럼 추가
    op.add_column('api_keys',
        sa.Column('user_id', sa.Integer(), nullable=True)
    )
    print("  ✅ api_keys.user_id 컬럼 추가")

    # 2-2. APIKey user_id 매핑 (owner 우선)
    connection.execute(text("""
        UPDATE api_keys ak
        SET user_id = (
            SELECT tm.user_id
            FROM team_members tm
            WHERE tm.team_id = ak.team_id
            AND tm.role = 'OWNER'
            LIMIT 1
        )
    """))
    print("  ✅ APIKey user_id 매핑 완료 (owner 기준)")

    # 2-3. 예외: owner 없는 팀 → 첫 멤버
    connection.execute(text("""
        UPDATE api_keys ak
        SET user_id = (
            SELECT tm.user_id
            FROM team_members tm
            WHERE tm.team_id = ak.team_id
            ORDER BY tm.joined_at ASC
            LIMIT 1
        )
        WHERE ak.user_id IS NULL
    """))
    print("  ✅ Owner 없는 팀 APIKey 처리 완료")

    # 2-4. FK 및 인덱스 설정
    op.alter_column('api_keys', 'user_id', nullable=False)
    op.create_foreign_key(
        'fk_api_keys_user_id',
        'api_keys', 'users',
        ['user_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_index(op.f('ix_api_keys_user_id'), 'api_keys', ['user_id'])
    print("  ✅ api_keys.user_id FK 및 인덱스 생성")

    # 2-5. team_id 제거
    op.drop_constraint('api_keys_team_id_fkey', 'api_keys', type_='foreignkey')
    op.drop_column('api_keys', 'team_id')
    print("  ✅ api_keys.team_id 제거 완료")

    # ========== 3. User 모델에서 team_memberships relationship 제거 준비 ==========
    print("\n[3/5] User 테이블 정리 중...")
    # (relationship은 모델 코드에서 제거, DB 스키마 변경 불필요)
    print("  ✅ User 모델 준비 완료 (relationship은 코드에서 제거)")

    # ========== 4. 팀 관련 테이블 삭제 ==========
    print("\n[4/5] 팀 관련 테이블 삭제 중...")

    # invite_tokens 삭제
    op.drop_index(op.f('ix_invite_tokens_token'), table_name='invite_tokens')
    op.drop_index(op.f('ix_invite_tokens_id'), table_name='invite_tokens')
    op.drop_table('invite_tokens')
    print("  ✅ invite_tokens 테이블 삭제")

    # team_members 삭제
    op.drop_index(op.f('ix_team_members_id'), table_name='team_members')
    op.drop_table('team_members')
    print("  ✅ team_members 테이블 삭제")

    # teams 삭제
    op.drop_index(op.f('ix_teams_uuid'), table_name='teams')
    op.drop_index(op.f('ix_teams_id'), table_name='teams')
    op.drop_table('teams')
    print("  ✅ teams 테이블 삭제")

    # ========== 5. 최종 검증 ==========
    print("\n[5/5] 최종 검증 중...")

    # Bot 검증
    result = connection.execute(text("SELECT COUNT(*) FROM bots"))
    bot_count = result.scalar()
    print(f"  ✅ Bot 총 {bot_count}개 (모두 user_id 보유)")

    # APIKey 검증
    result = connection.execute(text("SELECT COUNT(*) FROM api_keys"))
    key_count = result.scalar()
    print(f"  ✅ APIKey 총 {key_count}개 (모두 user_id 보유)")

    print("\n" + "=" * 70)
    print("✅ 팀 제거 마이그레이션 완료")
    print("=" * 70)


def downgrade() -> None:
    """롤백 불가능"""
    raise Exception(
        "이 마이그레이션은 데이터 손실로 인해 롤백을 지원하지 않습니다.\n"
        "백업에서 복원하세요."
    )
