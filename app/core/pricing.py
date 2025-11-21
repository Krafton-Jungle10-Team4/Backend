"""
LLM Model Pricing Information
2025년 10월 기준 모델별 토큰 가격 정보
"""

from typing import Dict, Optional
from decimal import Decimal

# 2025년 10월 기준 모델별 가격 (USD per 1M tokens)
MODEL_PRICING = {
    # OpenAI GPT-4 Series
    "gpt-4": {
        "input": Decimal("30.00"),   # $30 per 1M input tokens
        "output": Decimal("60.00"),  # $60 per 1M output tokens
    },
    "gpt-4-turbo": {
        "input": Decimal("10.00"),
        "output": Decimal("30.00"),
    },
    "gpt-4-turbo-preview": {
        "input": Decimal("10.00"),
        "output": Decimal("30.00"),
    },
    "gpt-4o": {
        "input": Decimal("5.00"),
        "output": Decimal("15.00"),
    },
    "gpt-4o-mini": {
        "input": Decimal("0.15"),
        "output": Decimal("0.60"),
    },
    
    # OpenAI GPT-3.5 Series
    "gpt-3.5-turbo": {
        "input": Decimal("0.50"),
        "output": Decimal("1.50"),
    },
    "gpt-3.5-turbo-16k": {
        "input": Decimal("3.00"),
        "output": Decimal("4.00"),
    },
    
    # Anthropic Claude Series
    "claude-3-opus-20240229": {
        "input": Decimal("15.00"),
        "output": Decimal("75.00"),
    },
    "claude-3-sonnet-20240229": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    "claude-3-haiku-20240307": {
        "input": Decimal("0.25"),
        "output": Decimal("1.25"),
    },
    "claude-3-5-sonnet-20241022": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    
    # Google Gemini Series
    "gemini-pro": {
        "input": Decimal("0.50"),
        "output": Decimal("1.50"),
    },
    "gemini-1.5-pro": {
        "input": Decimal("3.50"),
        "output": Decimal("10.50"),
    },
    "gemini-1.5-flash": {
        "input": Decimal("0.075"),
        "output": Decimal("0.30"),
    },
    
    # OpenAI O1 Series
    "o1-preview": {
        "input": Decimal("15.00"),
        "output": Decimal("60.00"),
    },
    "o1-mini": {
        "input": Decimal("3.00"),
        "output": Decimal("12.00"),
    },
}


def normalize_model_name(model: str) -> str:
    """
    모델 이름 정규화
    
    예: "gpt-4-0613", "gpt-4-1106-preview" -> "gpt-4"
         "gpt-4-turbo-2024-04-09" -> "gpt-4-turbo"
    """
    model_lower = model.lower()
    
    # 정확한 매칭 우선
    if model_lower in MODEL_PRICING:
        return model_lower
    
    # OpenAI 모델 정규화
    if "gpt-5" in model_lower:  # gpt-5는 gpt-4o의 별칭
        return "gpt-4o"
    if "gpt-4o-mini" in model_lower:
        return "gpt-4o-mini"
    if "gpt-4o" in model_lower:
        return "gpt-4o"
    if "gpt-4-turbo" in model_lower:
        return "gpt-4-turbo"
    if "gpt-4" in model_lower:
        return "gpt-4"
    if "gpt-3.5-turbo-16k" in model_lower:
        return "gpt-3.5-turbo-16k"
    if "gpt-3.5-turbo" in model_lower or "gpt-35-turbo" in model_lower:
        return "gpt-3.5-turbo"
    
    # Anthropic 모델 정규화
    if "claude-3-5-sonnet" in model_lower or "claude-3.5-sonnet" in model_lower:
        return "claude-3-5-sonnet-20241022"
    if "claude-3-opus" in model_lower:
        return "claude-3-opus-20240229"
    if "claude-3-sonnet" in model_lower:
        return "claude-3-sonnet-20240229"
    if "claude-3-haiku" in model_lower:
        return "claude-3-haiku-20240307"
    
    # Google 모델 정규화
    if "gemini-1.5-pro" in model_lower:
        return "gemini-1.5-pro"
    if "gemini-1.5-flash" in model_lower:
        return "gemini-1.5-flash"
    if "gemini-pro" in model_lower:
        return "gemini-pro"
    
    # OpenAI O1 모델 정규화
    if "o1-preview" in model_lower:
        return "o1-preview"
    if "o1-mini" in model_lower:
        return "o1-mini"
    
    # 기본값: 원래 모델명 반환
    return model_lower


def calculate_token_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int
) -> Optional[Decimal]:
    """
    토큰 사용량 기반 비용 계산
    
    Args:
        model: 모델명
        prompt_tokens: 입력 토큰 수
        completion_tokens: 출력 토큰 수
    
    Returns:
        Decimal: USD 단위 비용 (예: 0.00123)
        None: 모델 가격 정보가 없는 경우
    """
    normalized_model = normalize_model_name(model)
    
    if normalized_model not in MODEL_PRICING:
        return None
    
    pricing = MODEL_PRICING[normalized_model]
    
    # 1M 토큰당 가격이므로 1,000,000으로 나눔
    input_cost = (Decimal(prompt_tokens) / Decimal(1_000_000)) * pricing["input"]
    output_cost = (Decimal(completion_tokens) / Decimal(1_000_000)) * pricing["output"]
    
    total_cost = input_cost + output_cost
    
    # 소수점 8자리까지 반올림 (USD)
    return total_cost.quantize(Decimal("0.00000001"))


def get_model_pricing_info(model: str) -> Optional[Dict[str, Decimal]]:
    """
    모델의 가격 정보 조회
    
    Returns:
        {"input": Decimal, "output": Decimal} 또는 None
    """
    normalized_model = normalize_model_name(model)
    return MODEL_PRICING.get(normalized_model)

