"""
감사 로깅 미들웨어

보안 이벤트 및 주요 API 호출 로깅 (구조화된 로깅)
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import time
import logging
import json
import uuid

logger = logging.getLogger(__name__)


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    감사 로깅 미들웨어

    - 모든 API 요청/응답 로깅
    - 응답 시간 측정
    - 보안 이벤트 감지
    """

    async def dispatch(self, request: Request, call_next):
        # 요청마다 고유 ID 생성 (요청-응답 페어링용)
        request_id = str(uuid.uuid4())[:8]

        # 요청 시작 시간
        start_time = time.time()

        # 요청 정보 추출
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path
        user_agent = request.headers.get("user-agent", "unknown")

        # 경로 유형 확인
        is_health_check = self._is_health_check(path)
        is_sensitive = self._is_sensitive_path(path)

        # 디버그: cost 관련 요청은 항상 상세 로깅
        if "/cost" in path or "/api/v1/cost" in path:
            logger.info(
                f"[DEBUG] Cost API 요청: method={method}, path={path}, "
                f"client_ip={client_ip}, request_id={request_id}"
            )

        # 요청 시작 로깅 (헬스체크는 간소화)
        self._log_request_start(
            request_id=request_id,
            method=method,
            path=path,
            client_ip=client_ip,
            user_agent=user_agent,
            is_compact=is_health_check
        )

        # 요청 처리
        try:
            response: Response = await call_next(request)
        except Exception as e:
            # 에러 로깅 (구조화된 포맷)
            self._log_request_error(
                request_id=request_id,
                method=method,
                path=path,
                client_ip=client_ip,
                error=str(e)
            )
            raise

        # 응답 시간 계산
        process_time = time.time() - start_time

        # 응답 종료 로깅 (헬스체크는 간소화)
        status_code = response.status_code
        
        # 디버그: cost 관련 요청 및 404 에러는 항상 상세 로깅
        if "/cost" in path or "/api/v1/cost" in path or status_code == 404:
            logger.warning(
                f"[DEBUG] Cost API 응답 또는 404: method={method}, path={path}, "
                f"status_code={status_code}, process_time={process_time:.3f}s, "
                f"request_id={request_id}"
            )
        
        self._log_request_end(
            request_id=request_id,
            method=method,
            path=path,
            client_ip=client_ip,
            status_code=status_code,
            process_time=process_time,
            is_compact=is_health_check
        )

        # 보안 이벤트 로깅
        if is_sensitive or status_code >= 400:
            await self._log_security_event(
                request, response, process_time, client_ip, request_id
            )

        # 응답 헤더에 처리 시간 및 Request ID 추가
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Request-ID"] = request_id

        return response

    def _is_health_check(self, path: str) -> bool:
        """헬스체크 및 모니터링 경로 확인 (간소 로깅 대상)"""
        health_check_paths = [
            "/health",
            "/api/v1/health",
            "/metrics",
            "/ping",
            "/readiness",
            "/liveness",
        ]
        return path in health_check_paths

    def _is_sensitive_path(self, path: str) -> bool:
        """민감한 경로 확인"""
        sensitive_paths = [
            "/api/v1/auth/",
            "/api/v1/widget/sessions",
            "/api/v1/bots/",
        ]
        return any(path.startswith(p) for p in sensitive_paths)

    def _get_log_level(self, status_code: int) -> int:
        """상태 코드에 따른 로그 레벨 반환"""
        if status_code >= 500:
            return logging.ERROR
        elif status_code >= 400:
            return logging.WARNING
        else:
            return logging.INFO

    def _log_request_start(
        self,
        request_id: str,
        method: str,
        path: str,
        client_ip: str,
        user_agent: str,
        is_compact: bool = False
    ):
        """요청 시작 로깅"""
        extra = {
            'log_type': 'request_start_compact' if is_compact else 'request_start',
            'request_id': request_id,
            'method': method,
            'path': path,
            'client_ip': client_ip,
            'user_agent': user_agent
        }
        logger.info(f"Request started", extra=extra)

    def _log_request_end(
        self,
        request_id: str,
        method: str,
        path: str,
        client_ip: str,
        status_code: int,
        process_time: float,
        is_compact: bool = False
    ):
        """요청 종료 로깅"""
        log_level = self._get_log_level(status_code)
        extra = {
            'log_type': 'request_end_compact' if is_compact else 'request_end',
            'request_id': request_id,
            'method': method,
            'path': path,
            'client_ip': client_ip,
            'status_code': status_code,
            'process_time': process_time
        }
        logger.log(log_level, f"Request completed", extra=extra)

    def _log_request_error(
        self,
        request_id: str,
        method: str,
        path: str,
        client_ip: str,
        error: str
    ):
        """요청 에러 로깅"""
        logger.error(
            f"\n{'='*80}\n"
            f"❌ REQUEST ERROR\n"
            f"{'='*80}\n"
            f"Request ID : {request_id}\n"
            f"Method     : {method}\n"
            f"Path       : {path}\n"
            f"Client IP  : {client_ip}\n"
            f"Error      : {error}\n"
            f"{'='*80}\n"
        )

    async def _log_security_event(
        self,
        request: Request,
        response: Response,
        process_time: float,
        client_ip: str,
        request_id: str
    ):
        """보안 이벤트 상세 로깅"""
        event = {
            "request_id": request_id,
            "timestamp": time.time(),
            "client_ip": client_ip,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "process_time": process_time,
            "user_agent": request.headers.get("user-agent", "unknown"),
            "referer": request.headers.get("referer", ""),
            "origin": request.headers.get("origin", ""),
        }

        # 인증 헤더 확인 (값은 로깅하지 않음)
        if "authorization" in request.headers:
            event["has_auth"] = True
        if "x-api-key" in request.headers:
            event["has_api_key"] = True

        extra = {'log_type': 'security_event'}
        logger.warning(
            f"Security event: {json.dumps(event, ensure_ascii=False)}",
            extra=extra
        )


# 보안 이벤트 전용 로거
security_logger = logging.getLogger("security")


def log_security_event(
    event_type: str,
    user_id: str = None,
    details: dict = None
):
    """
    보안 이벤트 로깅 헬퍼 함수

    사용 예시:
        log_security_event(
            "api_key_created",
            user_id="user_123",
            details={"key_id": "key_789"}
        )
    """
    event = {
        "timestamp": time.time(),
        "event_type": event_type,
        "user_id": user_id,
        "details": details or {}
    }
    security_logger.info(json.dumps(event, ensure_ascii=False))
