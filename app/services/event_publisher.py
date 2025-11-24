"""
SQS 기반 비동기 이벤트 발행기
"""
import asyncio
import json
import logging
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config as BotoConfig

from app.config import settings

logger = logging.getLogger(__name__)


class WorkflowEventPublisher:
    """
    워크플로우 관련 비동기 이벤트를 SQS로 발행하는 헬퍼

    - usage_queue_url: LLM 사용량/비용 이벤트
    - log_queue_url: 실행 로그 이벤트
    """

    def __init__(self) -> None:
        self._sqs_client: Optional[Any] = None

    def _get_client(self):
        if self._sqs_client is None:
            client_kwargs: Dict[str, Any] = {
                "region_name": settings.aws_region or "ap-northeast-2",
                "config": BotoConfig(retries={"max_attempts": 3, "mode": "standard"}),
            }
            if settings.aws_access_key_id and settings.aws_secret_access_key:
                client_kwargs.update(
                    {
                        "aws_access_key_id": settings.aws_access_key_id,
                        "aws_secret_access_key": settings.aws_secret_access_key,
                    }
                )
            self._sqs_client = boto3.client("sqs", **client_kwargs)
        return self._sqs_client

    async def _send_message(self, queue_url: str, payload: Dict[str, Any]) -> None:
        if not queue_url:
            return

        body = json.dumps(payload, ensure_ascii=False, default=str)
        client = self._get_client()
        await asyncio.to_thread(
            client.send_message,
            QueueUrl=queue_url,
            MessageBody=body,
        )
        logger.debug("Published event to %s", queue_url)

    async def publish_usage_event(self, payload: Dict[str, Any]) -> None:
        """LLM 사용량 이벤트 발행"""
        if not settings.usage_queue_url:
            logger.debug("Usage queue URL not configured. Skip publishing.")
            return
        await self._send_message(settings.usage_queue_url, payload)

    async def publish_log_event(self, payload: Dict[str, Any]) -> None:
        """워크플로우 실행 로그 이벤트 발행"""
        if not settings.log_queue_url:
            logger.debug("Log queue URL not configured. Skip publishing.")
            return
        await self._send_message(settings.log_queue_url, payload)
