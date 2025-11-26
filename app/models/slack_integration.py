"""
Slack Integration Model
사용자별 Slack OAuth 연동 정보 저장
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class SlackIntegration(Base):
    """
    Slack OAuth 연동 정보
    
    각 사용자가 자신의 Slack 워크스페이스를 SnapAgent에 연결할 수 있습니다.
    """
    __tablename__ = "slack_integrations"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bot_id = Column(String, ForeignKey("bots.bot_id", ondelete="CASCADE"), nullable=True, index=True)
    
    # OAuth 정보 (암호화 저장)
    access_token = Column(Text, nullable=False)  # 암호화된 Bot 토큰
    user_access_token = Column(Text, nullable=True)  # 암호화된 User 토큰 (선택)
    
    # Workspace 정보
    workspace_id = Column(String, nullable=False)
    workspace_name = Column(String, nullable=False)
    workspace_icon = Column(String, nullable=True)
    
    # Bot 정보
    bot_user_id = Column(String, nullable=True)
    authed_user_id = Column(String, nullable=True)  # OAuth 승인한 사용자 ID
    authed_user_scopes = Column(JSON, nullable=True, default=list)
    
    # 권한 범위
    scopes = Column(JSON, nullable=False, default=list)
    
    # 상태
    is_active = Column(Boolean, default=True, nullable=False)
    
    # 타임스탬프
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # 토큰 만료 시간 (있는 경우)
    
    # 관계
    user = relationship("User", back_populates="slack_integrations")
    bot = relationship("Bot", back_populates="slack_integration")
    
    @property
    def has_user_token(self) -> bool:
        """User 토큰 저장 여부"""
        return bool(self.user_access_token)
    
    def __repr__(self):
        return f"<SlackIntegration(id={self.id}, user_id={self.user_id}, workspace={self.workspace_name})>"
