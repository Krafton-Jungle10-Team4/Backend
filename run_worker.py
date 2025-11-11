#!/usr/bin/env python
"""
임베딩 워커 실행 스크립트

사용법:
    python run_worker.py

환경 변수:
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
    - AWS_REGION
    - S3_BUCKET_NAME
    - SQS_QUEUE_URL
    - DATABASE_URL
"""
import asyncio
import signal
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.workers import EmbeddingWorker
from app.core.logging_config import setup_logging, get_logger
from app.config import settings

# 로깅 설정
setup_logging(
    log_level=settings.log_level,
    use_structured=True
)
logger = get_logger(__name__)


async def main():
    """워커 메인 함수"""
    worker = EmbeddingWorker()

    # Graceful shutdown을 위한 시그널 핸들러
    def signal_handler(sig, frame):
        logger.info(f"시그널 수신: {sig}")
        asyncio.create_task(worker.shutdown())
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 워커 시작
        await worker.start()
    except KeyboardInterrupt:
        logger.info("워커 중단")
    except Exception as e:
        logger.error(f"워커 실행 중 오류 발생: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await worker.shutdown()


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("임베딩 워커 시작")
    logger.info("=" * 60)
    logger.info(f"환경: {settings.environment}")
    logger.info(f"데이터베이스: {settings.database_url.split('@')[-1]}")
    logger.info(f"S3 버킷: {settings.s3_bucket_name}")
    logger.info(f"SQS 큐: {settings.sqs_queue_url}")
    logger.info("=" * 60)

    # 필수 환경 변수 검증
    # AWS 자격증명은 ECS Task Role이 있으면 자동으로 제공되므로 선택적
    # DATABASE_URL은 개별 환경 변수(DATABASE_HOST, DATABASE_USER, DATABASE_PASSWORD)로부터 구성 가능
    required_vars = [
        "S3_BUCKET_NAME",
        "SQS_QUEUE_URL",
    ]

    # DATABASE 관련 환경 변수 확인 (DATABASE_URL 또는 개별 환경 변수)
    has_database_url = bool(getattr(settings, "database_url", None))
    has_database_components = all([
        getattr(settings, "database_host", None),
        getattr(settings, "database_name", None),
        getattr(settings, "database_user", None),
        getattr(settings, "database_password", None),
    ])

    if not (has_database_url or has_database_components):
        required_vars.append("DATABASE_URL or DATABASE_HOST/USER/PASSWORD")

    missing_vars = [var for var in required_vars if not getattr(settings, var.lower(), None)]
    if missing_vars:
        logger.error(f"필수 환경 변수 누락: {', '.join(missing_vars)}")
        sys.exit(1)

    # 워커 실행
    asyncio.run(main())
