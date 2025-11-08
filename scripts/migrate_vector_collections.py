"""
VectorStore 컬렉션 마이그레이션: team_{uuid} → user_{uuid}

⚠️ 실행 조건:
- alembic upgrade c1a2b3c4d5e6 완료 (User.uuid 존재)
- teams 테이블이 아직 존재해야 함
- 팀 제거 마이그레이션 실행 전

실행 방법:
    python Backend/scripts/migrate_vector_collections.py
"""
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    import chromadb
    from sqlalchemy import create_engine, text
    from app.config import settings
except ImportError as e:
    print(f"❌ 오류: 필요한 패키지를 import할 수 없습니다: {e}")
    print("pip install chromadb sqlalchemy를 실행하세요.")
    sys.exit(1)


def verify_preconditions(engine):
    """사전 조건 검증"""
    with engine.connect() as conn:
        # User.uuid 존재 확인
        try:
            result = conn.execute(text("SELECT uuid FROM users LIMIT 1"))
            result.fetchone()
            print("✅ users.uuid 컬럼 존재 확인")
        except Exception as e:
            print(f"❌ 오류: users.uuid 컬럼이 없습니다.")
            print(f"   상세: {e}")
            print("   먼저 'alembic upgrade c1a2b3c4d5e6'을 실행하세요.")
            sys.exit(1)

        # teams 테이블 존재 확인
        try:
            result = conn.execute(text("SELECT id FROM teams LIMIT 1"))
            result.fetchone()
            print("✅ teams 테이블 존재 확인")
        except Exception as e:
            print(f"❌ 오류: teams 테이블이 없습니다.")
            print(f"   이미 팀 제거 마이그레이션을 실행했습니다.")
            print(f"   상세: {e}")
            sys.exit(1)

        print("✅ 사전 조건 확인 완료\n")


def migrate_vector_collections():
    """VectorStore 컬렉션 마이그레이션 실행"""
    print("=" * 60)
    print("VectorStore 컬렉션 마이그레이션 시작")
    print("=" * 60)

    # DB 연결
    try:
        engine = create_engine(settings.database_url)
        print(f"✅ DB 연결 성공: {settings.database_url.split('@')[-1]}\n")
    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        sys.exit(1)

    # 사전 조건 검증
    verify_preconditions(engine)

    # ChromaDB 클라이언트 초기화
    try:
        chroma_client = chromadb.PersistentClient(
            path=settings.chroma_persist_directory
        )
        print(f"✅ ChromaDB 연결 성공: {settings.chroma_persist_directory}\n")
    except Exception as e:
        print(f"❌ ChromaDB 연결 실패: {e}")
        sys.exit(1)

    # team → user 매핑 조회
    with engine.connect() as conn:
        try:
            result = conn.execute(text("""
                SELECT DISTINCT
                    t.uuid as team_uuid,
                    u.uuid as user_uuid
                FROM teams t
                JOIN team_members tm ON tm.team_id = t.id AND tm.role = 'OWNER'
                JOIN users u ON u.id = tm.user_id
                ORDER BY t.uuid
            """))

            mappings = list(result.fetchall())

            if not mappings:
                print("⚠️  마이그레이션할 컬렉션이 없습니다.")
                print("   (팀이 없거나 owner가 없는 팀만 존재)")
                return

            print(f"📊 {len(mappings)}개 팀-사용자 매핑 발견\n")

        except Exception as e:
            print(f"❌ 팀-사용자 매핑 조회 실패: {e}")
            sys.exit(1)

    # 컬렉션 마이그레이션
    success_count = 0
    skip_count = 0
    error_count = 0

    for team_uuid, user_uuid in mappings:
        old_name = f"team_{team_uuid}"
        new_name = f"user_{user_uuid}"

        try:
            # 기존 컬렉션 확인
            old_collection = chroma_client.get_collection(old_name)

            # 새 컬렉션 생성
            new_collection = chroma_client.create_collection(new_name)

            # 데이터 복사
            all_data = old_collection.get()

            if all_data['ids'] and len(all_data['ids']) > 0:
                new_collection.add(
                    ids=all_data['ids'],
                    documents=all_data['documents'],
                    embeddings=all_data['embeddings'],
                    metadatas=all_data['metadatas']
                )
                print(f"  ✅ {old_name} → {new_name} ({len(all_data['ids'])} items)")
            else:
                print(f"  ✅ {old_name} → {new_name} (empty collection)")

            # 구 컬렉션 삭제
            chroma_client.delete_collection(old_name)
            success_count += 1

        except ValueError as e:
            # 컬렉션이 없으면 스킵
            if "does not exist" in str(e) or "not found" in str(e).lower():
                print(f"  ⏭️  {old_name} 컬렉션 없음 (스킵)")
                skip_count += 1
            else:
                print(f"  ❌ {old_name} 실패: {e}")
                error_count += 1
        except Exception as e:
            print(f"  ❌ {old_name} 실패: {e}")
            error_count += 1

    # 결과 요약
    print("\n" + "=" * 60)
    print("마이그레이션 완료")
    print("=" * 60)
    print(f"성공: {success_count}개")
    print(f"스킵: {skip_count}개")
    print(f"실패: {error_count}개")

    if error_count > 0:
        print("\n⚠️  일부 컬렉션 마이그레이션 실패")
        print("   실패한 컬렉션은 수동으로 확인이 필요합니다.")
        sys.exit(1)
    else:
        print("\n✅ 모든 컬렉션 마이그레이션 성공")


if __name__ == "__main__":
    try:
        migrate_vector_collections()
    except KeyboardInterrupt:
        print("\n\n❌ 사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 예상치 못한 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
