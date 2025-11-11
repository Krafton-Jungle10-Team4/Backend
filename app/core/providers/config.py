"""
LLM Provider 설정 스키마
"""
from typing import Optional
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """Provider 설정 베이스 클래스"""

    enabled: bool = Field(default=True, description="Provider 활성화 여부")


class OpenAIConfig(ProviderConfig):
    """OpenAI Provider 설정"""

    api_key: str = Field(..., description="OpenAI API Key")
    organization: Optional[str] = Field(
        default=None,
        description="OpenAI 조직 ID"
    )
    default_model: str = Field(
        default="gpt-4o-mini",
        description="기본 모델 ID"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="기본 시스템 프롬프트"
    )


class AnthropicConfig(ProviderConfig):
    """Anthropic Provider 설정"""

    api_key: str = Field(..., description="Anthropic API Key")
    default_model: str = Field(
        default="claude-3-sonnet-20240229",
        description="기본 모델 ID"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="기본 시스템 프롬프트"
    )


class LLMConfig(BaseModel):
    """LLM 통합 설정"""

    default_provider: str = Field(
        default="openai",
        description="기본 Provider"
    )
    openai: Optional[OpenAIConfig] = None
    anthropic: Optional[AnthropicConfig] = None

    def get_provider_config(self, provider: str) -> Optional[ProviderConfig]:
        """Provider 이름으로 설정 조회"""
        provider_key = (provider or "").lower()
        if provider_key == "openai":
            return self.openai
        if provider_key == "anthropic":
            return self.anthropic
        return None
