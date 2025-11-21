"""
테스트 사용자, Bot, Workflow, API Key 생성 스크립트
"""
import asyncio
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import os
import sys
import hashlib

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.models.user import User, AuthType
from app.models.bot import Bot
from app.models.workflow_version import BotWorkflowVersion
from app.models.bot_api_key import BotAPIKey
from app.config import settings


async def create_test_setup():
    """테스트용 사용자, Bot, Workflow, API Key 생성"""
    
    # 데이터베이스 연결
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        # 1. 테스트 사용자 생성 또는 조회
        result = await db.execute(
            select(User).where(User.email == "test@example.com")
        )
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(
                email="test@example.com",
                name="Test User",
                password_hash="test_hash",  # 실제로는 bcrypt 해시 사용
                auth_type=AuthType.LOCAL
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print(f"✅ 테스트 사용자 생성: {user.email} (ID: {user.id})")
        else:
            print(f"ℹ️ 기존 테스트 사용자 사용: {user.email} (ID: {user.id})")
        
        # 2. 테스트 Bot 생성
        bot_id = f"test_bot_{uuid.uuid4().hex[:8]}"
        test_bot = Bot(
            bot_id=bot_id,
            name="Token Test Bot",
            user_id=user.id,
            use_workflow_v2=True,
            status="active"
        )
        db.add(test_bot)
        await db.commit()
        await db.refresh(test_bot)
        print(f"✅ 테스트 Bot 생성: {test_bot.name} (ID: {test_bot.bot_id})")
        
        # 3. 간단한 LLM Workflow 생성
        workflow_version = BotWorkflowVersion(
            id=uuid.uuid4(),
            bot_id=test_bot.bot_id,
            version="v1",
            status="published",
            graph={
                "nodes": [
                    {
                        "id": "start",
                        "type": "start",
                        "data": {"title": "Start"}
                    },
                    {
                        "id": "llm_1",
                        "type": "llm",
                        "data": {
                            "title": "LLM",
                            "model": "claude-sonnet-4-5-20250929",
                            "system_prompt": "You are a helpful assistant.",
                            "temperature": 0.7,
                            "variable_mappings": {
                                "query": {
                                    "source": "static",
                                    "value": "Say hello and tell me you are ready to help. Be brief."
                                }
                            }
                        }
                    },
                    {
                        "id": "end",
                        "type": "end",
                        "data": {"title": "End"}
                    }
                ],
                "edges": [
                    {"source": "start", "target": "llm_1"},
                    {"source": "llm_1", "target": "end"}
                ]
            },
            input_schema=[
                {
                    "key": "message",
                    "type": "string",
                    "required": False,
                    "is_primary": True,
                    "description": "사용자 메시지"
                }
            ],
            output_schema=[],
            published_at=datetime.now(timezone.utc)
        )
        db.add(workflow_version)
        await db.commit()
        await db.refresh(workflow_version)
        print(f"✅ Workflow 버전 생성: {workflow_version.version} (ID: {workflow_version.id})")
        
        # 4. API Key 생성 (sk-proj- 접두사 사용)
        api_key_value = f"sk-proj-{uuid.uuid4().hex[:24]}"
        key_hash = hashlib.sha256(api_key_value.encode()).hexdigest()
        
        api_key = BotAPIKey(
            id=uuid.uuid4(),
            bot_id=test_bot.bot_id,
            user_id=user.id,
            key_hash=key_hash,
            key_prefix=api_key_value[:12],
            key_suffix=api_key_value[-4:],
            name="Test API Key",
            workflow_version_id=workflow_version.id,
            bind_to_latest_published=False,
            rate_limit_per_minute=60,
            rate_limit_per_hour=1000,
            rate_limit_per_day=10000,
            is_active=True
        )
        db.add(api_key)
        await db.commit()
        await db.refresh(api_key)
        print(f"✅ API Key 생성: {api_key.name}")
        
        # 결과 출력
        print("\n" + "="*70)
        print("🎉 테스트 환경 생성 완료!")
        print("="*70)
        print(f"\n📋 테스트 정보:")
        print(f"  - User ID: {user.id}")
        print(f"  - Bot ID: {test_bot.bot_id}")
        print(f"  - Workflow Version ID: {workflow_version.id}")
        print(f"  - API Key: {api_key_value}")
        print(f"\n🧪 테스트 명령어:")
        print(f'\ncurl -X POST http://localhost:8001/api/v1/public/workflows/run \\')
        print(f'  -H "X-API-Key: {api_key_value}" \\')
        print(f'  -H "Content-Type: application/json" \\')
        print(f'  -d \'{{"inputs": {{"user_query": "Hello, how are you?"}}}}\' | jq')
        print(f'\n💾 API Key를 저장해두세요: {api_key_value}\n')
        
        return {
            "user_id": user.id,
            "bot_id": test_bot.bot_id,
            "workflow_version_id": str(workflow_version.id),
            "api_key": api_key_value
        }


if __name__ == "__main__":
    result = asyncio.run(create_test_setup())

