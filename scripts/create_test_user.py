"""테스트 계정 생성 스크립트"""
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from passlib.context import CryptContext

from app.core.database import async_session_maker
from app.models.user import User, AuthType

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def create_test_user():
    """테스트 계정 생성"""
    async with async_session_maker() as db:
        # 이미 존재하는지 확인
        result = await db.execute(
            select(User).where(User.email == "test@example.com")
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            print("❌ 테스트 계정이 이미 존재합니다: test@example.com")
            return

        # 비밀번호 해싱
        hashed_password = pwd_context.hash("test1234")

        # 사용자 생성
        user = User(
            email="test@example.com",
            name="테스트 사용자",
            auth_type=AuthType.LOCAL,
            password_hash=hashed_password
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        print("✅ 테스트 계정이 생성되었습니다!")
        print(f"   이메일: test@example.com")
        print(f"   비밀번호: test1234")
        print(f"   사용자 ID: {user.id}")
        print(f"   사용자 UUID: {user.uuid}")


if __name__ == "__main__":
    asyncio.run(create_test_user())
