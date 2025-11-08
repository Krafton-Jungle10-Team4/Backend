"""
LLM Facade Layer with Intelligent Model Routing

비용 최적화를 위한 Bedrock 모델 자동 라우팅 시스템
- 쿼리 복잡도 기반 모델 선택 (Haiku vs Sonnet)
- CloudWatch 메트릭 전송으로 비용 추적
- 자동 폴백 메커니즘
"""

import boto3
import time
import json
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import datetime


class BedrockModel(Enum):
    """사용 가능한 Bedrock 모델"""
    HAIKU = "anthropic.claude-3-haiku-20240307-v1:0"
    HAIKU_35 = "anthropic.claude-3-5-haiku-20241022-v1:0"  # 주력 모델
    SONNET_35 = "anthropic.claude-3-5-sonnet-20241022-v2:0"  # 복잡한 쿼리용


@dataclass
class ModelPricing:
    """모델별 토큰 가격 (USD per 1K tokens)"""
    input_per_1k: float
    output_per_1k: float


# 2025년 Bedrock 가격표
PRICING = {
    BedrockModel.HAIKU: ModelPricing(0.00025, 0.00125),
    BedrockModel.HAIKU_35: ModelPricing(0.0008, 0.004),
    BedrockModel.SONNET_35: ModelPricing(0.003, 0.015),
}


class QueryComplexityAnalyzer:
    """쿼리 복잡도 분석 및 적절한 모델 선택"""

    @staticmethod
    def calculate_complexity(
        query: str,
        context_chunks: List[str],
        user_tier: str = "free",
        conversation_history: Optional[List[Dict]] = None
    ) -> float:
        """
        쿼리 복잡도 점수 계산 (0.0 - 1.0)

        Args:
            query: 사용자 질문
            context_chunks: RAG 검색된 컨텍스트 청크들
            user_tier: 사용자 등급 (free/premium)
            conversation_history: 대화 히스토리 (선택)

        Returns:
            0.0-0.3: 단순 (Haiku 3.5)
            0.3-0.7: 보통 (Haiku 3.5)
            0.7-1.0: 복잡 (Sonnet 3.5)
        """
        score = 0.0

        # Factor 1: 쿼리 길이 (긴 쿼리 = 복잡한 질문)
        query_tokens = len(query.split())
        if query_tokens > 100:
            score += 0.3
        elif query_tokens > 50:
            score += 0.2
        elif query_tokens > 20:
            score += 0.1

        # Factor 2: 컨텍스트 크기 (많은 컨텍스트 = 복잡한 추론 필요)
        total_context_tokens = sum(len(chunk.split()) for chunk in context_chunks)
        if total_context_tokens > 3000:
            score += 0.3
        elif total_context_tokens > 1500:
            score += 0.2
        elif total_context_tokens > 500:
            score += 0.1

        # Factor 3: 복잡한 쿼리 타입 감지
        complex_keywords = [
            'analyze', 'compare', 'explain why', 'reasoning',
            'complex', 'detailed analysis', 'pros and cons',
            'evaluate', 'assess', 'critique', 'synthesize',
            '분석', '비교', '이유', '장단점', '평가', '종합'
        ]
        if any(keyword in query.lower() for keyword in complex_keywords):
            score += 0.2

        # Factor 4: 다단계 추론 지시어 감지
        multi_step_indicators = [
            'first', 'then', 'finally', 'step by step',
            '첫째', '둘째', '마지막으로', '단계별'
        ]
        if any(indicator in query.lower() for indicator in multi_step_indicators):
            score += 0.15

        # Factor 5: 대화 히스토리 길이 (긴 대화 = 복잡한 맥락)
        if conversation_history and len(conversation_history) > 5:
            score += 0.1

        # Factor 6: 사용자 등급 (프리미엄 사용자는 더 나은 모델 편향)
        if user_tier == "premium":
            score += 0.1

        return min(1.0, score)

    @staticmethod
    def select_model(
        complexity: float,
        user_tier: str = "free",
        force_model: Optional[BedrockModel] = None
    ) -> BedrockModel:
        """복잡도 기반 모델 선택"""

        if force_model:
            return force_model

        # Premium 사용자: Haiku 3.5 또는 Sonnet
        if user_tier == "premium":
            return BedrockModel.SONNET_35 if complexity > 0.6 else BedrockModel.HAIKU_35

        # Free tier: 비용 최적화
        if complexity < 0.3:
            return BedrockModel.HAIKU_35  # 단순 쿼리
        elif complexity < 0.7:
            return BedrockModel.HAIKU_35  # 보통 쿼리
        else:
            return BedrockModel.SONNET_35  # 복잡한 쿼리만


class LLMFacade:
    """Bedrock LLM 통합 인터페이스 (지능형 라우팅)"""

    def __init__(
        self,
        region_name: str = "us-east-1",
        enable_cloudwatch: bool = True
    ):
        """
        Args:
            region_name: AWS 리전
            enable_cloudwatch: CloudWatch 메트릭 전송 여부
        """
        self.bedrock = boto3.client('bedrock-runtime', region_name=region_name)
        self.cloudwatch = boto3.client('cloudwatch', region_name=region_name) if enable_cloudwatch else None
        self.analyzer = QueryComplexityAnalyzer()
        self.enable_metrics = enable_cloudwatch

    def invoke(
        self,
        query: str,
        context_chunks: List[str],
        user_id: str,
        user_tier: str = "free",
        conversation_history: Optional[List[Dict]] = None,
        force_model: Optional[BedrockModel] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7
    ) -> Dict:
        """
        LLM 호출 (지능형 모델 선택)

        Args:
            query: 사용자 질문
            context_chunks: RAG 검색 결과
            user_id: 사용자 ID
            user_tier: 사용자 등급
            conversation_history: 대화 히스토리
            force_model: 강제 모델 선택 (테스트용)
            max_tokens: 최대 생성 토큰
            temperature: 생성 온도

        Returns:
            {
                'response': str,  # LLM 응답
                'model_used': str,  # 사용된 모델
                'complexity': float,  # 복잡도 점수
                'input_tokens': int,
                'output_tokens': int,
                'cost': float,  # USD
                'latency_ms': int
            }
        """
        start_time = time.time()

        # 모델 선택
        if force_model:
            model = force_model
            complexity = None
        else:
            complexity = self.analyzer.calculate_complexity(
                query, context_chunks, user_tier, conversation_history
            )
            model = self.analyzer.select_model(complexity, user_tier)

        # 프롬프트 구성
        prompt = self._build_prompt(query, context_chunks, conversation_history)

        # Bedrock 호출
        try:
            response = self._invoke_bedrock(
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # 비용 계산
            input_tokens = response['usage']['input_tokens']
            output_tokens = response['usage']['output_tokens']
            cost = self._calculate_cost(model, input_tokens, output_tokens)

            # CloudWatch 메트릭 전송
            if self.enable_metrics:
                self._publish_metrics(
                    model=model,
                    complexity=complexity,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost=cost,
                    latency_ms=latency_ms,
                    user_tier=user_tier,
                    fallback=False
                )

            return {
                'response': response['content'][0]['text'],
                'model_used': model.name,
                'complexity': complexity,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'cost': cost,
                'latency_ms': latency_ms,
                'fallback_occurred': False
            }

        except Exception as e:
            # 폴백: Sonnet 실패 시 Haiku로 재시도
            if model == BedrockModel.SONNET_35:
                print(f"⚠️ Sonnet failed, falling back to Haiku 3.5: {e}")

                fallback_response = self.invoke(
                    query=query,
                    context_chunks=context_chunks,
                    user_id=user_id,
                    user_tier=user_tier,
                    conversation_history=conversation_history,
                    force_model=BedrockModel.HAIKU_35,
                    max_tokens=max_tokens,
                    temperature=temperature
                )

                # 폴백 메트릭 전송
                if self.enable_metrics:
                    self.cloudwatch.put_metric_data(
                        Namespace='RAG/LLM',
                        MetricData=[{
                            'MetricName': 'ModelFallback',
                            'Value': 1,
                            'Unit': 'Count',
                            'Timestamp': datetime.utcnow(),
                            'Dimensions': [
                                {'Name': 'FromModel', 'Value': 'SONNET_35'},
                                {'Name': 'ToModel', 'Value': 'HAIKU_35'}
                            ]
                        }]
                    )

                fallback_response['fallback_occurred'] = True
                return fallback_response
            else:
                raise

    def _invoke_bedrock(
        self,
        model: BedrockModel,
        prompt: str,
        max_tokens: int,
        temperature: float
    ) -> Dict:
        """Bedrock API 호출"""

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        response = self.bedrock.invoke_model(
            modelId=model.value,
            body=json.dumps(body)
        )

        response_body = json.loads(response['body'].read())
        return response_body

    def _build_prompt(
        self,
        query: str,
        context_chunks: List[str],
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """RAG 프롬프트 구성"""

        # 컨텍스트 포맷팅
        context = "\n\n".join(
            f"[문서 {i+1}]\n{chunk}"
            for i, chunk in enumerate(context_chunks)
        )

        # 대화 히스토리 포함 (선택)
        history_text = ""
        if conversation_history:
            history_items = []
            for msg in conversation_history[-5:]:  # 최근 5개만
                role = "사용자" if msg['role'] == 'user' else "AI"
                history_items.append(f"{role}: {msg['content']}")
            history_text = f"\n\n<대화 히스토리>\n{chr(10).join(history_items)}\n</대화 히스토리>\n"

        prompt = f"""{history_text}
<문서>
{context}
</문서>

<질문>
{query}
</질문>

위 문서들을 참고하여 질문에 정확하고 간결하게 답변해주세요.
문서에 없는 내용은 추측하지 말고, 문서 기반으로만 답변하세요."""

        return prompt

    def _calculate_cost(
        self,
        model: BedrockModel,
        input_tokens: int,
        output_tokens: int
    ) -> float:
        """비용 계산 (USD)"""
        pricing = PRICING[model]
        input_cost = (input_tokens / 1000) * pricing.input_per_1k
        output_cost = (output_tokens / 1000) * pricing.output_per_1k
        return input_cost + output_cost

    def _publish_metrics(
        self,
        model: BedrockModel,
        complexity: Optional[float],
        input_tokens: int,
        output_tokens: int,
        cost: float,
        latency_ms: int,
        user_tier: str,
        fallback: bool
    ):
        """CloudWatch 메트릭 전송"""

        if not self.cloudwatch:
            return

        namespace = 'RAG/LLM'
        timestamp = datetime.utcnow()

        metrics = [
            # 토큰 사용량
            {
                'MetricName': 'InputTokens',
                'Value': input_tokens,
                'Unit': 'Count',
                'Timestamp': timestamp,
                'Dimensions': [
                    {'Name': 'Model', 'Value': model.name},
                    {'Name': 'UserTier', 'Value': user_tier}
                ]
            },
            {
                'MetricName': 'OutputTokens',
                'Value': output_tokens,
                'Unit': 'Count',
                'Timestamp': timestamp,
                'Dimensions': [
                    {'Name': 'Model', 'Value': model.name},
                    {'Name': 'UserTier', 'Value': user_tier}
                ]
            },
            # 비용 추적
            {
                'MetricName': 'LLMCost',
                'Value': cost,
                'Unit': 'None',  # USD
                'Timestamp': timestamp,
                'Dimensions': [
                    {'Name': 'Model', 'Value': model.name}
                ]
            },
            # 지연시간
            {
                'MetricName': 'LLMLatency',
                'Value': latency_ms,
                'Unit': 'Milliseconds',
                'Timestamp': timestamp,
                'Dimensions': [
                    {'Name': 'Model', 'Value': model.name}
                ]
            },
            # 모델 호출 분포
            {
                'MetricName': 'ModelInvocations',
                'Value': 1,
                'Unit': 'Count',
                'Timestamp': timestamp,
                'Dimensions': [
                    {'Name': 'Model', 'Value': model.name}
                ]
            }
        ]

        # 복잡도 점수 (계산된 경우)
        if complexity is not None:
            metrics.append({
                'MetricName': 'QueryComplexity',
                'Value': complexity,
                'Unit': 'None',
                'Timestamp': timestamp,
                'Dimensions': [
                    {'Name': 'Model', 'Value': model.name}
                ]
            })

        # CloudWatch에 전송
        try:
            self.cloudwatch.put_metric_data(
                Namespace=namespace,
                MetricData=metrics
            )
        except Exception as e:
            print(f"⚠️ Failed to publish CloudWatch metrics: {e}")


# 사용 예시
if __name__ == "__main__":
    # LLM Facade 초기화
    llm = LLMFacade(region_name='us-east-1', enable_cloudwatch=True)

    # RAG 쿼리 예시
    query = "RAG 시스템의 성능을 최적화하는 방법은?"
    context_chunks = [
        "RAG 시스템 최적화를 위해서는 벡터 인덱싱, 캐싱, 청크 크기 조정이 중요합니다...",
        "pgvector의 HNSW 인덱스를 사용하면 빠른 유사도 검색이 가능합니다..."
    ]

    result = llm.invoke(
        query=query,
        context_chunks=context_chunks,
        user_id="user123",
        user_tier="free"
    )

    print(f"✅ 모델: {result['model_used']}")
    print(f"💰 비용: ${result['cost']:.6f}")
    print(f"⚡ 지연시간: {result['latency_ms']}ms")
    print(f"📊 복잡도: {result['complexity']:.2f}")
    print(f"🔄 폴백 발생: {result['fallback_occurred']}")
    print(f"\n응답:\n{result['response']}")
