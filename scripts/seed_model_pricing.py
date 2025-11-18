"""
모델 가격 정보 초기 데이터 추가 스크립트
AWS Bedrock 및 기타 LLM Provider 모델 가격 설정
"""
import asyncio
import sys
from pathlib import Path

# Backend 디렉토리를 Python 경로에 추가
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.models.llm_usage import ModelPricing


async def seed_pricing_data():
    """
    모델 가격 정보 초기화

    주의: 가격은 2024년 기준이며, 실제 AWS Bedrock 공식 문서에서 확인 필요
    https://aws.amazon.com/bedrock/pricing/
    """
    # 데이터베이스 연결
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True
    )
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        # AWS Bedrock - Claude 모델 가격 (2024년 기준 예시)
        bedrock_models = [
            {
                "provider": "bedrock",
                "model_name": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "input_price_per_1k": 0.003,  # $3 per MTok
                "output_price_per_1k": 0.015,  # $15 per MTok
                "cache_write_price_per_1k": 0.00375,  # $3.75 per MTok
                "cache_read_price_per_1k": 0.0003,  # $0.30 per MTok
                "region": "us-east-1"
            },
            {
                "provider": "bedrock",
                "model_name": "anthropic.claude-3-5-sonnet-20240620-v1:0",
                "input_price_per_1k": 0.003,
                "output_price_per_1k": 0.015,
                "cache_write_price_per_1k": 0.00375,
                "cache_read_price_per_1k": 0.0003,
                "region": "us-east-1"
            },
            {
                "provider": "bedrock",
                "model_name": "anthropic.claude-3-opus-20240229-v1:0",
                "input_price_per_1k": 0.015,  # $15 per MTok
                "output_price_per_1k": 0.075,  # $75 per MTok
                "region": "us-east-1"
            },
            {
                "provider": "bedrock",
                "model_name": "anthropic.claude-3-sonnet-20240229-v1:0",
                "input_price_per_1k": 0.003,
                "output_price_per_1k": 0.015,
                "region": "us-east-1"
            },
            {
                "provider": "bedrock",
                "model_name": "anthropic.claude-3-haiku-20240307-v1:0",
                "input_price_per_1k": 0.00025,  # $0.25 per MTok
                "output_price_per_1k": 0.00125,  # $1.25 per MTok
                "region": "us-east-1"
            },
            {
                "provider": "bedrock",
                "model_name": "anthropic.claude-3-5-haiku-20241022-v1:0",
                "input_price_per_1k": 0.001,  # $1 per MTok
                "output_price_per_1k": 0.005,  # $5 per MTok
                "region": "us-east-1"
            },
        ]

        # OpenAI 모델 가격 (참고용)
        openai_models = [
            {
                "provider": "openai",
                "model_name": "gpt-4",
                "input_price_per_1k": 0.03,
                "output_price_per_1k": 0.06,
                "region": None
            },
            {
                "provider": "openai",
                "model_name": "gpt-4-turbo",
                "input_price_per_1k": 0.01,
                "output_price_per_1k": 0.03,
                "region": None
            },
            {
                "provider": "openai",
                "model_name": "gpt-3.5-turbo",
                "input_price_per_1k": 0.0005,
                "output_price_per_1k": 0.0015,
                "region": None
            },
            {
                "provider": "openai",
                "model_name": "gpt-5-chat-latest",  # 실제 사용 중인 모델
                "input_price_per_1k": 0.03,  # GPT-5 가격 (추정, GPT-4와 유사하게 설정)
                "output_price_per_1k": 0.06,
                "region": None
            },
        ]

        # Anthropic Direct 모델 가격 (참고용)
        anthropic_models = [
            {
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "input_price_per_1k": 0.003,
                "output_price_per_1k": 0.015,
                "cache_write_price_per_1k": 0.00375,
                "cache_read_price_per_1k": 0.0003,
                "region": None
            },
            {
                "provider": "anthropic",
                "model_name": "claude-sonnet-4-5-20250929",  # 실제 사용 중인 모델
                "input_price_per_1k": 0.003,  # Claude Sonnet 4.5 가격 (추정)
                "output_price_per_1k": 0.015,
                "cache_write_price_per_1k": 0.00375,
                "cache_read_price_per_1k": 0.0003,
                "region": None
            },
            {
                "provider": "anthropic",
                "model_name": "claude-3-opus-20240229",
                "input_price_per_1k": 0.015,
                "output_price_per_1k": 0.075,
                "region": None
            },
        ]

        all_models = bedrock_models + openai_models + anthropic_models

        for model_data in all_models:
            # 기존에 있는지 확인 (중복 방지)
            from sqlalchemy import select
            existing = await session.execute(
                select(ModelPricing).where(
                    ModelPricing.provider == model_data['provider'],
                    ModelPricing.model_name == model_data['model_name']
                )
            )
            if existing.scalar_one_or_none():
                print(f"⏭️  이미 존재: {model_data['provider']}/{model_data['model_name']}")
                continue
            
            pricing = ModelPricing(**model_data)
            session.add(pricing)
            print(f"✅ 추가: {model_data['provider']}/{model_data['model_name']}")

        await session.commit()
        print(f"\n총 {len(all_models)}개 모델 가격 정보 추가 완료")

    await engine.dispose()


if __name__ == "__main__":
    print("모델 가격 정보 초기화 시작...")
    print("주의: 가격은 2024년 기준이며, 실제 AWS/Provider 공식 문서 확인 필요\n")
    asyncio.run(seed_pricing_data())
    print("\n✅ 완료!")
