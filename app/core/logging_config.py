"""
구조화된 로깅 설정

가독성 향상을 위한 커스텀 로깅 포매터
"""
import logging
import sys
from typing import Optional


class ColoredFormatter(logging.Formatter):
    """
    색상이 적용된 로그 포매터 (터미널 출력용)
    """

    # ANSI 색상 코드
    COLORS = {
        'DEBUG': '\033[36m',      # 청록색
        'INFO': '\033[32m',       # 녹색
        'WARNING': '\033[33m',    # 노란색
        'ERROR': '\033[31m',      # 빨간색
        'CRITICAL': '\033[35m',   # 자홍색
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'

    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()

    def format(self, record: logging.LogRecord) -> str:
        if not self.use_colors:
            return self._format_plain(record)

        color = self.COLORS.get(record.levelname, self.RESET)

        # 로그 레벨에 색상 적용
        levelname = f"{color}{self.BOLD}{record.levelname:8s}{self.RESET}"

        # 타임스탬프
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")

        # 메시지
        message = record.getMessage()

        # 로거 이름 (간략화)
        logger_name = record.name.replace('app.', '')

        return f"{timestamp} | {levelname} | {logger_name:30s} | {message}"

    def _format_plain(self, record: logging.LogRecord) -> str:
        """색상 없는 포맷"""
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        levelname = f"{record.levelname:8s}"
        logger_name = record.name.replace('app.', '')
        message = record.getMessage()

        return f"{timestamp} | {levelname} | {logger_name:30s} | {message}"


class StructuredFormatter(logging.Formatter):
    """
    구조화된 멀티라인 로그 포매터

    박스형 구분선으로 로그를 그룹화하여 가독성 향상
    """

    # 박스 문자
    BOX_TOP = "╔" + "═" * 80 + "╗"
    BOX_BOTTOM = "╚" + "═" * 80 + "╝"
    BOX_MID = "╠" + "═" * 80 + "╣"
    BOX_SIDE = "║"

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S.%f")[:-3]
        message = record.getMessage()

        # 특수 로그 타입 확인
        if hasattr(record, 'log_type'):
            if record.log_type == 'request_start':
                return self._format_request_start(timestamp, message, record)
            elif record.log_type == 'request_end':
                return self._format_request_end(timestamp, message, record)
            elif record.log_type == 'request_start_compact':
                return self._format_request_compact(timestamp, message, record, is_start=True)
            elif record.log_type == 'request_end_compact':
                return self._format_request_compact(timestamp, message, record, is_start=False)
            elif record.log_type == 'security_event':
                return self._format_security_event(timestamp, message, record)

        # 일반 로그
        return self._format_standard(timestamp, record.levelname, message, record.name)

    def _format_request_start(self, timestamp: str, message: str, record: logging.LogRecord) -> str:
        """요청 시작 로그"""
        request_id = getattr(record, 'request_id', 'N/A')
        method = getattr(record, 'method', 'N/A')
        path = getattr(record, 'path', 'N/A')
        client_ip = getattr(record, 'client_ip', 'N/A')
        user_agent = getattr(record, 'user_agent', 'N/A')

        lines = [
            "",
            self.BOX_TOP,
            f"{self.BOX_SIDE} 📨 REQUEST START",
            self.BOX_MID,
            f"{self.BOX_SIDE} Request ID : {request_id}",
            f"{self.BOX_SIDE} Timestamp  : {timestamp}",
            f"{self.BOX_SIDE} Method     : {method}",
            f"{self.BOX_SIDE} Path       : {path}",
            f"{self.BOX_SIDE} Client IP  : {client_ip}",
            f"{self.BOX_SIDE} User Agent : {user_agent[:70]}",
            self.BOX_BOTTOM,
        ]
        return "\n".join(lines)

    def _format_request_end(self, timestamp: str, message: str, record: logging.LogRecord) -> str:
        """요청 종료 로그"""
        request_id = getattr(record, 'request_id', 'N/A')
        method = getattr(record, 'method', 'N/A')
        path = getattr(record, 'path', 'N/A')
        status_code = getattr(record, 'status_code', 'N/A')
        process_time = getattr(record, 'process_time', 0.0)

        # 상태 코드에 따른 이모지
        if status_code < 300:
            emoji = "✅"
            status_label = "SUCCESS"
        elif status_code < 400:
            emoji = "↪️"
            status_label = "REDIRECT"
        elif status_code < 500:
            emoji = "⚠️"
            status_label = "CLIENT ERROR"
        else:
            emoji = "❌"
            status_label = "SERVER ERROR"

        lines = [
            "",
            self.BOX_TOP,
            f"{self.BOX_SIDE} {emoji} RESPONSE COMPLETED - {status_label}",
            self.BOX_MID,
            f"{self.BOX_SIDE} Request ID   : {request_id}",
            f"{self.BOX_SIDE} Timestamp    : {timestamp}",
            f"{self.BOX_SIDE} Method       : {method}",
            f"{self.BOX_SIDE} Path         : {path}",
            f"{self.BOX_SIDE} Status Code  : {status_code}",
            f"{self.BOX_SIDE} Process Time : {process_time:.3f}s",
            self.BOX_BOTTOM,
            "",
        ]
        return "\n".join(lines)

    def _format_request_compact(self, timestamp: str, message: str, record: logging.LogRecord, is_start: bool) -> str:
        """간소화된 요청/응답 로그 (헬스체크 등)"""
        request_id = getattr(record, 'request_id', 'N/A')
        method = getattr(record, 'method', 'N/A')
        path = getattr(record, 'path', 'N/A')

        if is_start:
            # 요청 시작: 한 줄로 간단히
            return f"{timestamp} | 📨 REQ  | [{request_id}] {method:4s} {path}"
        else:
            # 요청 종료: 상태 코드와 처리 시간 포함
            status_code = getattr(record, 'status_code', 'N/A')
            process_time = getattr(record, 'process_time', 0.0)

            # 상태 코드에 따른 이모지
            if status_code < 300:
                emoji = "✅"
            elif status_code < 400:
                emoji = "↪️"
            elif status_code < 500:
                emoji = "⚠️"
            else:
                emoji = "❌"

            return f"{timestamp} | {emoji} RES  | [{request_id}] {method:4s} {path} → {status_code} ({process_time:.3f}s)"

    def _format_security_event(self, timestamp: str, message: str, record: logging.LogRecord) -> str:
        """보안 이벤트 로그"""
        lines = [
            "",
            "╔" + "═" * 80 + "╗",
            f"║ 🔐 SECURITY EVENT",
            "╠" + "═" * 80 + "╣",
            f"║ Timestamp : {timestamp}",
            f"║ Message   : {message}",
            "╚" + "═" * 80 + "╝",
            "",
        ]
        return "\n".join(lines)

    def _format_standard(self, timestamp: str, level: str, message: str, logger_name: str) -> str:
        """표준 로그"""
        logger_name = logger_name.replace('app.', '')

        # 레벨별 이모지
        level_emoji = {
            'DEBUG': '🔍',
            'INFO': 'ℹ️',
            'WARNING': '⚠️',
            'ERROR': '❌',
            'CRITICAL': '🚨',
        }
        emoji = level_emoji.get(level, '📝')

        return f"{timestamp} | {emoji} {level:8s} | {logger_name:30s} | {message}"


def setup_logging(log_level: str = "INFO", use_structured: bool = True):
    """
    로깅 설정 초기화

    Args:
        log_level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        use_structured: 구조화된 포매터 사용 여부
    """
    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # 기존 핸들러 제거
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 콘솔 핸들러 생성
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper()))

    # 포매터 선택
    if use_structured:
        formatter = StructuredFormatter()
    else:
        formatter = ColoredFormatter(use_colors=True)

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # uvicorn 로거 레벨 조정 (너무 자세한 로그 방지)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    # 외부 라이브러리 로거 레벨 조정 (과도한 DEBUG 로그 방지)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("s3transfer").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)  # 자동 리로드 관련 로그


def get_logger(name: str) -> logging.Logger:
    """
    로거 인스턴스 가져오기

    Args:
        name: 로거 이름 (보통 __name__ 사용)

    Returns:
        Logger 인스턴스
    """
    return logging.getLogger(name)
