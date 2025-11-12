#!/usr/bin/env python3
import asyncio
import sys
from sqlalchemy import text
from app.core.database import async_session_factory

async def main():
    async with async_session_factory() as session:
        # Check if documents table exists
        result = await session.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'documents'
            );
        """))
        table_exists = result.scalar()
        print(f"documents 테이블 존재: {table_exists}")
        
        # Check alembic version
        try:
            result = await session.execute(text("SELECT version_num FROM alembic_version"))
            version = result.scalar()
            print(f"현재 Alembic 버전: {version}")
        except Exception as e:
            print(f"Alembic 버전 확인 실패: {e}")
        
        # If table doesn't exist but version is ahead, reset to correct version
        if not table_exists:
            print("❌ documents 테이블이 없는데 마이그레이션 버전이 잘못되어 있습니다!")
            print("🔧 마이그레이션 버전을 c2d3e4f5g6h7로 되돌립니다...")
            await session.execute(text("UPDATE alembic_version SET version_num = 'c2d3e4f5g6h7'"))
            await session.commit()
            print("✅ 버전 수정 완료. 이제 alembic upgrade head를 실행하세요.")
        else:
            print("✅ documents 테이블이 정상적으로 존재합니다.")

if __name__ == "__main__":
    asyncio.run(main())
