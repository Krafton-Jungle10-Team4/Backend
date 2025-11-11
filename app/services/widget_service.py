import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import Optional, Dict, Any, List, AsyncGenerator
from datetime import datetime, timedelta, timezone
from uuid import UUID
import secrets

from app.models.deployment import BotDeployment, WidgetSession, WidgetMessage
from app.models.bot import Bot
from app.schemas.widget import SessionCreateRequest, ChatMessageRequest
from app.core.widget.security import widget_security
from app.core.exceptions import NotFoundException, ForbiddenException, UnauthorizedException
from app.config import settings


def extract_domain_from_origin_or_referer(
    origin: Optional[str],
    referer: Optional[str]
) -> Optional[str]:
    """
    Origin 또는 Referer 헤더에서 도메인 추출

    Args:
        origin: Origin 헤더
        referer: Referer 헤더

    Returns:
        추출된 도메인 (예: https://example.com) 또는 None
    """
    # Origin 헤더 우선
    if origin:
        return origin

    # Referer 헤더에서 도메인 추출
    if referer:
        from urllib.parse import urlparse
        try:
            parsed = urlparse(referer)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            pass

    return None


class WidgetService:
    """Widget 서비스"""

    @staticmethod
    async def _load_session_and_bot(
        db: AsyncSession,
        message_data: ChatMessageRequest,
        session_token: str
    ) -> tuple[WidgetSession, Bot]:
        """세션 검증 및 봇 로드"""
        session_token_hash = widget_security.hash_token(session_token)

        stmt = select(WidgetSession).options(
            selectinload(WidgetSession.deployment)
        ).where(
            WidgetSession.session_id == message_data.session_id,
            WidgetSession.session_token_hash == session_token_hash,
            WidgetSession.is_active == True
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise UnauthorizedException("Invalid session")

        if datetime.now(timezone.utc) > session.expires_at:
            raise UnauthorizedException("Session expired")

        deployment = session.deployment or await db.get(BotDeployment, session.deployment_id)

        stmt = select(Bot).where(Bot.id == deployment.bot_id).options(selectinload(Bot.user))
        result = await db.execute(stmt)
        bot = result.scalar_one_or_none()

        if not bot:
            raise NotFoundException("Bot not found for widget deployment")

        return session, bot

    @staticmethod
    async def get_widget_config(
        db: AsyncSession,
        widget_key: str,
        origin: Optional[str],
        referer: Optional[str]
    ) -> Dict[str, Any]:
        """
        Widget 설정 조회 (도메인 검증 포함)

        Args:
            db: DB 세션
            widget_key: Widget Key
            origin: 요청 출처 (선택사항)
            referer: Referer 헤더 (선택사항)

        Returns:
            서명된 Widget 설정
        """
        # 배포 조회 (status 필터 제거 - 존재 여부와 게시 상태를 분리 검증)
        stmt = select(BotDeployment).where(
            BotDeployment.widget_key == widget_key
        )
        result = await db.execute(stmt)
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise NotFoundException("Widget not found")

        # 게시 상태 검증 (명세 255-259: 존재하지만 미게시 시 403)
        if deployment.status != "published":
            raise ForbiddenException(f"Widget is not published (status: {deployment.status})")

        # 도메인 검증 강화 (allowed_domains 설정 시 반드시 검증)
        if deployment.allowed_domains:
            request_origin = extract_domain_from_origin_or_referer(origin, referer)

            # Origin/Referer 둘 다 없으면 거부
            if not request_origin:
                raise ForbiddenException(
                    "Origin or Referer header required when domain restriction is enabled"
                )

            # 도메인 검증
            if not widget_security.verify_domain(request_origin, deployment.allowed_domains):
                raise ForbiddenException(f"Domain '{request_origin}' is not allowed")

        # Bot 정보 로드 (relationship 사용)
        await db.refresh(deployment, ["bot"])

        # 설정 구성 (명세서의 모든 필수 필드 포함)
        config = {
            "bot_id": deployment.bot.bot_id,
            "bot_name": deployment.widget_config.get("bot_name", deployment.bot.name),
            "avatar_url": deployment.widget_config.get("avatar_url"),
            "theme": deployment.widget_config.get("theme", "light"),
            "position": deployment.widget_config.get("position", "bottom-right"),
            "welcome_message": deployment.widget_config.get("welcome_message", "안녕하세요! 무엇을 도와드릴까요?"),
            "placeholder_text": deployment.widget_config.get("placeholder_text", "메시지를 입력하세요..."),
            "primary_color": deployment.widget_config.get("primary_color", "#0066FF"),
            "show_typing_indicator": deployment.widget_config.get("show_typing_indicator", True),
            "auto_open": deployment.widget_config.get("auto_open", False),
            "auto_open_delay": deployment.widget_config.get("auto_open_delay", 5000),
            "enable_file_upload": deployment.widget_config.get("enable_file_upload", False),
            "max_file_size_mb": deployment.widget_config.get("max_file_size_mb", 10),
            "allowed_file_types": deployment.widget_config.get("allowed_file_types", ["pdf", "jpg", "png"]),
            "enable_feedback": deployment.widget_config.get("enable_feedback", True),
            "enable_sound": deployment.widget_config.get("enable_sound", True),
            "save_conversation": deployment.widget_config.get("save_conversation", True),
            "conversation_storage": deployment.widget_config.get("conversation_storage", "localStorage"),
            "features": {
                "file_upload": deployment.widget_config.get("enable_file_upload", False),
                "voice_input": False,
                "feedback": deployment.widget_config.get("enable_feedback", True),
                "save_conversation": deployment.widget_config.get("save_conversation", True),
            },
            "api_endpoints": {
                "session": "/api/v1/widget/sessions",
                "chat": "/api/v1/widget/chat",
                "feedback": "/api/v1/widget/feedback",
                "upload": "/api/v1/widget/upload",
                "track": f"/api/v1/widget/config/{widget_key}/track"
            }
        }

        # 서명 추가
        signed_config = widget_security.sign_config(config, widget_key)
        return signed_config

    @staticmethod
    async def create_session(
        db: AsyncSession,
        session_data: SessionCreateRequest,
        origin: Optional[str],
        referer: Optional[str]
    ) -> Dict[str, Any]:
        """
        Widget 세션 생성

        Args:
            db: DB 세션
            session_data: 세션 생성 데이터
            origin: 요청 출처 (선택사항)
            referer: Referer 헤더 (선택사항)

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

        # HMAC 서명 검증 (DB의 config를 사용하여 payload 재구성)
        if session_data.widget_signature:
            # 중요: DB에서 가져온 deployment.widget_config를 사용하여 payload 재구성
            # 이유:
            #   - sign_config()는 config 전체를 포함하여 서명을 생성함
            #   - 클라이언트는 SessionCreateRequest에 config를 포함하지 않음
            #   - 서버가 DB에서 config를 가져와 동일한 payload를 재구성해야 검증 성공
            #   - 이 방식이 더 안전함 (클라이언트가 config를 조작할 수 없음)

            # Bot 정보 로드 (relationship 사용)
            await db.refresh(deployment, ["bot"])

            # 설정 구성 (get_widget_config와 동일한 로직)
            config = {
                "bot_id": deployment.bot.bot_id,
                "bot_name": deployment.widget_config.get("bot_name", deployment.bot.name),
                "avatar_url": deployment.widget_config.get("avatar_url"),
                "theme": deployment.widget_config.get("theme", "light"),
                "position": deployment.widget_config.get("position", "bottom-right"),
                "welcome_message": deployment.widget_config.get("welcome_message", "안녕하세요! 무엇을 도와드릴까요?"),
                "placeholder_text": deployment.widget_config.get("placeholder_text", "메시지를 입력하세요..."),
                "primary_color": deployment.widget_config.get("primary_color", "#0066FF"),
                "show_typing_indicator": deployment.widget_config.get("show_typing_indicator", True),
                "auto_open": deployment.widget_config.get("auto_open", False),
                "auto_open_delay": deployment.widget_config.get("auto_open_delay", 5000),
                "enable_file_upload": deployment.widget_config.get("enable_file_upload", False),
                "max_file_size_mb": deployment.widget_config.get("max_file_size_mb", 10),
                "allowed_file_types": deployment.widget_config.get("allowed_file_types", ["pdf", "jpg", "png"]),
                "enable_feedback": deployment.widget_config.get("enable_feedback", True),
                "enable_sound": deployment.widget_config.get("enable_sound", True),
                "save_conversation": deployment.widget_config.get("save_conversation", True),
                "conversation_storage": deployment.widget_config.get("conversation_storage", "localStorage"),
                "features": {
                    "file_upload": deployment.widget_config.get("enable_file_upload", False),
                    "voice_input": False,
                    "feedback": deployment.widget_config.get("enable_feedback", True),
                    "save_conversation": deployment.widget_config.get("save_conversation", True),
                },
                "api_endpoints": {
                    "session": "/api/v1/widget/sessions",
                    "chat": "/api/v1/widget/chat",
                    "feedback": "/api/v1/widget/feedback",
                    "upload": "/api/v1/widget/upload",
                    "track": f"/api/v1/widget/config/{session_data.widget_key}/track"
                }
            }

            payload = {
                "config": config,  # DB에서 가져온 config
                "widget_key": session_data.widget_signature.widget_key,
                "expires_at": session_data.widget_signature.expires_at,
                "nonce": session_data.widget_signature.nonce,
                "signature": session_data.widget_signature.signature
            }

            # 서명 검증
            if not widget_security.verify_signature(payload):
                raise ForbiddenException("Invalid widget signature")

            # widget_key 일치 확인
            if session_data.widget_signature.widget_key != session_data.widget_key:
                raise ForbiddenException("Widget key mismatch")

        # 도메인 검증 강화 (allowed_domains 설정 시 반드시 검증)
        if deployment.allowed_domains:
            request_origin = extract_domain_from_origin_or_referer(origin, referer)

            # Origin/Referer 둘 다 없으면 거부
            if not request_origin:
                raise ForbiddenException(
                    "Origin or Referer header required when domain restriction is enabled"
                )

            # 도메인 검증
            if not widget_security.verify_domain(request_origin, deployment.allowed_domains):
                raise ForbiddenException(f"Domain '{request_origin}' is not allowed")

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

        # 세션 생성 (속성명 수정: metadata → session_metadata)
        session = WidgetSession(
            deployment_id=deployment.deployment_id,
            session_token_hash=session_token_hash,
            refresh_token_hash=refresh_token_hash,
            user_info=session_data.user_info.dict() if session_data.user_info else None,
            fingerprint=session_data.fingerprint.dict(),
            fingerprint_hash=fingerprint_hash,
            origin=origin or session_data.context.page_url,
            expires_at=expires_at,
            session_metadata=session_data.context.dict()
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

        # WebSocket URL 구성 (명세 355: 백엔드 API URL 기반)
        from urllib.parse import urlparse
        api_url = settings.api_public_url
        parsed_url = urlparse(api_url)
        ws_protocol = "wss" if parsed_url.scheme == "https" else "ws"
        ws_host = parsed_url.netloc if parsed_url.netloc else "localhost:8001"
        ws_url = f"{ws_protocol}://{ws_host}/ws/widget/chat/{session.session_id}"

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
        session, bot = await WidgetService._load_session_and_bot(db, message_data, session_token)

        # 사용자 메시지 저장 (속성명 수정: metadata → message_metadata)
        user_message = WidgetMessage(
            session_id=session.session_id,
            role="user",
            content=message_data.message["content"],
            message_type=message_data.message.get("type", "text"),
            attachments=message_data.message.get("attachments"),
            message_metadata=message_data.context
        )
        db.add(user_message)

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

        # 봇 응답 저장 (속성명 수정: metadata → message_metadata)
        bot_message = WidgetMessage(
            session_id=session.session_id,
            role="assistant",
            content=chat_response.response,
            sources=[source.dict() for source in chat_response.sources] if chat_response.sources else None,
            message_metadata={"confidence": 0.95}
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
                "metadata": bot_message.message_metadata
            },
            "sources": bot_message.sources or [],
            "suggested_actions": [],
            "timestamp": bot_message.created_at
        }

    @staticmethod
    async def stream_message(
        db: AsyncSession,
        message_data: ChatMessageRequest,
        session_token: str
    ) -> AsyncGenerator[str, None]:
        """위젯 스트리밍 응답 생성"""
        from app.services.chat_service import ChatService
        from app.models.chat import ChatRequest

        session, bot = await WidgetService._load_session_and_bot(db, message_data, session_token)

        user_message = WidgetMessage(
            session_id=session.session_id,
            role="user",
            content=message_data.message["content"],
            message_type=message_data.message.get("type", "text"),
            attachments=message_data.message.get("attachments"),
            message_metadata=message_data.context
        )
        db.add(user_message)

        chat_service = ChatService()
        chat_request = ChatRequest(
            message=message_data.message["content"],
            bot_id=bot.bot_id if bot else None,
            top_k=settings.chat_default_top_k
        )
        user_uuid = str(bot.user.uuid) if bot and bot.user else None

        assistant_chunks: List[str] = []
        sources_payload: List[Dict[str, Any]] = []
        error_event_emitted = False

        try:
            async for event_json in chat_service.generate_response_stream(
                request=chat_request,
                user_uuid=user_uuid,
                db=db
            ):
                try:
                    payload = json.loads(event_json)
                    event_type = payload.get("type")
                    if event_type == "content":
                        assistant_chunks.append(payload.get("data", ""))
                    elif event_type == "sources":
                        sources_payload = payload.get("data") or []
                    elif event_type == "error":
                        error_event_emitted = True
                except json.JSONDecodeError:
                    pass

                yield event_json

        except Exception:
            await db.rollback()
            raise
        else:
            if not error_event_emitted:
                assistant_text = "".join(assistant_chunks)
                if assistant_text:
                    bot_message = WidgetMessage(
                        session_id=session.session_id,
                        role="assistant",
                        content=assistant_text,
                        sources=sources_payload or None,
                        message_metadata={"confidence": 0.95}
                    )
                    db.add(bot_message)

                session.last_activity = datetime.now(timezone.utc)
                await db.commit()
            else:
                await db.rollback()

    @staticmethod
    async def track_usage(
        db: AsyncSession,
        widget_key: str,
        track_data: Dict[str, Any]
    ) -> None:
        """
        Widget 사용 통계 수집

        Args:
            db: DB 세션
            widget_key: Widget Key
            track_data: 추적 데이터
        """
        # 배포 조회
        stmt = select(BotDeployment).where(
            BotDeployment.widget_key == widget_key
        )
        result = await db.execute(stmt)
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise NotFoundException("Widget not found")

        # 통계 업데이트 (향후 구현)
        # 현재는 단순히 성공 처리
        pass
