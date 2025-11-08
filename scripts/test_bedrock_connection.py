#!/usr/bin/env python3
"""
AWS Bedrock 연결 테스트 스크립트

이 스크립트는 Bedrock Titan Embeddings API 연결을 검증합니다.

사용법:
    python scripts/test_bedrock_connection.py

요구사항:
    - .env.local 파일에 AWS credentials 설정
    - boto3 패키지 설치 (pip install boto3)
"""

import os
import sys
import json
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError

# 환경 변수 로드
load_dotenv(dotenv_path=".env.local")


def test_bedrock_connection():
    """Bedrock API 연결 테스트"""

    print("=" * 60)
    print("AWS Bedrock Titan Embeddings 연결 테스트")
    print("=" * 60)

    # AWS 설정 확인
    aws_region = os.getenv("AWS_REGION", "ap-northeast-2")
    aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

    print(f"\n[1/5] AWS 설정 확인")
    print(f"  Region: {aws_region}")
    print(f"  Access Key: {'설정됨' if aws_access_key else '❌ 미설정'}")
    print(f"  Secret Key: {'설정됨' if aws_secret_key else '❌ 미설정'}")

    if not aws_access_key or not aws_secret_key:
        print("\n❌ 오류: AWS credentials가 설정되지 않았습니다.")
        print("   .env.local 파일에 AWS_ACCESS_KEY_ID와 AWS_SECRET_ACCESS_KEY를 설정하세요.")
        return False

    # Bedrock 클라이언트 생성
    print(f"\n[2/5] Bedrock 클라이언트 생성 중...")
    try:
        client = boto3.client(
            service_name='bedrock-runtime',
            region_name=aws_region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key
        )
        print("  ✅ 클라이언트 생성 완료")
    except Exception as e:
        print(f"  ❌ 클라이언트 생성 실패: {str(e)}")
        return False

    # 모델 ID 및 설정
    model_id = "amazon.titan-embed-text-v2:0"
    test_text = "안녕하세요! AWS Bedrock 연결 테스트입니다."
    dimensions = 1024

    print(f"\n[3/5] 임베딩 API 호출 테스트")
    print(f"  Model ID: {model_id}")
    print(f"  Test Text: {test_text}")
    print(f"  Dimensions: {dimensions}")

    # Bedrock API 호출
    try:
        print("  API 호출 중...")
        request_body = {
            "inputText": test_text,
            "dimensions": dimensions,
            "normalize": True
        }

        response = client.invoke_model(
            modelId=model_id,
            body=json.dumps(request_body)
        )

        # 응답 파싱
        result = json.loads(response['body'].read())

        print("  ✅ API 호출 성공")

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']

        print(f"  ❌ API 호출 실패: {error_code}")
        print(f"  Error Message: {error_message}")

        # 자주 발생하는 에러 해결 방법 안내
        if error_code == 'AccessDeniedException':
            print("\n해결 방법:")
            print("  1. IAM 권한 확인: AmazonBedrockFullAccess 정책이 추가되었는지 확인")
            print("  2. AWS Console → IAM → Users → 사용자 → Permissions 확인")

        elif error_code == 'ResourceNotFoundException':
            print("\n해결 방법:")
            print("  1. Model Access 승인 확인")
            print("  2. AWS Console → Bedrock → Model access")
            print("  3. Titan Embeddings G1 - Text v2 모델 승인 상태 확인")

        elif error_code == 'ValidationException':
            print("\n해결 방법:")
            print("  1. Region 확인: Bedrock이 지원되는 리전인지 확인")
            print(f"     현재 리전: {aws_region}")
            print("     권장 리전: ap-northeast-2 (서울) 또는 us-east-1 (버지니아)")

        return False

    except Exception as e:
        print(f"  ❌ 알 수 없는 오류: {str(e)}")
        return False

    # 응답 검증
    print(f"\n[4/5] 응답 데이터 검증")

    if 'embedding' not in result:
        print("  ❌ 응답에 'embedding' 필드가 없습니다.")
        return False

    embedding = result['embedding']
    token_count = result.get('inputTextTokenCount', 'N/A')

    print(f"  ✅ Embedding 벡터 생성 성공")
    print(f"  Vector Length: {len(embedding)}")
    print(f"  Expected Dimensions: {dimensions}")
    print(f"  Input Token Count: {token_count}")
    print(f"  First 5 values: {embedding[:5]}")

    if len(embedding) != dimensions:
        print(f"  ⚠️ 경고: 벡터 차원이 예상과 다릅니다 ({len(embedding)} != {dimensions})")

    # 최종 결과
    print(f"\n[5/5] 종합 결과")
    print("  ✅ Bedrock Titan Embeddings 연결 성공!")
    print("  ✅ 임베딩 API 정상 작동")

    # 비용 정보
    print(f"\n💰 비용 예상")
    print(f"  입력 토큰 수: {token_count}")
    print(f"  1K 토큰 당 비용: $0.0001")
    print(f"  이 호출 비용: ~$0.000001 (약 0.001원)")

    print("\n" + "=" * 60)
    print("다음 단계: embeddings.py의 EmbeddingService를 사용하여 통합 테스트 진행")
    print("=" * 60)

    return True


def test_embedding_service():
    """EmbeddingService 클래스 통합 테스트"""

    print("\n" + "=" * 60)
    print("EmbeddingService 통합 테스트")
    print("=" * 60)

    try:
        from app.core.embeddings import get_embedding_service
        import asyncio

        print("\n[1/3] EmbeddingService 인스턴스 생성 중...")
        service = get_embedding_service()
        print("  ✅ 인스턴스 생성 완료")

        print("\n[2/3] 동기 메서드 테스트 (embed_query_sync)")
        test_query = "Bedrock 임베딩 테스트 쿼리"
        embedding = service.embed_query_sync(test_query)
        print(f"  ✅ 쿼리 임베딩 성공")
        print(f"  Vector Length: {len(embedding)}")
        print(f"  First 5 values: {embedding[:5]}")

        print("\n[3/3] 비동기 메서드 테스트 (embed_documents)")
        test_documents = [
            "첫 번째 문서 내용입니다.",
            "두 번째 문서 내용입니다.",
            "세 번째 문서 내용입니다."
        ]

        async def test_async():
            embeddings = await service.embed_documents(test_documents)
            return embeddings

        embeddings = asyncio.run(test_async())
        print(f"  ✅ 문서 임베딩 성공")
        print(f"  문서 개수: {len(embeddings)}")
        print(f"  각 벡터 차원: {len(embeddings[0])}")

        print("\n" + "=" * 60)
        print("✅ 모든 테스트 통과!")
        print("=" * 60)

        return True

    except ImportError as e:
        print(f"  ❌ 모듈 import 실패: {str(e)}")
        print("  app.core.embeddings 모듈을 찾을 수 없습니다.")
        return False

    except Exception as e:
        print(f"  ❌ 테스트 실패: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Bedrock API 직접 테스트
    success = test_bedrock_connection()

    if not success:
        print("\n⚠️ Bedrock API 연결 테스트 실패")
        print("   위의 해결 방법을 참고하여 설정을 확인하세요.")
        sys.exit(1)

    # EmbeddingService 통합 테스트
    print("\n")
    success = test_embedding_service()

    if not success:
        print("\n⚠️ EmbeddingService 통합 테스트 실패")
        sys.exit(1)

    print("\n🎉 모든 테스트가 성공적으로 완료되었습니다!")
    sys.exit(0)
