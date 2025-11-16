"""
봇 관리 서비스
"""
import copy
import logging
import time
import secrets
from typing import Optional, Tuple, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, update, delete
from sqlalchemy.exc import SQLAlchemyError

from app.models.bot import Bot, BotKnowledge, BotStatus
from app.models.document_embeddings import DocumentEmbedding
from app.schemas.bot import (
    CreateBotRequest,
    UpdateBotRequestPut,
    UpdateBotRequestPatch,
    BotGoal,
)
from app.core.exceptions import (
    BotCreationError,
    BotConfigurationError,
    DatabaseTransactionError
)
from app.config import settings

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

    def _create_default_workflow(
        self,
        knowledge_list: Optional[List[str]] = None,
        bot_identifier: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        기본 워크플로우 생성

        Args:
            knowledge_list: 지식 문서 ID 리스트
            bot_identifier: workflow에서 dataset_id로 사용할 값 (bot_id 권장)

        Returns:
            기본 워크플로우 딕셔너리 (START → KNOWLEDGE → LLM → ANSWER)
        """
        nodes = []
        edges = []

        # 1. START 노드
        start_node = {
            "id": "start-1",
            "type": "start",
            "position": {"x": 100, "y": 150},
            "data": {
                "title": "START",
                "desc": "시작 노드",
                "type": "start"
            }
        }
        nodes.append(start_node)

        default_provider = (settings.llm_provider or "openai").lower()
        default_model = (
            settings.openai_model
            if default_provider == "openai"
            else settings.anthropic_model
        )

        # 2. LLM 노드 (프론트엔드 호환 구조)
        llm_node = {
            "id": "llm-1",
            "type": "llm",
            "position": {"x": 400, "y": 150},
            "data": {
                "title": "LLM",
                "desc": "언어 모델",
                "type": "llm",
                "provider": default_provider,
                "model": default_model,
                "prompt_template": "Context: {context}\\nQuestion: {question}\\nAnswer:",
                "temperature": 0.7,
                "max_tokens": 500
            }
        }
        nodes.append(llm_node)

        # START → LLM 엣지 (기본)
        edge_llm = {
            "id": "e-start-1-llm-1",
            "source": "start-1",
            "target": "llm-1",
            "type": "custom",
            "data": {
                "source_type": "start",
                "target_type": "llm"
            }
        }
        edges.append(edge_llm)

        # 3. END 노드
        end_node = {
            "id": "end-1",
            "type": "end",
            "position": {"x": 700, "y": 150},
            "data": {
                "title": "END",
                "desc": "종료 노드",
                "type": "end"
            }
        }
        nodes.append(end_node)

        # LLM → END 엣지
        edge_end = {
            "id": "e-llm-1-end-1",
            "source": "llm-1",
            "target": "end-1",
            "type": "custom",
            "data": {
                "source_type": "llm",
                "target_type": "end"
            }
        }
        edges.append(edge_end)

        workflow = {
            "nodes": nodes,
            "edges": edges
        }

        if knowledge_list:
            workflow = self._apply_knowledge_to_workflow_dict(
                workflow,
                knowledge_list,
                bot_identifier
            )

        return workflow

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

    def _normalize_goal_input(
        self,
        goal_input: Optional[str | BotGoal]
    ) -> Tuple[Optional[str], Optional[BotGoal]]:
        """
        goal 입력값을 저장용 문자열과 ENUM (선택)으로 분리

        Args:
            goal_input: 사용자 입력 goal (ENUM 또는 자유 텍스트)

        Returns:
            (저장용 문자열, ENUM 값 또는 None)
        """
        if goal_input is None:
            return None, None

        if isinstance(goal_input, BotGoal):
            return goal_input.value, goal_input

        goal_text = goal_input.strip()
        if not goal_text:
            return None, None

        try:
            return goal_text, BotGoal(goal_text)
        except ValueError:
            return goal_text, None

    def _apply_knowledge_to_workflow_dict(
        self,
        workflow_dict: Dict[str, Any],
        knowledge_list: List[str],
        bot_identifier: Optional[str]
    ) -> Dict[str, Any]:
        """워크플로우에 지식 노드를 주입하거나 업데이트"""

        if not workflow_dict:
            workflow_dict = {"nodes": [], "edges": []}

        workflow = copy.deepcopy(workflow_dict)
        nodes = workflow.setdefault("nodes", [])
        edges = workflow.setdefault("edges", [])

        start_node = next((n for n in nodes if n.get("type") == "start"), None)
        llm_node = next((n for n in nodes if n.get("type") == "llm"), None)

        if not start_node or not llm_node:
            # 필수 노드가 없다면 기본 구조를 재생성
            return self._create_default_workflow(knowledge_list, bot_identifier)

        knowledge_node = next((n for n in nodes if n.get("type") == "knowledge-retrieval"), None)

        dataset_id = bot_identifier or (knowledge_list[0] if knowledge_list else "default-dataset")
        dataset_name = f"{len(knowledge_list)}개 문서" if knowledge_list else None

        if knowledge_list:
            if not knowledge_node:
                knowledge_node = {
                    "id": "knowledge-1",
                    "type": "knowledge-retrieval",
                    "position": {
                        "x": (start_node["position"]["x"] + llm_node["position"]["x"]) / 2,
                        "y": start_node["position"].get("y", 150)
                    },
                    "data": {}
                }
                nodes.append(knowledge_node)

            knowledge_node.setdefault("data", {})
            knowledge_node["data"].update({
                "title": knowledge_node["data"].get("title", "KNOWLEDGE"),
                "desc": knowledge_node["data"].get("desc", "지식 검색"),
                "type": "knowledge-retrieval",
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "mode": knowledge_node["data"].get("mode", "semantic"),
                "top_k": knowledge_node["data"].get("top_k", 5),
                "document_ids": knowledge_list
            })

            # START → KNOWLEDGE, KNOWLEDGE → LLM 연결 보장
            self._ensure_edge(edges, start_node["id"], knowledge_node["id"], "start", "knowledge-retrieval")
            self._ensure_edge(edges, knowledge_node["id"], llm_node["id"], "knowledge-retrieval", "llm")

            # 직접 연결 제거 (중복 방지)
            edges[:] = [
                edge for edge in edges
                if not (edge.get("source") == start_node["id"] and edge.get("target") == llm_node["id"])
            ]
        else:
            # 지식이 없으면 지식 노드 제거 (자동 생성된 노드만 해당)
            knowledge_node_ids = [n["id"] for n in nodes if n.get("type") == "knowledge-retrieval"]
            if knowledge_node_ids:
                nodes[:] = [n for n in nodes if n.get("id") not in knowledge_node_ids]
                edges[:] = [
                    edge for edge in edges
                    if edge.get("source") not in knowledge_node_ids and edge.get("target") not in knowledge_node_ids
                ]

            # START → LLM 경로 복구
            self._ensure_edge(edges, start_node["id"], llm_node["id"], "start", "llm")

        return workflow

    @staticmethod
    def _ensure_edge(
        edges: List[Dict[str, Any]],
        source: str,
        target: str,
        source_type: str,
        target_type: str
    ) -> None:
        """엣지가 없으면 추가하고 존재하면 타입 정보를 보정"""
        for edge in edges:
            if edge.get("source") == source and edge.get("target") == target:
                edge.setdefault("data", {})
                edge["data"].update({
                    "source_type": source_type,
                    "target_type": target_type
                })
                return

        edges.append({
            "id": f"e-{source}-{target}",
            "source": source,
            "target": target,
            "type": "custom",
            "data": {
                "source_type": source_type,
                "target_type": target_type
            }
        })

    async def create_bot(
        self,
        request: CreateBotRequest,
        user_id: int,
        db: AsyncSession
    ) -> Bot:
        """
        봇 생성

        Args:
            request: 봇 생성 요청 데이터
            user_id: 사용자 ID
            db: 데이터베이스 세션

        Returns:
            생성된 Bot 인스턴스

        Raises:
            ValueError: 봇 ID 중복 등의 유효성 검증 실패
            Exception: 데이터베이스 오류
        """
        logger.info(f"봇 생성 요청: name={request.name}, user_id={user_id}")

        try:
            # 1. 고유한 bot_id 생성 (중복 체크 포함)
            bot_id = await self._generate_unique_bot_id(db)

            # 2. goal 문자열 및 ENUM 분리 (커스텀 텍스트 허용)
            goal_str, goal_enum = self._normalize_goal_input(request.goal)

            # 3. Goal에 따른 기본 페르소나 설정 (사용자가 지정하지 않은 경우)
            personality = request.personality
            if not personality and goal_enum:
                personality = self._get_default_personality(goal_enum.value)

            # 4. description 생성 (goal이 있으면 사용, 없으면 name 기반)
            description = goal_str if goal_str else f"{request.name} 봇"

            # 5. workflow 처리: 없거나 기본 노드만 있으면 자동 생성
            workflow_dict = None
            if request.workflow:
                workflow_dict = request.workflow.model_dump(mode='json')

                # 노드가 전혀 없을 때만 서버에서 기본 워크플로우를 생성한다.
                nodes = workflow_dict.get('nodes', [])
                if not nodes:
                    logger.info("제공된 워크플로우 노드가 없어 기본 워크플로우를 자동 생성합니다.")
                    workflow_dict = self._create_default_workflow(request.knowledge, bot_id)
            else:
                # workflow가 없으면 기본 워크플로우 생성
                logger.info("기본 워크플로우 자동 생성 (workflow 없음)")
                workflow_dict = self._create_default_workflow(request.knowledge, bot_id)

            # 6. Bot 인스턴스 생성
            bot = Bot(
                bot_id=bot_id,
                user_id=user_id,
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

            migrated_vectors = 0
            if request.session_id:
                migrated_vectors = await self._migrate_session_embeddings(
                    session_bot_id=request.session_id,
                    target_bot_id=bot.bot_id,
                    db=db
                )

            # 4. 지식 항목 저장
            if request.knowledge:
                await self._save_knowledge_items(bot.id, request.knowledge, db)

            # 5. 커밋 및 리프레시
            await db.commit()
            await db.refresh(bot)

            logger.info(
                f"봇 생성 성공: bot_id={bot_id}, knowledge_count={len(request.knowledge or [])}, "
                f"migrated_vectors={migrated_vectors}"
            )

            return bot

        except SQLAlchemyError as e:
            logger.error(f"봇 생성 DB 오류: {e}", exc_info=True)
            await db.rollback()
            raise DatabaseTransactionError(
                message="봇 생성 중 데이터베이스 오류가 발생했습니다",
                details={
                    "bot_name": request.name,
                    "user_id": user_id,
                    "error": str(e)
                }
            )
        except ValueError as e:
            logger.error(f"봇 생성 검증 오류: {e}", exc_info=True)
            await db.rollback()
            raise BotConfigurationError(
                message=str(e),
                details={
                    "bot_name": request.name,
                    "user_id": user_id
                }
            )
        except Exception as e:
            logger.error(f"봇 생성 실패: {e}", exc_info=True)
            await db.rollback()
            raise BotCreationError(
                message="봇 생성 중 예기치 않은 오류가 발생했습니다",
                details={
                    "bot_name": request.name,
                    "user_id": user_id,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )

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

    async def _migrate_session_embeddings(
        self,
        session_bot_id: str,
        target_bot_id: str,
        db: AsyncSession
    ) -> int:
        """
        Setup 단계에서 사용된 임시 봇(session_*)의 벡터를 실제 봇으로 마이그레이션

        Args:
            session_bot_id: 임시 봇 ID (session_* 형식)
            target_bot_id: 새로 생성된 봇의 bot_id 
            db: 데이터베이스 세션

        Returns:
            이동한 임베딩(청크) 개수
        """
        if not session_bot_id or session_bot_id == target_bot_id:
            return 0

        logger.info(
            f"임시 봇 벡터 마이그레이션 시작: session_bot_id={session_bot_id}, target_bot_id={target_bot_id}"
        )

        # 1. 이동할 벡터 수 조회
        count_result = await db.execute(
            select(func.count(DocumentEmbedding.id)).where(
                DocumentEmbedding.bot_id == session_bot_id
            )
        )
        total_embeddings = count_result.scalar_one() or 0

        if total_embeddings == 0:
            logger.info(f"임시 봇 벡터 없음: session_bot_id={session_bot_id}")
            return 0

        # 2. bot_id 업데이트
        await db.execute(
            update(DocumentEmbedding)
            .where(DocumentEmbedding.bot_id == session_bot_id)
            .values(bot_id=target_bot_id)
        )
        await db.flush()

        logger.info(
            f"임시 봇 벡터 마이그레이션 완료: session_bot_id={session_bot_id}, "
            f"target_bot_id={target_bot_id}, moved={total_embeddings}"
        )
        return total_embeddings

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

    async def _replace_knowledge_items(
        self,
        bot_id: int,
        knowledge_list: list[str],
        db: AsyncSession
    ) -> None:
        """기존 지식 항목을 모두 교체"""

        await db.execute(delete(BotKnowledge).where(BotKnowledge.bot_id == bot_id))
        await db.flush()

        if knowledge_list:
            await self._save_knowledge_items(bot_id, knowledge_list, db)

    async def get_bots_by_user(self, user_id: int, db: AsyncSession) -> list[Bot]:
        """
        사용자의 모든 봇 조회

        Args:
            user_id: 사용자 ID
            db: 데이터베이스 세션

        Returns:
            봇 목록
        """
        result = await db.execute(
            select(Bot).where(Bot.user_id == user_id).order_by(Bot.created_at.desc())
        )
        bots = result.scalars().all()
        logger.info(f"사용자 {user_id}의 봇 {len(bots)}개 조회")
        return list(bots)

    async def get_bots_with_pagination(
        self,
        user_id: int,
        db: AsyncSession,
        page: int = 1,
        limit: int = 10,
        sort: str = "updated_at:desc",
        search: Optional[str] = None
    ) -> Tuple[List[Bot], int]:
        """
        페이지네이션과 검색을 지원하는 Bot 목록 조회

        Args:
            user_id: 사용자 ID
            db: 데이터베이스 세션
            page: 페이지 번호 (1부터 시작)
            limit: 페이지당 항목 수
            sort: 정렬 기준 (field:asc/desc)
            search: 검색어

        Returns:
            (봇 목록, 전체 개수) 튜플
        """
        # 기본 쿼리
        query = select(Bot).where(Bot.user_id == user_id)

        # 검색 필터 (이름과 설명으로 검색)
        if search:
            query = query.where(
                or_(
                    Bot.name.ilike(f"%{search}%"),
                    Bot.description.ilike(f"%{search}%")
                )
            )

        # 전체 개수 조회
        count_result = await db.execute(
            select(func.count()).select_from(Bot).where(Bot.user_id == user_id).where(
                or_(
                    Bot.name.ilike(f"%{search}%"),
                    Bot.description.ilike(f"%{search}%")
                ) if search else True
            )
        )
        total = count_result.scalar()

        # 정렬 처리
        if sort:
            field, order = sort.split(':') if ':' in sort else (sort, 'asc')

            # 필드명 매핑 (camelCase → snake_case)
            field_mapping = {
                'updatedAt': 'updated_at',
                'createdAt': 'created_at',
                'name': 'name'
            }

            field = field_mapping.get(field, 'updated_at')

            # 정렬 적용
            if hasattr(Bot, field):
                sort_column = getattr(Bot, field)
                if order.lower() == 'desc':
                    query = query.order_by(sort_column.desc())
                else:
                    query = query.order_by(sort_column.asc())

        # 페이지네이션 적용
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        result = await db.execute(query)
        bots = result.scalars().all()

        logger.info(f"사용자 {user_id}의 봇 페이지네이션 조회: page={page}, limit={limit}, total={total}")

        return list(bots), total

    async def get_bot_by_id(
        self,
        bot_id: str,
        user_id: Optional[int],
        db: AsyncSession,
        include_workflow: bool = False
    ) -> Optional[Bot]:
        """
        특정 봇 조회

        Args:
            bot_id: 봇 ID
            user_id: 사용자 ID (None이면 user_id 검증 생략)
            db: 데이터베이스 세션
            include_workflow: workflow 포함 여부 (상세 조회용)

        Returns:
            Bot 인스턴스 또는 None
        """
        query = select(Bot).where(Bot.bot_id == bot_id)

        if user_id is not None:
            query = query.where(Bot.user_id == user_id)

        result = await db.execute(query)
        bot = result.scalar_one_or_none()

        if bot:
            logger.info(f"봇 조회 성공: bot_id={bot_id}, include_workflow={include_workflow}")
        else:
            logger.warning(f"봇을 찾을 수 없음: bot_id={bot_id}, user_id={user_id}")

        return bot

    async def update_bot(
        self,
        bot_id: str,
        user_id: int,
        request: UpdateBotRequestPut | UpdateBotRequestPatch,
        db: AsyncSession
    ) -> Optional[Bot]:
        """
        봇 정보 수정

        Args:
            bot_id: 봇 ID
            user_id: 사용자 ID
            request: 수정 요청 데이터
            db: 데이터베이스 세션

        Returns:
            수정된 Bot 인스턴스 또는 None

        Raises:
            ValueError: 봇을 찾을 수 없는 경우
        """
        bot = await self.get_bot_by_id(bot_id, user_id, db)

        if not bot:
            raise ValueError(f"봇을 찾을 수 없습니다: {bot_id}")

        # 수정할 필드만 업데이트
        update_data = request.model_dump(exclude_unset=True)
        knowledge_items = update_data.pop("knowledge", None)

        for field, value in update_data.items():
            if field == "status":
                setattr(bot, field, BotStatus(value))
            elif field == "goal" and value is not None:
                previous_goal = bot.goal
                previous_description = bot.description
                goal_value, _ = self._normalize_goal_input(value)
                setattr(bot, field, goal_value)

                # 사용자가 별도로 설명을 입력하지 않았다면 goal과 동기화
                if previous_description in (None, previous_goal, f"{bot.name} 봇"):
                    bot.description = goal_value
            elif field == "workflow" and value is not None:
                # Pydantic Workflow 객체 → dict 변환
                workflow_dict = value.model_dump(mode='json') if hasattr(value, 'model_dump') else value
                setattr(bot, field, workflow_dict)
            else:
                setattr(bot, field, value)

        if knowledge_items is not None:
            knowledge_values = knowledge_items or []
            await self._replace_knowledge_items(bot.id, knowledge_values, db)

            current_workflow = bot.workflow if isinstance(bot.workflow, dict) else bot.workflow or {}
            bot.workflow = self._apply_knowledge_to_workflow_dict(
                current_workflow,
                knowledge_values,
                bot.bot_id
            )

        try:
            await db.commit()
            await db.refresh(bot)
            logger.info(f"봇 수정 성공: bot_id={bot_id}, 수정 필드={list(update_data.keys())}")
            return bot
        except SQLAlchemyError as e:
            logger.error(f"봇 수정 DB 오류: {e}", exc_info=True)
            await db.rollback()
            raise DatabaseTransactionError(
                message="봇 수정 중 데이터베이스 오류가 발생했습니다",
                details={
                    "bot_id": bot_id,
                    "user_id": user_id,
                    "update_fields": list(update_data.keys()),
                    "error": str(e)
                }
            )
        except Exception as e:
            logger.error(f"봇 수정 실패: {e}", exc_info=True)
            await db.rollback()
            raise BotConfigurationError(
                message="봇 수정 중 예기치 않은 오류가 발생했습니다",
                details={
                    "bot_id": bot_id,
                    "user_id": user_id,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )

    async def toggle_bot_status(
        self,
        bot_id: str,
        user_id: int,
        is_active: bool,
        db: AsyncSession
    ) -> Bot:
        """
        Bot 활성화 상태 토글

        Args:
            bot_id: 봇 ID
            user_id: 사용자 ID
            is_active: 활성화 여부
            db: 데이터베이스 세션

        Returns:
            업데이트된 Bot 인스턴스

        Raises:
            ValueError: 봇을 찾을 수 없거나 workflow 검증 실패
        """
        bot = await self.get_bot_by_id(bot_id, user_id, db)

        if not bot:
            raise ValueError(f"봇을 찾을 수 없습니다: {bot_id}")

        # 활성화 시 workflow 검증
        if is_active and bot.workflow:
            # 간단한 검증 - 실제로는 더 복잡한 검증이 필요할 수 있음
            workflow = bot.workflow if isinstance(bot.workflow, dict) else {}
            nodes = workflow.get('nodes', [])
            edges = workflow.get('edges', [])

            # Start 노드 확인
            start_nodes = [n for n in nodes if n.get('type') == 'start']
            if not start_nodes:
                raise ValueError("Workflow 검증 실패: Start 노드가 필요합니다")

            # End 노드 확인
            end_nodes = [n for n in nodes if n.get('type') == 'end']
            if not end_nodes:
                raise ValueError("Workflow 검증 실패: End 노드가 필요합니다")

        # 상태 변경
        bot.status = BotStatus.ACTIVE if is_active else BotStatus.INACTIVE

        try:
            await db.commit()
            await db.refresh(bot)
            logger.info(f"봇 상태 토글 성공: bot_id={bot_id}, is_active={is_active}")
            return bot
        except SQLAlchemyError as e:
            logger.error(f"봇 상태 토글 DB 오류: {e}", exc_info=True)
            await db.rollback()
            raise DatabaseTransactionError(
                message="봇 상태 변경 중 데이터베이스 오류가 발생했습니다",
                details={
                    "bot_id": bot_id,
                    "user_id": user_id,
                    "is_active": is_active,
                    "error": str(e)
                }
            )

    async def delete_bot(self, bot_id: str, user_id: int, db: AsyncSession) -> bool:
        """
        봇 삭제

        Args:
            bot_id: 봇 ID
            user_id: 사용자 ID
            db: 데이터베이스 세션

        Returns:
            삭제 성공 여부

        Raises:
            ValueError: 봇을 찾을 수 없는 경우
        """
        bot = await self.get_bot_by_id(bot_id, user_id, db)

        if not bot:
            raise ValueError(f"봇을 찾을 수 없습니다: {bot_id}")

        try:
            await db.delete(bot)
            await db.commit()
            logger.info(f"봇 삭제 성공: bot_id={bot_id}")
            return True
        except SQLAlchemyError as e:
            logger.error(f"봇 삭제 DB 오류: {e}", exc_info=True)
            await db.rollback()
            raise DatabaseTransactionError(
                message="봇 삭제 중 데이터베이스 오류가 발생했습니다",
                details={
                    "bot_id": bot_id,
                    "user_id": user_id,
                    "error": str(e)
                }
            )
        except Exception as e:
            logger.error(f"봇 삭제 실패: {e}", exc_info=True)
            await db.rollback()
            raise BotConfigurationError(
                message="봇 삭제 중 예기치 않은 오류가 발생했습니다",
                details={
                    "bot_id": bot_id,
                    "user_id": user_id,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )

    async def update_bot_workflow(
        self,
        bot_id: str,
        user_id: int,
        workflow: Dict[str, Any],
        db: AsyncSession
    ) -> bool:
        """
        봇의 워크플로우 업데이트

        Args:
            bot_id: 봇 ID
            user_id: 사용자 ID
            workflow: 워크플로우 정의
            db: 데이터베이스 세션

        Returns:
            bool: 성공 여부
        """
        try:
            # 봇 조회
            bot = await self.get_bot_by_id(bot_id, user_id, db)
            if not bot:
                return False

            # 워크플로우 업데이트
            bot.workflow = workflow
            await db.commit()

            logger.info(f"Updated workflow for bot {bot_id}")
            return True

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to update bot workflow: {str(e)}")
            raise

    async def enable_workflow_v2(
        self,
        bot_id: str,
        user_id: int,
        db: AsyncSession
    ) -> Bot:
        """봇의 V2 워크플로우 모드를 활성화"""
        bot = await self.get_bot_by_id(bot_id, user_id, db)

        if not bot:
            raise ValueError(f"봇을 찾을 수 없습니다: {bot_id}")

        if not bot.use_workflow_v2:
            bot.use_workflow_v2 = True
            await db.commit()
            await db.refresh(bot)
            logger.info(f"Enabled workflow V2 mode for bot {bot_id}")
        else:
            logger.info(f"Bot {bot_id} already has workflow V2 enabled")

        return bot


# 싱글톤 인스턴스
_bot_service: Optional[BotService] = None


def get_bot_service() -> BotService:
    """봇 서비스 싱글톤 인스턴스 반환"""
    global _bot_service
    if _bot_service is None:
        _bot_service = BotService()
    return _bot_service
