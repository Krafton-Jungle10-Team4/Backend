"""
Slack Node V2
워크플로우에서 Slack 채널로 메시지를 전송하는 노드
"""
from typing import Any, Dict, Optional
import os
import logging

from app.core.workflow.base_node_v2 import (
    BaseNodeV2,
    NodeExecutionContext,
    NodePortSchema,
    PortDefinition,
    PortType,
)

logger = logging.getLogger(__name__)


class SlackNodeV2(BaseNodeV2):
    """
    Slack 메시지 전송 노드
    
    워크플로우 실행 결과를 Slack 채널로 전송합니다.
    
    Configuration:
        - channel: Slack 채널 ID 또는 이름 (예: C12345678 또는 #general)
        - use_blocks: 메시지 블록 사용 여부 (기본: false)
        
    Input Ports:
        - text: 전송할 메시지 텍스트 (필수)
        - title: 메시지 제목 (선택, use_blocks=true일 때 사용)
        
    Output Ports:
        - success: 전송 성공 여부 (boolean)
        - message_ts: Slack 메시지 타임스탬프
        - channel: 메시지가 전송된 채널 ID
        - error: 에러 메시지 (실패 시)
    """
    
    def get_port_schema(self) -> NodePortSchema:
        """포트 스키마 정의"""
        return NodePortSchema(
            inputs=[
                PortDefinition(
                    name="text",
                    type=PortType.STRING,
                    required=True,
                    description="전송할 메시지 텍스트"
                ),
                PortDefinition(
                    name="title",
                    type=PortType.STRING,
                    required=False,
                    description="메시지 제목 (블록 사용 시)"
                ),
            ],
            outputs=[
                PortDefinition(
                    name="success",
                    type=PortType.BOOLEAN,
                    description="전송 성공 여부"
                ),
                PortDefinition(
                    name="message_ts",
                    type=PortType.STRING,
                    description="Slack 메시지 타임스탬프"
                ),
                PortDefinition(
                    name="channel",
                    type=PortType.STRING,
                    description="메시지가 전송된 채널 ID"
                ),
                PortDefinition(
                    name="error",
                    type=PortType.STRING,
                    description="에러 메시지 (실패 시)"
                ),
            ]
        )
    
    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        Slack 메시지 전송 실행
        
        Args:
            context: 실행 컨텍스트
            
        Returns:
            Dict[str, Any]: {success, message_ts, channel, error}
        """
        # 입력 조회
        text = context.get_input("text")
        if not text:
            logger.error(f"[SlackNodeV2] Text input is required for node {self.node_id}")
            return {
                "success": False,
                "message_ts": "",
                "channel": "",
                "error": "Text input is required"
            }
        
        title = context.get_input("title") or ""
        
        # 설정 조회
        logger.info(f"[SlackNodeV2] Config for node {self.node_id}: {self.config}")
        channel = self.config.get("channel")
        if not channel:
            logger.error(f"[SlackNodeV2] Channel configuration is required for node {self.node_id}. Config keys: {list(self.config.keys())}")
            return {
                "success": False,
                "message_ts": "",
                "channel": "",
                "error": "Channel configuration is required"
            }
        
        use_blocks = self.config.get("use_blocks", False)
        
        # OAuth 방식: integration_id로 토큰 조회
        integration_id = self.config.get("integration_id")
        slack_token = None
        
        if integration_id:
            # DB에서 연동 정보 조회
            try:
                from app.core.database import AsyncSessionLocal
                from app.services.slack_service import SlackService
                from sqlalchemy import select
                from app.models.slack_integration import SlackIntegration
                
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(SlackIntegration).where(
                            SlackIntegration.id == integration_id,
                            SlackIntegration.is_active == True
                        )
                    )
                    integration = result.scalar_one_or_none()
                    
                    if integration:
                        # 토큰 복호화
                        slack_token = SlackService.decrypt_token(integration.access_token)
                        logger.info(f"[SlackNodeV2] Using OAuth token from integration {integration_id}")
                    else:
                        logger.warning(f"[SlackNodeV2] Integration {integration_id} not found or inactive")
            except Exception as e:
                logger.error(f"[SlackNodeV2] Failed to load integration: {e}")
        
        # 환경 변수 fallback (기존 방식)
        if not slack_token:
            slack_token = os.environ.get("SLACK_BOT_TOKEN")
            if slack_token:
                logger.info("[SlackNodeV2] Using SLACK_BOT_TOKEN from environment")
        
        if not slack_token:
            logger.error("[SlackNodeV2] No Slack token available")
            return {
                "success": False,
                "message_ts": "",
                "channel": "",
                "error": "Slack token is not configured. Please connect Slack integration or set SLACK_BOT_TOKEN."
            }
        
        # Slack 메시지 전송
        try:
            from slack_sdk import WebClient
            from slack_sdk.errors import SlackApiError
            
            client = WebClient(token=slack_token)
            
            # 메시지 블록 생성 (use_blocks=true인 경우)
            blocks = None
            if use_blocks and title:
                blocks = [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": title,
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": text
                        }
                    }
                ]
            
            # 메시지 전송
            response = client.chat_postMessage(
                channel=channel,
                text=text,
                blocks=blocks
            )
            
            logger.info(f"[SlackNodeV2] Message sent to Slack channel: {response['channel']}")
            
            return {
                "success": True,
                "message_ts": response["ts"],
                "channel": response["channel"],
                "error": ""
            }
            
        except SlackApiError as e:
            error_msg = f"Slack API Error: {e.response['error']}"
            logger.error(f"[SlackNodeV2] {error_msg}")
            return {
                "success": False,
                "message_ts": "",
                "channel": channel,
                "error": error_msg
            }
        except ImportError:
            error_msg = "slack-sdk is not installed. Please run: pip install slack-sdk"
            logger.error(f"[SlackNodeV2] {error_msg}")
            return {
                "success": False,
                "message_ts": "",
                "channel": channel,
                "error": error_msg
            }
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"[SlackNodeV2] {error_msg}")
            return {
                "success": False,
                "message_ts": "",
                "channel": channel,
                "error": error_msg
            }
    
    def validate(self) -> tuple[bool, Optional[str]]:
        """노드 설정 검증"""
        if not self.config.get("channel"):
            return False, "Channel configuration is required"
        
        return True, None

