from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from uuid import UUID
import secrets

from app.models.deployment import BotDeployment, WidgetSession, WidgetMessage
from app.models.bot import Bot
from app.schemas.widget import SessionCreateRequest, ChatMessageRequest
from app.core.widget.security import widget_security
from app.core.exceptions import NotFoundException, ForbiddenException, UnauthorizedException
from app.config import settings


class WidgetService:
    """Widget 서비스"""

    @staticmethod
    async def get_widget_config(
        db: AsyncSession,
        widget_key: str,
        origin: str
    ) -> Dict[str, Any]:
        """
        Widget 설정 조회 (도메인 검증 포함)

        Args:
            db: DB 세션
            widget_key: Widget Key
            origin: 요청 출처

        Returns:
            서명된 Widget 설정
        """
        # 배포 조회
        stmt = select(BotDeployment).where(
            BotDeployment.widget_key == widget_key,
            BotDeployment.status == "published"
        )
        result = await db.execute(stmt)
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise NotFoundException("Widget not found or not published")

        # 도메인 검증
        if not widget_security.verify_domain(origin, deployment.allowed_domains):
            raise ForbiddenException("Domain not allowed")

        # Bot 정보 로드 (relationship 사용)
        await db.refresh(deployment, ["bot"])

        # 설정 구성
        config = {
            "bot_id": deployment.bot.bot_id,
            "bot_name": deployment.widget_config.get("bot_name"),
            "avatar_url": deployment.widget_config.get("avatar_url"),
            "theme": deployment.widget_config.get("theme"),
            "position": deployment.widget_config.get("position"),
            "welcome_message": deployment.widget_config.get("welcome_message"),
            "features": {
                "file_upload": deployment.widget_config.get("enable_file_upload"),
                "voice_input": False,  # 향후 구현
                "feedback": deployment.widget_config.get("enable_feedback"),
                "save_conversation": deployment.widget_config.get("save_conversation"),
            },
            "api_endpoints": {
                "session": "/api/v1/widget/sessions",
                "chat": "/api/v1/widget/chat",
                "feedback": "/api/v1/widget/feedback",
                "upload": "/api/v1/widget/upload",
            }
        }

        # 서명 추가
        signed_config = widget_security.sign_config(config, widget_key)
        return signed_config

    @staticmethod
    async def create_session(
        db: AsyncSession,
        session_data: SessionCreateRequest
    ) -> Dict[str, Any]:
        """
        Widget 세션 생성

        Args:
            db: DB 세션
            session_data: 세션 생성 데이터

        Returns:
            세션 정보 (토큰 포함)
        """
        # 배포 조회
        stmt = select(BotDeployment).where(
            BotDeployment.widget_key == session_data.widget_key,
            BotDeployment.status == "published"
        )
        result = await db.execute(stmt)
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise NotFoundException("Widget not found")

        # 지문 해시 생성
        fingerprint_hash = widget_security.generate_fingerprint_hash(
            session_data.fingerprint.dict()
        )

        # 세션 토큰 생성
        session_token = f"wst_{secrets.token_urlsafe(32)}"
        refresh_token = f"wrt_{secrets.token_urlsafe(32)}"

        # 토큰 해싱
        session_token_hash = widget_security.hash_token(session_token)
        refresh_token_hash = widget_security.hash_token(refresh_token)

        # 만료 시간 계산 (timezone-aware)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.widget_session_expire_hours)

        # 세션 생성
        session = WidgetSession(
            deployment_id=deployment.deployment_id,
            session_token_hash=session_token_hash,
            refresh_token_hash=refresh_token_hash,
            user_info=session_data.user_info.dict() if session_data.user_info else None,
            fingerprint=session_data.fingerprint.dict(),
            fingerprint_hash=fingerprint_hash,
            origin=session_data.context.page_url,
            expires_at=expires_at,
            metadata=session_data.context.dict()
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

        # WebSocket URL 구성
        ws_url = f"wss://{settings.host}/ws/widget/chat/{session.session_id}"

        return {
            "session_id": session.session_id,
            "session_token": session_token,  # 평문으로 반환 (클라이언트 저장용)
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "ws_url": ws_url,
            "ws_protocols": ["chat.v1"],
            "features_enabled": {
                "file_upload": deployment.widget_config.get("enable_file_upload", False),
                "voice_input": False,
                "feedback": deployment.widget_config.get("enable_feedback", True),
            }
        }

    @staticmethod
    async def send_message(
        db: AsyncSession,
        message_data: ChatMessageRequest,
        session_token: str
    ) -> Dict[str, Any]:
        """
        메시지 전송 및 봇 응답 생성

        Args:
            db: DB 세션
            message_data: 메시지 데이터
            session_token: 세션 토큰

        Returns:
            봇 응답
        """
        # 세션 조회 및 검증
        session_token_hash = widget_security.hash_token(session_token)
        stmt = select(WidgetSession).where(
            WidgetSession.session_id == message_data.session_id,
            WidgetSession.session_token_hash == session_token_hash,
            WidgetSession.is_active == True
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise UnauthorizedException("Invalid session")

        # 만료 확인 (timezone-aware 비교)
        if datetime.now(timezone.utc) > session.expires_at:
            raise UnauthorizedException("Session expired")

        # 사용자 메시지 저장
        user_message = WidgetMessage(
            session_id=session.session_id,
            role="user",
            content=message_data.message["content"],
            message_type=message_data.message.get("type", "text"),
            attachments=message_data.message.get("attachments"),
            metadata=message_data.context
        )
        db.add(user_message)

        # 배포 및 봇 정보 로드 (user relationship을 eager loading)
        deployment = await db.get(BotDeployment, session.deployment_id)

        # Bot 조회 시 user도 함께 로드 (lazy loading 방지)
        stmt = select(Bot).where(Bot.id == deployment.bot_id).options(selectinload(Bot.user))
        result = await db.execute(stmt)
        bot = result.scalar_one_or_none()

        # ChatService로 RAG 파이프라인 실행
        from app.services.chat_service import ChatService
        from app.models.chat import ChatRequest

        chat_service = ChatService()

        # ChatRequest 생성
        chat_request = ChatRequest(
            message=message_data.message["content"],
            bot_id=bot.bot_id if bot else None,
            top_k=settings.chat_default_top_k
        )

        # User UUID 가져오기
        user_uuid = str(bot.user.uuid) if bot and bot.user else None

        # 응답 생성
        chat_response = await chat_service.generate_response(
            request=chat_request,
            user_uuid=user_uuid,
            db=db
        )

        # 봇 응답 저장
        bot_message = WidgetMessage(
            session_id=session.session_id,
            role="assistant",
            content=chat_response.response,
            sources=[source.dict() for source in chat_response.sources] if chat_response.sources else None,
            metadata={"confidence": 0.95}  # 임시
        )
        db.add(bot_message)

        # 마지막 활동 시간 업데이트 (timezone-aware)
        session.last_activity = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(bot_message)

        return {
            "message_id": bot_message.message_id,
            "response": {
                "content": bot_message.content,
                "type": "text",
                "metadata": bot_message.metadata
            },
            "sources": bot_message.sources or [],
            "suggested_actions": [],  # 향후 구현
            "timestamp": bot_message.created_at
        }
