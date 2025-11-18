"""
워크플로우 실행 기록 서비스

워크플로우 실행 기록 조회, 노드 실행 상세 조회 등의 기능을 제공합니다.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func, or_, cast, String
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import logging

from app.models.workflow_version import WorkflowExecutionRun, WorkflowNodeExecution, WorkflowRunAnnotation

logger = logging.getLogger(__name__)


class WorkflowExecutionService:
    """워크플로우 실행 기록 서비스"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_runs(
        self,
        bot_id: str,
        status: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        실행 기록 목록 조회 (페이지네이션 지원)

        Args:
            bot_id: 봇 ID
            status: 필터링할 상태 (선택사항)
            start_date: 시작 날짜 (선택사항)
            end_date: 종료 날짜 (선택사항)
            limit: 조회할 개수
            offset: 건너뛸 개수

        Returns:
            Dict: {
                "items": List[WorkflowExecutionRun],
                "total": int,
                "limit": int,
                "offset": int
            }
        """
        # 기본 쿼리
        stmt = select(WorkflowExecutionRun).where(
            WorkflowExecutionRun.bot_id == bot_id
        )

        # 필터 적용
        if status:
            stmt = stmt.where(WorkflowExecutionRun.status == status)

        if start_date:
            stmt = stmt.where(WorkflowExecutionRun.started_at >= start_date)

        if end_date:
            stmt = stmt.where(WorkflowExecutionRun.started_at <= end_date)

        if search:
            like_pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    cast(WorkflowExecutionRun.id, String).ilike(like_pattern),
                    WorkflowExecutionRun.session_id.ilike(like_pattern),
                    cast(WorkflowExecutionRun.inputs, String).ilike(like_pattern),
                    cast(WorkflowExecutionRun.outputs, String).ilike(like_pattern)
                )
            )

        # 총 개수 조회
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar_one()

        # 페이지네이션 적용
        stmt = stmt.order_by(desc(WorkflowExecutionRun.started_at))
        stmt = stmt.limit(limit).offset(offset)

        result = await self.db.execute(stmt)
        runs = result.scalars().all()

        return {
            "items": list(runs),
            "total": total,
            "limit": limit,
            "offset": offset
        }

    async def get_run(
        self,
        run_id: str
    ) -> Optional[WorkflowExecutionRun]:
        """
        특정 실행 기록 조회

        Args:
            run_id: 실행 기록 ID

        Returns:
            Optional[WorkflowExecutionRun]: 실행 기록 또는 None
        """
        stmt = select(WorkflowExecutionRun).where(
            WorkflowExecutionRun.id == run_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_node_executions(
        self,
        run_id: str
    ) -> List[WorkflowNodeExecution]:
        """
        특정 실행의 노드 실행 기록 목록 조회

        Args:
            run_id: 실행 기록 ID

        Returns:
            List[WorkflowNodeExecution]: 노드 실행 기록 목록
        """
        stmt = select(WorkflowNodeExecution).where(
            WorkflowNodeExecution.workflow_run_id == run_id
        ).order_by(WorkflowNodeExecution.execution_order)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_node_execution(
        self,
        node_execution_id: str
    ) -> Optional[WorkflowNodeExecution]:
        """
        특정 노드 실행 기록 조회

        Args:
            node_execution_id: 노드 실행 기록 ID

        Returns:
            Optional[WorkflowNodeExecution]: 노드 실행 기록 또는 None
        """
        stmt = select(WorkflowNodeExecution).where(
            WorkflowNodeExecution.id == node_execution_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_run_statistics(
        self,
        bot_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        실행 통계 조회

        Args:
            bot_id: 봇 ID
            start_date: 시작 날짜 (선택사항)
            end_date: 종료 날짜 (선택사항)

        Returns:
            Dict: {
                "total_runs": int,
                "succeeded_runs": int,
                "failed_runs": int,
                "avg_elapsed_time": float,
                "total_tokens": int
            }
        """
        # 기본 쿼리
        stmt = select(WorkflowExecutionRun).where(
            WorkflowExecutionRun.bot_id == bot_id
        )

        # 날짜 필터
        if start_date:
            stmt = stmt.where(WorkflowExecutionRun.created_at >= start_date)
        if end_date:
            stmt = stmt.where(WorkflowExecutionRun.created_at <= end_date)

        result = await self.db.execute(stmt)
        runs = result.scalars().all()

        # 통계 계산
        total_runs = len(runs)
        succeeded_runs = sum(1 for r in runs if r.status == "succeeded")
        failed_runs = sum(1 for r in runs if r.status == "failed")

        # 평균 실행 시간 (milliseconds)
        elapsed_times = [r.elapsed_time for r in runs if r.elapsed_time is not None]
        avg_elapsed_time = sum(elapsed_times) / len(elapsed_times) if elapsed_times else 0

        # 총 토큰 사용량
        total_tokens = sum(r.total_tokens or 0 for r in runs)

        return {
            "total_runs": total_runs,
            "succeeded_runs": succeeded_runs,
            "failed_runs": failed_runs,
            "avg_elapsed_time": round(avg_elapsed_time, 2),
            "total_tokens": total_tokens
        }

    async def get_token_statistics(
        self,
        bot_id: str,
        run_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """토큰 사용량 통계 조회"""

        stmt = select(
            func.coalesce(func.sum(WorkflowExecutionRun.total_tokens), 0).label('total_tokens'),
            func.count(WorkflowExecutionRun.id).label('total_runs')
        ).where(WorkflowExecutionRun.bot_id == bot_id)

        if run_id:
            stmt = stmt.where(WorkflowExecutionRun.id == run_id)
        if start_date:
            stmt = stmt.where(WorkflowExecutionRun.started_at >= start_date)
        if end_date:
            stmt = stmt.where(WorkflowExecutionRun.started_at <= end_date)

        stats_result = await self.db.execute(stmt)
        stats = stats_result.first()

        node_query = select(
            WorkflowNodeExecution.node_type,
            func.coalesce(func.sum(WorkflowNodeExecution.tokens_used), 0).label('tokens')
        ).join(
            WorkflowExecutionRun,
            WorkflowNodeExecution.workflow_run_id == WorkflowExecutionRun.id
        ).where(
            WorkflowExecutionRun.bot_id == bot_id
        ).group_by(WorkflowNodeExecution.node_type)

        if run_id:
            node_query = node_query.where(WorkflowExecutionRun.id == run_id)
        if start_date:
            node_query = node_query.where(WorkflowExecutionRun.started_at >= start_date)
        if end_date:
            node_query = node_query.where(WorkflowExecutionRun.started_at <= end_date)

        node_result = await self.db.execute(node_query)
        by_node_type = {
            row.node_type: int(row.tokens or 0)
            for row in node_result.all()
        }

        date_query = select(
            func.date_trunc('day', WorkflowExecutionRun.started_at).label('bucket'),
            func.coalesce(func.sum(WorkflowExecutionRun.total_tokens), 0).label('tokens')
        ).where(
            WorkflowExecutionRun.bot_id == bot_id
        ).group_by('bucket').order_by('bucket')

        if run_id:
            date_query = date_query.where(WorkflowExecutionRun.id == run_id)
        if start_date:
            date_query = date_query.where(WorkflowExecutionRun.started_at >= start_date)
        if end_date:
            date_query = date_query.where(WorkflowExecutionRun.started_at <= end_date)

        date_result = await self.db.execute(date_query)
        by_date = [
            {
                "date": (row.bucket.date().isoformat() if row.bucket else None),
                "tokens": int(row.tokens or 0)
            }
            for row in date_result.all()
            if row.bucket is not None
        ]

        total_tokens = int(stats.total_tokens) if stats and stats.total_tokens is not None else 0
        total_runs = int(stats.total_runs) if stats and stats.total_runs is not None else 0
        avg_tokens = total_tokens / total_runs if total_runs > 0 else 0.0

        return {
            "total_tokens": total_tokens,
            "total_runs": total_runs,
            "average_tokens_per_run": avg_tokens,
            "by_node_type": by_node_type,
            "by_date": by_date
        }

    async def get_annotation(
        self,
        run_id: str,
        user_id: int
    ) -> Optional[WorkflowRunAnnotation]:
        """사용자 어노테이션 조회"""

        stmt = select(WorkflowRunAnnotation).where(
            WorkflowRunAnnotation.workflow_run_id == run_id,
            WorkflowRunAnnotation.user_id == user_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_annotation(
        self,
        bot_id: str,
        run_id: str,
        user_id: int,
        annotation: str
    ) -> WorkflowRunAnnotation:
        """어노테이션 생성/수정"""

        record = await self.get_annotation(run_id, user_id)

        if record:
            record.annotation = annotation
            record.updated_at = datetime.utcnow()
        else:
            record = WorkflowRunAnnotation(
                workflow_run_id=run_id,
                bot_id=bot_id,
                user_id=user_id,
                annotation=annotation
            )
            self.db.add(record)

        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def delete_run(
        self,
        run_id: str
    ) -> bool:
        """
        실행 기록 삭제

        Args:
            run_id: 실행 기록 ID

        Returns:
            bool: 삭제 성공 여부
        """
        stmt = select(WorkflowExecutionRun).where(
            WorkflowExecutionRun.id == run_id
        )
        result = await self.db.execute(stmt)
        run = result.scalar_one_or_none()

        if not run:
            return False

        await self.db.delete(run)
        await self.db.commit()

        logger.info(f"Deleted workflow execution run {run_id}")
        return True

    async def cleanup_old_runs(
        self,
        bot_id: str,
        days_to_keep: int = 30
    ) -> int:
        """
        오래된 실행 기록 정리

        Args:
            bot_id: 봇 ID
            days_to_keep: 보관할 일수

        Returns:
            int: 삭제된 기록 개수
        """
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)

        stmt = select(WorkflowExecutionRun).where(
            and_(
                WorkflowExecutionRun.bot_id == bot_id,
                WorkflowExecutionRun.created_at < cutoff_date
            )
        )
        result = await self.db.execute(stmt)
        old_runs = result.scalars().all()

        count = len(old_runs)
        for run in old_runs:
            await self.db.delete(run)

        await self.db.commit()

        logger.info(f"Cleaned up {count} old execution runs for bot {bot_id}")
        return count
