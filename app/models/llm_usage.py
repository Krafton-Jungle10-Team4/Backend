"""
LLM 사용량 및 비용 추적 모델
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime

from app.core.database import Base


class LLMUsageLog(Base):
    """LLM 사용 로그 테이블"""
    __tablename__ = "llm_usage_logs"

    id = Column(Integer, primary_key=True, index=True)

    # 봇 및 사용자 정보
    bot_id = Column(String(100), ForeignKey("bots.bot_id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # LLM 제공자 및 모델 정보
    provider = Column(String(50), nullable=False, index=True)  # 'bedrock', 'openai', 'anthropic', etc.
    model_name = Column(String(100), nullable=False, index=True)

    # 토큰 사용량
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)

    # 캐시 토큰 (Bedrock 전용)
    cache_read_tokens = Column(Integer, nullable=True, default=0)
    cache_write_tokens = Column(Integer, nullable=True, default=0)

    # 비용 정보 (USD)
    input_cost = Column(Float, nullable=False, default=0.0)
    output_cost = Column(Float, nullable=False, default=0.0)
    total_cost = Column(Float, nullable=False, default=0.0)

    # 요청 메타데이터
    request_id = Column(String(100), nullable=True, index=True)
    session_id = Column(String(100), nullable=True, index=True)

    # 타임스탬프
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # 관계
    bot = relationship("Bot", backref="usage_logs")
    user = relationship("User", backref="llm_usage_logs")

    # 복합 인덱스 (성능 최적화)
    __table_args__ = (
        Index('idx_bot_created', 'bot_id', 'created_at'),
        Index('idx_user_created', 'user_id', 'created_at'),
        Index('idx_provider_model_created', 'provider', 'model_name', 'created_at'),
    )

    def __repr__(self):
        return f"<LLMUsageLog(bot_id={self.bot_id}, model={self.model_name}, cost=${self.total_cost:.4f})>"


class ModelPricing(Base):
    """모델별 가격 정보 테이블"""
    __tablename__ = "model_pricing"

    id = Column(Integer, primary_key=True, index=True)

    # 모델 식별
    provider = Column(String(50), nullable=False, index=True)
    model_name = Column(String(100), nullable=False, index=True)

    # 가격 정보 (USD per 1000 tokens)
    input_price_per_1k = Column(Float, nullable=False)  # 입력 토큰 1000개당 비용
    output_price_per_1k = Column(Float, nullable=False)  # 출력 토큰 1000개당 비용

    # 캐시 가격 (선택적, Bedrock 등에서 사용)
    cache_write_price_per_1k = Column(Float, nullable=True)
    cache_read_price_per_1k = Column(Float, nullable=True)

    # 메타데이터
    region = Column(String(50), nullable=True)  # AWS 리전
    is_active = Column(Integer, default=1, nullable=False)  # 활성화 여부

    # 타임스탬프
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 유니크 제약 (provider + model_name 조합은 유일)
    __table_args__ = (
        Index('idx_provider_model_unique', 'provider', 'model_name', unique=True),
    )

    def __repr__(self):
        return f"<ModelPricing(provider={self.provider}, model={self.model_name}, input=${self.input_price_per_1k:.4f}/1k)>"
