"""
Widget Key 보안 및 도메인 검증
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import json
from urllib.parse import urlparse

from app.config import settings


class WidgetSecurity:
    """Widget Key 보안 및 도메인 검증"""

    def __init__(self):
        # Widget 전용 시크릿 키 (환경변수에서 로드)
        self.secret_key = settings.jwt_secret_key.encode()

    def generate_widget_key(self) -> str:
        """
        보안 Widget Key 생성

        형식: wk_{32바이트 URL-safe 랜덤}
        """
        return f"wk_{secrets.token_urlsafe(32)}"

    def sign_config(self, config: Dict, widget_key: str, ttl: int = 300) -> Dict:
        """
        Widget 설정에 HMAC-SHA256 서명 추가

        Args:
            config: Widget 설정 딕셔너리
            widget_key: Widget Key
            ttl: 서명 유효 시간 (초, 기본 5분)

        Returns:
            서명된 설정 딕셔너리 (signature, expires_at, nonce 포함)
        """
        expires_at = datetime.utcnow() + timedelta(seconds=ttl)
        nonce = secrets.token_urlsafe(16)

        payload = {
            "config": config,
            "widget_key": widget_key,
            "expires_at": expires_at.isoformat(),
            "nonce": nonce
        }

        # HMAC-SHA256 서명 생성
        message = json.dumps(payload, sort_keys=True).encode()
        signature = hmac.new(
            self.secret_key,
            message,
            hashlib.sha256
        ).hexdigest()

        return {
            "config": config,
            "signature": signature,
            "expires_at": expires_at.isoformat(),
            "nonce": nonce
        }

    def verify_signature(self, payload: Dict) -> bool:
        """
        서명 검증

        Args:
            payload: 서명된 설정 딕셔너리

        Returns:
            서명 유효 여부
        """
        if "signature" not in payload:
            return False

        # 만료 시간 확인
        try:
            expires_at = datetime.fromisoformat(payload["expires_at"])
            if datetime.utcnow() > expires_at:
                return False
        except (ValueError, KeyError):
            return False

        # 서명 검증
        original_signature = payload.pop("signature")
        message = json.dumps(payload, sort_keys=True).encode()
        expected_signature = hmac.new(
            self.secret_key,
            message,
            hashlib.sha256
        ).hexdigest()

        # Timing attack 방지를 위한 constant-time 비교
        return hmac.compare_digest(original_signature, expected_signature)

    def verify_domain(self, origin: str, allowed_domains: Optional[List[str]]) -> bool:
        """
        도메인 검증 (와일드카드 지원)

        Args:
            origin: 요청 출처 (예: https://example.com)
            allowed_domains: 허용된 도메인 리스트 (예: ["example.com", "*.example.com"])

        Returns:
            도메인 허용 여부
        """
        # 도메인 제한 없음
        if not allowed_domains or len(allowed_domains) == 0:
            return True

        # Origin 파싱
        try:
            parsed = urlparse(origin)
            hostname = parsed.hostname or ""
        except Exception:
            return False

        # 도메인 매칭
        for allowed in allowed_domains:
            if allowed.startswith("*"):
                # 와일드카드 도메인 (*.example.com)
                suffix = allowed[1:]  # .example.com
                if hostname.endswith(suffix):
                    return True
            elif hostname == allowed:
                # 정확한 도메인 매칭
                return True

        return False

    def hash_token(self, token: str) -> str:
        """
        토큰 해싱 (SHA-256)

        Args:
            token: 원본 토큰

        Returns:
            해시된 토큰
        """
        return hashlib.sha256(token.encode()).hexdigest()

    def generate_fingerprint_hash(self, fingerprint: Dict) -> str:
        """
        브라우저 지문 해시 생성

        Args:
            fingerprint: 브라우저 지문 딕셔너리

        Returns:
            지문 해시
        """
        fingerprint_str = json.dumps(fingerprint, sort_keys=True)
        return hashlib.sha256(fingerprint_str.encode()).hexdigest()


# 싱글톤 인스턴스
widget_security = WidgetSecurity()
