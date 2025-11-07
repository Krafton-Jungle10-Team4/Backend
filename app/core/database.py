"""
데이터베이스 연결 및 세션 관리
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import ValidationError as PydanticValidationError
from fastapi.exceptions import RequestValidationError
from app.config import settings
from app.core.exceptions import DatabaseTransactionError, BaseAppException

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

    Raises:
        DatabaseTransactionError: 트랜잭션 처리 중 오류 발생 시
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            raise DatabaseTransactionError(
                message=f"데이터베이스 트랜잭션 처리 중 오류가 발생했습니다: {str(e)}",
                details={"error_type": type(e).__name__, "error": str(e)}
            )
        except SQLAlchemyError:
            # SQLAlchemy 오류는 이미 위에서 처리됨
            raise
        except (StarletteHTTPException, BaseAppException, RequestValidationError, PydanticValidationError):
            # HTTPException, 커스텀 예외, Validation 예외는 그대로 전파
            await session.rollback()
            raise
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            # 일반적인 Python 예외는 그대로 전파 (애플리케이션 로직 오류)
            await session.rollback()
            raise
        except Exception as e:
            # 그 외 예상하지 못한 예외만 DatabaseTransactionError로 변환
            await session.rollback()
            raise DatabaseTransactionError(
                message=f"예기치 않은 데이터베이스 오류가 발생했습니다: {str(e)}",
                details={"error_type": type(e).__name__, "error": str(e)}
            )
        finally:
            await session.close()
