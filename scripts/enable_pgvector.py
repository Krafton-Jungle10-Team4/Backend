#!/usr/bin/env python3
"""
Aurora PostgreSQL에서 pgvector 확장 활성화 스크립트

사용법:
    python scripts/enable_pgvector.py

환경 변수 필요:
    - POSTGRES_HOST (또는 config.py의 설정)
    - POSTGRES_DB
    - POSTGRES_USER
    - POSTGRES_PASSWORD
"""

import sys
import os
from pathlib import Path

# Backend 디렉토리를 Python 경로에 추가
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import psycopg2
from app.config import settings


def enable_pgvector():
    """pgvector 확장 활성화"""

    print("=" * 60)
    print("pgvector 확장 활성화 스크립트")
    print("=" * 60)
    print()

    # 연결 정보 출력
    print(f"데이터베이스: {settings.database_url}")
    print(f"호스트: {settings.postgres_host}")
    print(f"포트: {settings.postgres_port}")
    print(f"데이터베이스명: {settings.postgres_db}")
    print()

    conn = None
    cursor = None

    try:
        # PostgreSQL 연결 (psycopg2 사용, Alembic migration용)
        print("PostgreSQL 연결 중...")
        conn = psycopg2.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            database=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password
        )
        conn.autocommit = True
        cursor = conn.cursor()
        print("✅ 연결 성공")
        print()

        # PostgreSQL 버전 확인
        print("PostgreSQL 버전 확인 중...")
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        print(f"✅ 버전: {version}")
        print()

        # Aurora 버전 확인 (Aurora인 경우)
        if "aurora" in version.lower():
            print("🌟 Aurora PostgreSQL 감지")
            cursor.execute("SHOW aurora_version;")
            aurora_version = cursor.fetchone()[0]
            print(f"✅ Aurora 버전: {aurora_version}")
            print()

        # pgvector 확장 활성화
        print("pgvector 확장 활성화 중...")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        print("✅ pgvector 확장 활성화 완료")
        print()

        # 설치 확인
        print("pgvector 설치 확인 중...")
        cursor.execute("""
            SELECT extname, extversion
            FROM pg_extension
            WHERE extname = 'vector';
        """)
        result = cursor.fetchone()

        if result:
            ext_name, ext_version = result
            print(f"✅ pgvector 설치됨")
            print(f"   - 확장 이름: {ext_name}")
            print(f"   - 버전: {ext_version}")
            print()
        else:
            print("❌ pgvector가 설치되지 않았습니다")
            sys.exit(1)

        # 사용 가능한 벡터 타입 확인
        print("사용 가능한 벡터 타입 확인 중...")
        cursor.execute("""
            SELECT typname
            FROM pg_type
            WHERE typname = 'vector';
        """)
        vector_type = cursor.fetchone()

        if vector_type:
            print(f"✅ vector 타입 사용 가능: {vector_type[0]}")
            print()
        else:
            print("❌ vector 타입을 찾을 수 없습니다")
            sys.exit(1)

        # 테스트: 간단한 벡터 생성
        print("벡터 생성 테스트 중...")
        try:
            cursor.execute("SELECT '[1,2,3]'::vector;")
            test_vector = cursor.fetchone()[0]
            print(f"✅ 벡터 생성 테스트 성공: {test_vector}")
            print()
        except Exception as e:
            print(f"❌ 벡터 생성 테스트 실패: {e}")
            sys.exit(1)

        # 코사인 거리 연산자 테스트
        print("코사인 거리 연산자 테스트 중...")
        try:
            cursor.execute("""
                SELECT '[1,2,3]'::vector <=> '[4,5,6]'::vector AS cosine_distance;
            """)
            distance = cursor.fetchone()[0]
            print(f"✅ 코사인 거리 계산 성공: {distance}")
            print()
        except Exception as e:
            print(f"❌ 코사인 거리 계산 실패: {e}")
            sys.exit(1)

        print("=" * 60)
        print("✅ pgvector 확장 활성화 완료!")
        print("=" * 60)
        print()
        print("다음 단계:")
        print("1. Alembic migration 실행:")
        print("   cd Backend && alembic upgrade head")
        print()
        print("2. 백엔드 서버 재시작")
        print()

    except psycopg2.Error as e:
        print(f"❌ 데이터베이스 오류: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 예기치 않은 오류: {e}")
        sys.exit(1)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            print("PostgreSQL 연결 종료")


if __name__ == "__main__":
    enable_pgvector()
