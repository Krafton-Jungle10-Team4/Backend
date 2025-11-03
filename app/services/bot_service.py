"""
봇 관리 서비스
"""
import logging
import time
import secrets
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.bot import Bot, BotKnowledge, BotStatus
from app.schemas.bot import CreateBotRequest

logger = logging.getLogger(__name__)


def generate_bot_id() -> str:
    """
    고유한 봇 ID 생성

    형식: bot_{timestamp}_{random_hex}
    예: bot_1730718000_a8b9c3d4e
    """
    timestamp = int(time.time())
    random_hex = secrets.token_hex(5)
    return f"bot_{timestamp}_{random_hex}"


class BotService:
    """봇 비즈니스 로직"""

    async def create_bot(
        self,
        request: CreateBotRequest,
        team_id: int,
        db: AsyncSession
    ) -> Bot:
        """
        봇 생성

        Args:
            request: 봇 생성 요청 데이터
            team_id: 팀 ID
            db: 데이터베이스 세션

        Returns:
            생성된 Bot 인스턴스

        Raises:
            ValueError: 봇 ID 중복 등의 유효성 검증 실패
            Exception: 데이터베이스 오류
        """
        logger.info(f"봇 생성 요청: name={request.name}, team_id={team_id}")

        try:
            # 1. 고유한 bot_id 생성 (중복 체크 포함)
            bot_id = await self._generate_unique_bot_id(db)

            # 2. description 생성 (goal이 있으면 사용, 없으면 name 기반)
            description = request.goal if request.goal else f"{request.name} 봇"

            # 3. Bot 인스턴스 생성
            bot = Bot(
                bot_id=bot_id,
                team_id=team_id,
                name=request.name,
                goal=request.goal,
                personality=request.personality,
                description=description,
                status=BotStatus.ACTIVE,
                messages_count=0,
                errors_count=0
            )

            db.add(bot)
            await db.flush()

            logger.debug(f"봇 생성 완료: bot.id={bot.id}, bot_id={bot_id}")

            # 4. 지식 항목 저장
            if request.knowledge:
                await self._save_knowledge_items(bot.id, request.knowledge, db)

            # 5. 커밋 및 리프레시
            await db.commit()
            await db.refresh(bot)

            logger.info(f"봇 생성 성공: bot_id={bot_id}, knowledge_count={len(request.knowledge or [])}")

            return bot

        except Exception as e:
            logger.error(f"봇 생성 실패: {e}", exc_info=True)
            await db.rollback()
            raise

    async def _generate_unique_bot_id(self, db: AsyncSession, max_retries: int = 5) -> str:
        """
        중복되지 않는 bot_id 생성

        Args:
            db: 데이터베이스 세션
            max_retries: 최대 재시도 횟수

        Returns:
            고유한 bot_id

        Raises:
            ValueError: 최대 재시도 횟수 초과
        """
        for attempt in range(max_retries):
            bot_id = generate_bot_id()

            result = await db.execute(
                select(Bot).where(Bot.bot_id == bot_id)
            )
            existing_bot = result.scalar_one_or_none()

            if not existing_bot:
                return bot_id

            logger.warning(f"bot_id 중복 감지: {bot_id}, 재시도 {attempt + 1}/{max_retries}")

        raise ValueError("고유한 bot_id 생성 실패: 최대 재시도 횟수 초과")

    async def _save_knowledge_items(
        self,
        bot_id: int,
        knowledge_list: list[str],
        db: AsyncSession
    ) -> None:
        """
        봇 지식 항목 저장

        Args:
            bot_id: Bot 테이블의 id (PK)
            knowledge_list: 지식 항목 리스트
            db: 데이터베이스 세션
        """
        for item in knowledge_list:
            if item and item.strip():
                knowledge = BotKnowledge(
                    bot_id=bot_id,
                    knowledge_item=item.strip()
                )
                db.add(knowledge)

        logger.debug(f"{len(knowledge_list)}개 지식 항목 저장 완료")


# 싱글톤 인스턴스
_bot_service: Optional[BotService] = None


def get_bot_service() -> BotService:
    """봇 서비스 싱글톤 인스턴스 반환"""
    global _bot_service
    if _bot_service is None:
        _bot_service = BotService()
    return _bot_service
