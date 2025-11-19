"""
마켓플레이스 모델
"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Text, Index, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import uuid

from app.core.database import Base


class MarketplaceItem(Base):
    """마켓플레이스 아이템 테이블 (전체 공개 에이전트)"""
    __tablename__ = "marketplace_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 워크플로우 버전 참조
    workflow_version_id = Column(UUID(as_uuid=True), ForeignKey('bot_workflow_versions.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)

    # 게시자 정보
    publisher_team_id = Column(String(36), nullable=True, index=True)
    publisher_user_id = Column(String(36), ForeignKey('users.uuid', ondelete='SET NULL'), nullable=True)

    # 마켓플레이스 상태
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    status = Column(String(20), default='published', nullable=False)  # published, suspended, draft

    # 마켓플레이스 메타데이터 (워크플로우 버전의 메타데이터와 별도 관리 가능)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True, index=True)
    tags = Column(JSONB, nullable=True)

    # 미리보기 이미지 및 스크린샷
    thumbnail_url = Column(String(500), nullable=True)
    screenshots = Column(JSONB, nullable=True)  # ["url1", "url2", ...]

    # 통계
    download_count = Column(Integer, default=0, nullable=False)
    view_count = Column(Integer, default=0, nullable=False)
    rating_average = Column(Float, default=0.0, nullable=False)
    rating_count = Column(Integer, default=0, nullable=False)

    # 추가 정보
    readme = Column(Text, nullable=True)  # 마크다운 형식 상세 설명
    use_cases = Column(JSONB, nullable=True)  # 사용 사례 목록

    # 타임스탬프
    published_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 관계
    workflow_version = relationship("BotWorkflowVersion", foreign_keys=[workflow_version_id])
    publisher_team = None
    publisher_user = relationship("User", foreign_keys=[publisher_user_id])

    # 인덱스
    __table_args__ = (
        Index('ix_marketplace_items_category_active', 'category', 'is_active'),
        Index('ix_marketplace_items_published_at_desc', published_at.desc()),
        Index('ix_marketplace_items_download_count_desc', download_count.desc()),
        Index('ix_marketplace_items_rating_desc', rating_average.desc()),
        {"extend_existing": True},
    )


class MarketplaceReview(Base):
    """마켓플레이스 리뷰 테이블"""
    __tablename__ = "marketplace_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    marketplace_item_id = Column(UUID(as_uuid=True), ForeignKey('marketplace_items.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey('users.uuid', ondelete='CASCADE'), nullable=False, index=True)

    # 리뷰 내용
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)

    # 타임스탬프
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 관계
    marketplace_item = relationship("MarketplaceItem")
    user = relationship("User")

    # 인덱스
    __table_args__ = (
        Index('uq_marketplace_reviews_item_user', 'marketplace_item_id', 'user_id', unique=True),
        {"extend_existing": True},
    )
