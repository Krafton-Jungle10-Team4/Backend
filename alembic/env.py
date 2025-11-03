"""Alembic 마이그레이션 환경 설정"""
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
import asyncio

# 우리 프로젝트 설정 import
from app.config import settings
from app.core.database import Base
# 모든 모델 import (Alembic이 자동으로 감지하도록)
from app.models.user import User, Team, TeamMember, APIKey, InviteToken
from app.models.bot import Bot, BotKnowledge

# Alembic Config 객체
config = context.config

# 환경 변수에서 DATABASE_URL 가져오기
config.set_main_option("sqlalchemy.url", settings.database_url)

# 로깅 설정
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 모델의 MetaData (테이블 정의)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """오프라인 모드 (SQL 파일만 생성)"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """실제 마이그레이션 실행"""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """비동기 마이그레이션"""
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = settings.database_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """온라인 모드 (실제 DB에 적용)"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
