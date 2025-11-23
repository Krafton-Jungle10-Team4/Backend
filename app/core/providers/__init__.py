"""
LLM Provider 구현체 모듈

모듈 import 시 register_provider 데코레이터가 실행되어
LLMProviderRegistry에 자동 등록됩니다.
"""

from app.core.providers import openai as _openai  # noqa: F401
from app.core.providers import anthropic as _anthropic  # noqa: F401
from app.core.providers import bedrock as _bedrock  # noqa: F401

# Google provider는 optional (google-generativeai 패키지가 없을 수 있음)
try:
    from app.core.providers import google as _google  # noqa: F401
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning("Google provider를 로드할 수 없습니다. google-generativeai 패키지가 설치되지 않았을 수 있습니다.")
    _google = None

__all__ = ["_openai", "_anthropic", "_google", "_bedrock"]
