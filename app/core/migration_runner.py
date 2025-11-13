"""
애플리케이션 기동 시 Alembic 마이그레이션을 자동으로 실행하는 유틸리티
"""
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Backend 루트 경로 (/Backend)
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH: Final[Path] = PROJECT_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION: Final[Path] = PROJECT_ROOT / "alembic"


def _build_alembic_config() -> Config:
    """실행 환경에 맞는 Alembic 설정 생성"""
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", settings.get_database_url_sync())
    return config


async def run_db_migrations() -> None:
    """
    Alembic upgrade head를 비동기 FastAPI 환경에서 실행
    - ThreadPool로 실행하여 이벤트 루프 블로킹 방지
    """
    if not settings.auto_run_migrations:
        logger.info("⏭️ AUTO_RUN_MIGRATIONS=false - 자동 마이그레이션을 건너뜁니다")
        return

    config = _build_alembic_config()

    def _upgrade():
        logger.info("🔁 데이터베이스 마이그레이션 검증 시작")
        command.upgrade(config, "head")
        logger.info("✅ 데이터베이스 마이그레이션 완료")

    try:
        await run_in_threadpool(_upgrade)
    except Exception as exc:  # pragma: no cover - 로깅 목적
        logger.exception("❌ Alembic 마이그레이션 실행 실패: %s", exc)
        raise
