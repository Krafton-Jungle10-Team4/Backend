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
from app.schemas.bot import CreateBotRequest, UpdateBotRequest

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

    def _get_default_personality(self, goal: str) -> str:
        """
        Goal에 따른 기본 페르소나 반환

        Args:
            goal: 봇의 목표 (customer-support, ai-assistant, sales, other)

        Returns:
            기본 페르소나 프롬프트
        """
        personalities = {
            "customer-support": (
                "당신은 친절하고 전문적인 고객 지원 상담원입니다. "
                "고객의 문제를 신속하고 정확하게 해결하는 것을 최우선으로 합니다. "
                "항상 공손한 태도를 유지하며, 고객의 불만이나 문제에 공감하고 이해심을 보입니다. "
                "복잡한 기술적 내용도 쉽게 설명하며, 해결책을 단계별로 안내합니다."
            ),
            "ai-assistant": (
                "당신은 사용자를 돕는 만능 AI 어시스턴트입니다. "
                "다양한 주제에 대해 정확하고 유용한 정보를 제공하며, "
                "사용자의 질문에 명확하고 간결하게 답변합니다. "
                "필요한 경우 추가 설명이나 예시를 제공하여 이해를 돕습니다. "
                "브랜드와 관련된 모든 질문에 전문적으로 응대합니다."
            ),
            "sales": (
                "당신은 열정적이고 지식이 풍부한 영업 상담원입니다. "
                "고객이 자신에게 맞는 제품이나 서비스를 찾도록 돕습니다. "
                "고객의 니즈를 파악하고 적절한 솔루션을 제안하며, "
                "제품의 장점과 가치를 명확하게 전달합니다. "
                "부담스럽지 않게 자연스러운 대화를 통해 고객의 결정을 돕습니다."
            ),
            "other": (
                "당신은 사용자 맞춤형 대화형 에이전트입니다. "
                "사용자의 고유한 요구사항에 맞춰 유연하게 대응하며, "
                "친근하면서도 전문적인 태도를 유지합니다. "
                "대화의 맥락을 이해하고 적절한 응답을 제공합니다."
            )
        }

        return personalities.get(goal, personalities["other"])

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

            # 2. goal을 ENUM에서 string으로 변환 (DB 저장용)
            goal_str = request.goal.value if request.goal else None

            # 3. Goal에 따른 기본 페르소나 설정 (사용자가 지정하지 않은 경우)
            personality = request.personality
            if not personality and request.goal:
                personality = self._get_default_personality(request.goal.value)

            # 4. description 생성 (goal이 있으면 사용, 없으면 name 기반)
            description = goal_str if goal_str else f"{request.name} 봇"

            # 5. workflow 직렬화 (Pydantic → dict)
            workflow_dict = None
            if request.workflow:
                workflow_dict = request.workflow.model_dump(mode='json')

            # 6. Bot 인스턴스 생성
            bot = Bot(
                bot_id=bot_id,
                team_id=team_id,
                name=request.name,
                goal=goal_str,
                personality=personality,
                description=description,
                workflow=workflow_dict,
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

    async def get_bots_by_team(self, team_id: int, db: AsyncSession) -> list[Bot]:
        """
        팀의 모든 봇 조회

        Args:
            team_id: 팀 ID
            db: 데이터베이스 세션

        Returns:
            봇 목록
        """
        result = await db.execute(
            select(Bot).where(Bot.team_id == team_id).order_by(Bot.created_at.desc())
        )
        bots = result.scalars().all()
        logger.info(f"팀 {team_id}의 봇 {len(bots)}개 조회")
        return list(bots)

    async def get_bot_by_id(
        self,
        bot_id: str,
        team_id: Optional[int],
        db: AsyncSession,
        include_workflow: bool = False
    ) -> Optional[Bot]:
        """
        특정 봇 조회

        Args:
            bot_id: 봇 ID
            team_id: 팀 ID (None이면 team_id 검증 생략)
            db: 데이터베이스 세션
            include_workflow: workflow 포함 여부 (상세 조회용)

        Returns:
            Bot 인스턴스 또는 None
        """
        query = select(Bot).where(Bot.bot_id == bot_id)

        if team_id is not None:
            query = query.where(Bot.team_id == team_id)

        result = await db.execute(query)
        bot = result.scalar_one_or_none()

        if bot:
            logger.info(f"봇 조회 성공: bot_id={bot_id}, include_workflow={include_workflow}")
        else:
            logger.warning(f"봇을 찾을 수 없음: bot_id={bot_id}, team_id={team_id}")

        return bot

    async def update_bot(
        self,
        bot_id: str,
        team_id: int,
        request: UpdateBotRequest,
        db: AsyncSession
    ) -> Optional[Bot]:
        """
        봇 정보 수정

        Args:
            bot_id: 봇 ID
            team_id: 팀 ID
            request: 수정 요청 데이터
            db: 데이터베이스 세션

        Returns:
            수정된 Bot 인스턴스 또는 None

        Raises:
            ValueError: 봇을 찾을 수 없는 경우
        """
        bot = await self.get_bot_by_id(bot_id, team_id, db)

        if not bot:
            raise ValueError(f"봇을 찾을 수 없습니다: {bot_id}")

        # 수정할 필드만 업데이트
        update_data = request.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if field == "status":
                setattr(bot, field, BotStatus(value))
            elif field == "goal" and value is not None:
                setattr(bot, field, value.value)
            elif field == "workflow" and value is not None:
                # Pydantic Workflow 객체 → dict 변환
                workflow_dict = value.model_dump(mode='json') if hasattr(value, 'model_dump') else value
                setattr(bot, field, workflow_dict)
            else:
                setattr(bot, field, value)

        try:
            await db.commit()
            await db.refresh(bot)
            logger.info(f"봇 수정 성공: bot_id={bot_id}, 수정 필드={list(update_data.keys())}")
            return bot
        except Exception as e:
            logger.error(f"봇 수정 실패: {e}", exc_info=True)
            await db.rollback()
            raise

    async def delete_bot(self, bot_id: str, team_id: int, db: AsyncSession) -> bool:
        """
        봇 삭제

        Args:
            bot_id: 봇 ID
            team_id: 팀 ID
            db: 데이터베이스 세션

        Returns:
            삭제 성공 여부

        Raises:
            ValueError: 봇을 찾을 수 없는 경우
        """
        bot = await self.get_bot_by_id(bot_id, team_id, db)

        if not bot:
            raise ValueError(f"봇을 찾을 수 없습니다: {bot_id}")

        try:
            await db.delete(bot)
            await db.commit()
            logger.info(f"봇 삭제 성공: bot_id={bot_id}")
            return True
        except Exception as e:
            logger.error(f"봇 삭제 실패: {e}", exc_info=True)
            await db.rollback()
            raise


# 싱글톤 인스턴스
_bot_service: Optional[BotService] = None


def get_bot_service() -> BotService:
    """봇 서비스 싱글톤 인스턴스 반환"""
    global _bot_service
    if _bot_service is None:
        _bot_service = BotService()
    return _bot_service
