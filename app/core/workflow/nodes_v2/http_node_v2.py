"""
HTTP Node V2
HTTP 요청을 전송하는 워크플로우 노드
"""
import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

from app.core.workflow.base_node_v2 import (
    BaseNodeV2,
    NodeExecutionContext,
    NodePortSchema,
    PortDefinition,
    PortType,
)

logger = logging.getLogger(__name__)


class HTTPNodeV2(BaseNodeV2):
    """
    HTTP 요청 노드

    외부 API 호출, 웹훅 전송, 데이터 수집 등에 사용
    """

    def get_port_schema(self) -> NodePortSchema:
        """포트 스키마 정의"""
        return NodePortSchema(
            inputs=[
                PortDefinition(
                    name="url",
                    type=PortType.STRING,
                    required=False,
                    description="요청할 URL (변수 지원: {{node.port}})"
                ),
                PortDefinition(
                    name="method",
                    type=PortType.STRING,
                    required=False,
                    default_value="GET",
                    description="HTTP 메서드 (GET, POST, PUT, DELETE, PATCH)"
                ),
                PortDefinition(
                    name="headers",
                    type=PortType.OBJECT,
                    required=False,
                    description="요청 헤더 (JSON 객체)"
                ),
                PortDefinition(
                    name="query_params",
                    type=PortType.OBJECT,
                    required=False,
                    description="쿼리 파라미터 (JSON 객체)"
                ),
                PortDefinition(
                    name="body",
                    type=PortType.STRING,
                    required=False,
                    description="요청 본문 (POST/PUT/PATCH용, JSON 문자열)"
                ),
                PortDefinition(
                    name="timeout",
                    type=PortType.NUMBER,
                    required=False,
                    default_value=30,
                    description="타임아웃 (초)"
                ),
            ],
            outputs=[
                PortDefinition(
                    name="status_code",
                    type=PortType.NUMBER,
                    description="HTTP 상태 코드"
                ),
                PortDefinition(
                    name="body",
                    type=PortType.STRING,
                    description="응답 본문"
                ),
                PortDefinition(
                    name="headers",
                    type=PortType.OBJECT,
                    description="응답 헤더"
                ),
                PortDefinition(
                    name="success",
                    type=PortType.BOOLEAN,
                    description="요청 성공 여부 (2xx 상태 코드)"
                ),
                PortDefinition(
                    name="error",
                    type=PortType.STRING,
                    description="에러 메시지 (실패 시)"
                ),
            ]
        )

    def _substitute_variables(self, text: str, context: NodeExecutionContext) -> str:
        """
        문자열 내의 {{variable}} 형태를 실제 값으로 치환

        Args:
            text: 치환할 문자열
            context: 노드 실행 컨텍스트

        Returns:
            치환된 문자열
        """
        if not text or not isinstance(text, str):
            return text

        # 모든 변수 가져오기
        all_vars = {}
        if hasattr(context, 'variable_pool'):
            try:
                all_vars_dict = context.variable_pool.to_dict()
                all_vars = {
                    **all_vars_dict.get("node_outputs", {}),
                    **all_vars_dict.get("environment_variables", {}),
                    **all_vars_dict.get("system_variables", {}),
                    **all_vars_dict.get("conversation_variables", {})
                }
            except Exception as e:
                logger.warning(f"[HTTPNode] Variable pool 접근 실패: {e}")

        # {{variable}} 패턴 찾아서 치환
        def replace_var(match):
            var_path = match.group(1).strip()
            # 중첩 딕셔너리 경로 처리 (예: nodes.start.bot_id)
            keys = var_path.split('.')
            value = all_vars
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    logger.warning(f"[HTTPNode] 변수 '{var_path}' 찾을 수 없음")
                    return match.group(0)  # 원본 유지
            return str(value)

        result = re.sub(r'\{\{([^}]+)\}\}', replace_var, text)
        return result

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        HTTP 요청 실행

        Args:
            context: 노드 실행 컨텍스트

        Returns:
            응답 데이터 딕셔너리
        """
        # 입력 수집 (config 우선, 없으면 포트 입력 사용)
        url = self.config.get("url") or context.get_input("url") or ""
        method = (self.config.get("method") or context.get_input("method") or "GET").upper()
        headers = self.config.get("headers") or context.get_input("headers") or {}

        # query_params 처리 (config는 배열 형태, 포트 입력은 딕셔너리)
        query_params_raw = self.config.get("query_params") or context.get_input("query_params") or {}
        if isinstance(query_params_raw, list):
            # 배열 형태 [{key: "...", value: "..."}, ...] → 딕셔너리로 변환
            query_params = {item["key"]: item["value"] for item in query_params_raw if isinstance(item, dict) and "key" in item}
        else:
            query_params = query_params_raw

        body_str = self.config.get("body") or context.get_input("body") or None
        timeout = self.config.get("timeout") or context.get_input("timeout") or 30

        # 변수 치환 수행
        url = self._substitute_variables(url, context)

        # 헤더 값들도 변수 치환
        if isinstance(headers, dict):
            headers = {k: self._substitute_variables(str(v), context) if isinstance(v, str) else v
                      for k, v in headers.items()}

        # query_params 값들도 변수 치환
        if isinstance(query_params, dict):
            query_params = {k: self._substitute_variables(str(v), context) if isinstance(v, str) else v
                           for k, v in query_params.items()}

        # Body도 변수 치환
        if body_str and isinstance(body_str, str):
            body_str = self._substitute_variables(body_str, context)

        # JWT 자동 주입
        if hasattr(context, 'variable_pool'):
            try:
                jwt_token = context.variable_pool.get_system_variable("jwt_token")
                if jwt_token and isinstance(headers, dict):
                    # Authorization 헤더가 없거나 비어있으면 자동 추가
                    if not headers.get("Authorization"):
                        headers["Authorization"] = f"Bearer {jwt_token}"
                        logger.info("[HTTPNode] JWT 토큰 자동 주입됨")
            except Exception as e:
                logger.warning(f"[HTTPNode] JWT 토큰 조회 실패: {e}")

        # 디버깅용: Authorization 헤더가 있으면 앞부분만 로그에 출력
        auth_header_info = ""
        if headers.get("Authorization"):
            auth_value = headers["Authorization"]
            if auth_value.startswith("Bearer "):
                token_preview = auth_value[7:27] + "..."  # 처음 20자만
                auth_header_info = f", Auth=Bearer {token_preview}"

        logger.info(
            f"[HTTPNode] 요청 시작: {method} {url} "
            f"(timeout={timeout}s, headers={len(headers)}{auth_header_info})"
        )

        # 메서드 검증
        allowed_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
        if method not in allowed_methods:
            error_msg = f"지원하지 않는 HTTP 메서드: {method}"
            logger.error(f"[HTTPNode] {error_msg}")
            return {
                "status_code": 0,
                "body": "",
                "headers": {},
                "success": False,
                "error": error_msg,
            }

        # Body 파싱 (JSON 문자열 → 객체)
        body_data = None
        if body_str and method in ["POST", "PUT", "PATCH"]:
            try:
                body_data = json.loads(body_str) if isinstance(body_str, str) else body_str
            except json.JSONDecodeError as e:
                logger.warning(f"[HTTPNode] Body JSON 파싱 실패, 문자열로 전송: {e}")
                body_data = body_str

        # HTTP 요청 실행
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                # 요청 파라미터 구성
                request_kwargs = {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "params": query_params,
                }

                # Body가 있는 경우
                if body_data is not None:
                    if isinstance(body_data, (dict, list)):
                        request_kwargs["json"] = body_data
                    else:
                        request_kwargs["content"] = str(body_data)

                # 요청 전송
                response = await client.request(**request_kwargs)

                # 응답 처리
                response_body = response.text
                response_headers = dict(response.headers)
                status_code = response.status_code
                is_success = 200 <= status_code < 300

                # 에러 응답인 경우 본문 내용도 로그에 기록
                if not is_success:
                    logger.error(
                        f"[HTTPNode] 응답 수신: {status_code} "
                        f"({len(response_body)}자, success={is_success})\n"
                        f"응답 본문: {response_body[:500]}"  # 처음 500자만
                    )
                else:
                    logger.info(
                        f"[HTTPNode] 응답 수신: {status_code} "
                        f"({len(response_body)}자, success={is_success})"
                    )

                return {
                    "status_code": status_code,
                    "body": response_body,
                    "headers": response_headers,
                    "success": is_success,
                    "error": "" if is_success else f"HTTP {status_code}",
                }

        except httpx.TimeoutException:
            error_msg = f"요청 타임아웃 ({timeout}초 초과)"
            logger.error(f"[HTTPNode] {error_msg}: {url}")
            return {
                "status_code": 0,
                "body": "",
                "headers": {},
                "success": False,
                "error": error_msg,
            }

        except httpx.RequestError as e:
            error_msg = f"요청 실패: {str(e)}"
            logger.error(f"[HTTPNode] {error_msg}")
            return {
                "status_code": 0,
                "body": "",
                "headers": {},
                "success": False,
                "error": error_msg,
            }

        except Exception as e:
            error_msg = f"예상치 못한 오류: {str(e)}"
            logger.error(f"[HTTPNode] {error_msg}", exc_info=True)
            return {
                "status_code": 0,
                "body": "",
                "headers": {},
                "success": False,
                "error": error_msg,
            }

    def validate(self) -> tuple[bool, Optional[str]]:
        """노드 설정 검증"""
        # URL은 config 또는 variable_mappings 중 하나에 있어야 함
        has_url_in_config = bool(self.config.get("url"))
        has_url_in_mappings = "url" in self.variable_mappings

        if not (has_url_in_config or has_url_in_mappings):
            return False, "URL은 config 또는 variable_mappings에 설정되어야 합니다"

        # URL이 config에 있는 경우 문자열인지 확인
        if has_url_in_config:
            url = self.config.get("url")
            if not isinstance(url, str):
                return False, "URL은 문자열이어야 합니다"

        return True, None
