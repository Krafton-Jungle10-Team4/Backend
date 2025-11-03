"""
데이터베이스 연결 및 세션 관리
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import settings

# SQLAlchemy Base 클래스 (JPA의 @Entity 상속용)
Base = declarative_base()

# 비동기 엔진 생성
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# 비동기 세션 팩토리 (JPA의 EntityManager와 유사)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    """
    데이터베이스 세션 의존성
    FastAPI 엔드포인트에서 사용 (JPA의 @Repository와 유사)

    Usage:
        @router.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
