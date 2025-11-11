"""
AWS S3 및 SQS 클라이언트 유틸리티
"""
import boto3
from botocore.exceptions import ClientError
from app.config import settings
from app.core.logging_config import get_logger
from typing import Optional, Dict, Any
import json

logger = get_logger(__name__)


class S3Client:
    """AWS S3 클라이언트"""

    def __init__(self):
        # ECS Task Role을 사용하기 위해 자격증명 파라미터를 생략
        # boto3가 자동으로 ECS Task Role 또는 환경 변수에서 자격증명을 가져옴
        client_config = {'region_name': settings.aws_region}

        # 로컬 개발 환경에서만 명시적 자격증명 사용
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            client_config['aws_access_key_id'] = settings.aws_access_key_id
            client_config['aws_secret_access_key'] = settings.aws_secret_access_key

        self.client = boto3.client('s3', **client_config)
        self.bucket_name = settings.s3_bucket_name

    async def upload_file(
        self,
        file_content: bytes,
        key: str,
        content_type: str = "application/octet-stream"
    ) -> str:
        """
        S3에 파일 업로드

        Args:
            file_content: 파일 바이너리 데이터
            key: S3 키 (경로)
            content_type: MIME 타입

        Returns:
            S3 URI (s3://bucket/key)
        """
        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=file_content,
                ContentType=content_type
            )
            s3_uri = f"s3://{self.bucket_name}/{key}"
            logger.info(f"S3 업로드 성공: {s3_uri}")
            return s3_uri
        except ClientError as e:
            logger.error(f"S3 업로드 실패: {e}")
            raise

    async def download_file(self, key: str) -> bytes:
        """
        S3에서 파일 다운로드

        Args:
            key: S3 키 (경로)

        Returns:
            파일 바이너리 데이터
        """
        try:
            response = self.client.get_object(
                Bucket=self.bucket_name,
                Key=key
            )
            content = response['Body'].read()
            logger.info(f"S3 다운로드 성공: s3://{self.bucket_name}/{key}")
            return content
        except ClientError as e:
            logger.error(f"S3 다운로드 실패: {e}")
            raise

    async def delete_file(self, key: str) -> None:
        """
        S3에서 파일 삭제

        Args:
            key: S3 키 (경로)
        """
        try:
            self.client.delete_object(
                Bucket=self.bucket_name,
                Key=key
            )
            logger.info(f"S3 삭제 성공: s3://{self.bucket_name}/{key}")
        except ClientError as e:
            logger.error(f"S3 삭제 실패: {e}")
            raise

    def generate_s3_key(self, bot_id: str, document_id: str, filename: str) -> str:
        """
        S3 키 생성 (경로 구조)

        Args:
            bot_id: 봇 ID
            document_id: 문서 ID
            filename: 파일명

        Returns:
            S3 키 (예: bot_123/doc_456/파일.pdf)
        """
        return f"{bot_id}/{document_id}/{filename}"


class SQSClient:
    """AWS SQS 클라이언트"""

    def __init__(self):
        # ECS Task Role을 사용하기 위해 자격증명 파라미터를 생략
        client_config = {'region_name': settings.aws_region}

        # 로컬 개발 환경에서만 명시적 자격증명 사용
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            client_config['aws_access_key_id'] = settings.aws_access_key_id
            client_config['aws_secret_access_key'] = settings.aws_secret_access_key

        self.client = boto3.client('sqs', **client_config)
        self.queue_url = settings.sqs_queue_url
        self.dlq_url = settings.sqs_dlq_url

    async def send_message(
        self,
        message_body: Dict[str, Any],
        delay_seconds: int = 0
    ) -> str:
        """
        SQS 큐에 메시지 전송

        Args:
            message_body: 메시지 본문 (dict)
            delay_seconds: 지연 시간 (초)

        Returns:
            메시지 ID
        """
        try:
            response = self.client.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(message_body),
                DelaySeconds=delay_seconds
            )
            message_id = response['MessageId']
            logger.info(f"SQS 메시지 전송 성공: {message_id}")
            return message_id
        except ClientError as e:
            logger.error(f"SQS 메시지 전송 실패: {e}")
            raise

    async def receive_messages(
        self,
        max_messages: int = 1,
        wait_time_seconds: int = 20
    ) -> list:
        """
        SQS 큐에서 메시지 수신 (Long Polling)

        Args:
            max_messages: 최대 수신 개수
            wait_time_seconds: 대기 시간 (Long Polling)

        Returns:
            메시지 리스트
        """
        try:
            response = self.client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time_seconds,
                MessageAttributeNames=['All']
            )
            messages = response.get('Messages', [])
            logger.info(f"SQS 메시지 수신: {len(messages)}개")
            return messages
        except ClientError as e:
            logger.error(f"SQS 메시지 수신 실패: {e}")
            raise

    async def delete_message(self, receipt_handle: str) -> None:
        """
        SQS 큐에서 메시지 삭제

        Args:
            receipt_handle: 메시지 수신 핸들
        """
        try:
            self.client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )
            logger.info("SQS 메시지 삭제 성공")
        except ClientError as e:
            logger.error(f"SQS 메시지 삭제 실패: {e}")
            raise


# 싱글톤 인스턴스
_s3_client: Optional[S3Client] = None
_sqs_client: Optional[SQSClient] = None


def get_s3_client() -> S3Client:
    """S3 클라이언트 싱글톤"""
    global _s3_client
    if _s3_client is None:
        _s3_client = S3Client()
    return _s3_client


def get_sqs_client() -> SQSClient:
    """SQS 클라이언트 싱글톤"""
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = SQSClient()
    return _sqs_client
