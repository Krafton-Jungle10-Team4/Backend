# RAG Platform Backend - AWS 배포 종합 가이드

**작성일**: 2025-11-09
**최종 업데이트**: 2025-11-09 23:57 (bot_id 기반 리팩토링 배포 완료)
**프로젝트**: RAG Platform Backend
**배포 환경**: AWS ECS Fargate (ap-northeast-2)
**도메인**: https://api.snapagent.store
**상태**: 🟢 정상 운영 중

---

## 📋 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [실제 기술 스택](#2-실제-기술-스택)
3. [아키텍처 다이어그램](#3-아키텍처-다이어그램)
4. [AWS 리소스 구성](#4-aws-리소스-구성)
5. [배포 프로세스](#5-배포-프로세스)
6. [핵심 트러블슈팅](#6-핵심-트러블슈팅)
7. [운영 가이드](#7-운영-가이드)
8. [비용 분석](#8-비용-분석)
9. [향후 개선 사항](#9-향후-개선-사항)

---

## 1. 프로젝트 개요

### 1.1 서비스 설명

RAG (Retrieval-Augmented Generation) Platform은 **봇(bot) 기반 문서 관리 및 AI 대화 시스템**입니다.

**주요 특징**:
- ✅ **봇(Bot) 단위 데이터 격리**: 각 봇별로 독립적인 문서 저장소
- ✅ **PostgreSQL pgvector 기반**: ChromaDB 대신 PostgreSQL 네이티브 벡터 검색
- ✅ **AWS Bedrock Titan 임베딩**: Sentence Transformers 대신 AWS 관리형 서비스
- ✅ **Anthropic Claude 메인 LLM**: GPT 대신 Claude Sonnet 4 사용
- ✅ **워크플로우 엔진**: 노드 기반 커스터마이징 가능한 RAG 파이프라인

### 1.2 최종 엔드포인트

```
Primary Domain: https://api.snapagent.store
Health Check:   https://api.snapagent.store/health
API Docs:       https://api.snapagent.store/docs
OpenAPI:        https://api.snapagent.store/openapi.json
```

---

## 2. 실제 기술 스택

### 2.1 코어 스택

| 카테고리 | 기술 | 버전/상세 | 용도 |
|---------|------|----------|------|
| **프레임워크** | FastAPI | 0.109.0 | REST API 서버 |
| **서버** | Uvicorn | 0.27.0 (uvloop, httptools) | ASGI 서버 |
| **언어** | Python | 3.11-slim | 런타임 |
| **배포** | Docker | Multi-stage build | 컨테이너화 |
| **오케스트레이션** | AWS ECS Fargate | - | 서버리스 컨테이너 |

### 2.2 데이터 레이어

| 카테고리 | 기술 | 상세 | 용도 |
|---------|------|------|------|
| **메인 DB** | PostgreSQL 16 | Aurora Serverless v2 | 사용자, 봇, 문서 메타데이터 |
| **벡터 DB** | pgvector | 0.2.4 (PostgreSQL extension) | 문서 임베딩 저장 및 검색 |
| **캐시** | Redis 7.1 | ElastiCache (TLS 암호화) | Rate limiting, 세션 |
| ~~**ChromaDB**~~ | ~~0.5.3~~ | ⚠️ **미사용 (레거시)** | 로컬 개발용으로만 존재 |

**중요**:
- ✅ **프로덕션은 pgvector 사용** (PostgreSQL 내장)
- ❌ **ChromaDB는 사용하지 않음** (requirements.txt에만 존재)

### 2.3 AI 레이어

| 카테고리 | 기술 | 모델/설정 | 용도 |
|---------|------|----------|------|
| **임베딩** | AWS Bedrock Titan | `amazon.titan-embed-text-v2:0` (1024차원) | 문서 벡터화 |
| **메인 LLM** | Anthropic Claude | `claude-sonnet-4-5-20250929` | RAG 응답 생성 |
| **보조 LLM** | OpenAI | GPT-3.5/4 (옵션) | Fallback/테스트용 |
| ~~**로컬 임베딩**~~ | ~~Sentence Transformers~~ | ⚠️ **미사용 (레거시)** | config.py에만 존재 |

**중요**:
- ✅ **프로덕션은 AWS Bedrock 사용** (boto3)
- ✅ **Claude가 메인 LLM** (Anthropic API)
- ❌ **Sentence Transformers는 사용하지 않음**

### 2.4 인증 및 보안

| 기능 | 기술 | 용도 |
|-----|------|------|
| **JWT 토큰** | python-jose | Access/Refresh 토큰 |
| **OAuth** | Authlib | Google 소셜 로그인 |
| **Rate Limiting** | SlowAPI + Redis | API 호출 제한 |
| **비밀 관리** | AWS Secrets Manager | 민감 정보 암호화 저장 |

### 2.5 문서 처리

| 기능 | 라이브러리 | 용도 |
|-----|----------|------|
| **PDF 파싱** | pypdf 3.17.4 | PDF 텍스트 추출 |
| **DOCX 파싱** | python-docx 1.1.0 | Word 문서 처리 |
| **텍스트 청킹** | LangChain 0.1.0 | 문서 분할 (텍스트 전용) |

**중요**: LangChain은 **텍스트 분할 전용**으로만 사용 (LangChain RAG 체인 미사용)

---

## 3. 아키텍처 다이어그램

### 3.1 전체 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                           INTERNET                                  │
│                    (Users, Widget Embeddings)                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                  ┌──────────▼──────────┐
                  │   Route 53 DNS      │
                  │ api.snapagent.store │
                  └──────────┬──────────┘
                             │
              ┌──────────────▼──────────────┐
              │   ACM SSL Certificate       │
              │  (Auto-renewal enabled)     │
              └──────────────┬──────────────┘
                             │
        ┌────────────────────▼────────────────────┐
        │   Application Load Balancer (ALB)      │
        │   - Listener 80: HTTP → HTTPS redirect │
        │   - Listener 443: HTTPS → ECS:8001     │
        └────────────────────┬────────────────────┘
                             │
    ┌────────────────────────▼────────────────────────┐
    │              VPC (10.0.0.0/16)                  │
    │  ┌──────────────────────────────────────────┐   │
    │  │        Public Subnets (ALB용)            │   │
    │  │  - 10.0.1.0/24 (ap-northeast-2a)         │   │
    │  │  - 10.0.2.0/24 (ap-northeast-2c)         │   │
    │  └──────────────────────────────────────────┘   │
    │                      │                           │
    │  ┌───────────────────▼──────────────────────┐   │
    │  │       Private Subnets (격리)             │   │
    │  │  - 10.0.11.0/24 (ap-northeast-2a)        │   │
    │  │  - 10.0.12.0/24 (ap-northeast-2c)        │   │
    │  │                                           │   │
    │  │  ┌─────────────────────────────────────┐ │   │
    │  │  │   ECS Fargate Cluster               │ │   │
    │  │  │   ┌───────────────────────────────┐ │ │   │
    │  │  │   │  rag-backend-service          │ │ │   │
    │  │  │   │  - Task: .5 vCPU, 2GB Memory  │ │ │   │
    │  │  │   │  - Port: 8001                 │ │ │   │
    │  │  │   │  - Image: ECR latest          │ │ │   │
    │  │  │   └───────────────────────────────┘ │ │   │
    │  │  └─────────────────────────────────────┘ │   │
    │  │                      │                    │   │
    │  │       ┌──────────────┼──────────────┐     │   │
    │  │       │              │              │     │   │
    │  │  ┌────▼────┐   ┌─────▼─────┐  ┌────▼────┐│   │
    │  │  │ Aurora  │   │  Redis    │  │ Bedrock ││   │
    │  │  │PostgreSQL│   │ElastiCache│  │ (Titan) ││   │
    │  │  │         │   │  (TLS)    │  │Embedding││   │
    │  │  │ pgvector│   │           │  │         ││   │
    │  │  └─────────┘   └───────────┘  └─────────┘│   │
    │  └───────────────────────────────────────────┘   │
    │                      │                           │
    │  ┌───────────────────▼──────────────────────┐   │
    │  │         NAT Gateway                      │   │
    │  │  (Private → Internet for AWS APIs)       │   │
    │  └──────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   ┌────▼─────┐      ┌───────▼───────┐   ┌──────▼──────┐
   │ Secrets  │      │  CloudWatch   │   │   ECR       │
   │ Manager  │      │     Logs      │   │ (Docker)    │
   │          │      │               │   │             │
   └──────────┘      └───────────────┘   └─────────────┘
```

### 3.2 데이터 플로우 (봇 기반 RAG)

```
┌──────────────────────────────────────────────────────────────────┐
│                    1. 문서 업로드 플로우                         │
└──────────────────────────────────────────────────────────────────┘

POST /api/v1/documents/upload?bot_id=123
         │
         ▼
┌─────────────────────┐
│  FastAPI Endpoint   │  ← JWT 인증 + bot_id 검증
│  (upload.py)        │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ DocumentService     │  ← 파일 파싱 (PDF/DOCX)
│ (document_service)  │  ← 텍스트 청킹 (LangChain)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ AWS Bedrock Titan   │  ← 임베딩 생성 (1024차원)
│ (boto3 bedrock)     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────────┐
│  PostgreSQL pgvector                │
│  ┌───────────────────────────────┐  │
│  │ document_embeddings 테이블    │  │
│  │  - bot_id (파티션 키)         │  │
│  │  - document_id                │  │
│  │  - chunk_id                   │  │
│  │  - embedding (vector 1024)    │  │
│  │  - content (text)             │  │
│  │  - metadata (jsonb)           │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                    2. RAG 대화 플로우                            │
└──────────────────────────────────────────────────────────────────┘

POST /api/v1/chat {"message": "질문", "bot_id": 123}
         │
         ▼
┌─────────────────────┐
│  ChatService        │  ← bot_id로 Bot 조회
│  (chat_service)     │  ← workflow 존재 여부 확인
└──────────┬──────────┘
           │
           ├─── workflow 있음 ───┐
           │                      │
           │                      ▼
           │          ┌─────────────────────┐
           │          │ WorkflowExecutor    │
           │          │  (executor.py)      │
           │          └──────────┬──────────┘
           │                     │
           │          ┌──────────▼───────────────┐
           │          │ Start Node → Knowledge   │
           │          │ Node → LLM Node → End    │
           │          └──────────┬───────────────┘
           │                     │
           │                     ▼
           │          ┌─────────────────────┐
           │          │  KnowledgeNode      │
           │          │  (knowledge_node)   │
           │          └──────────┬──────────┘
           │                     │
           ├─── workflow 없음 ───┤
           │                     │
           ▼                     ▼
┌─────────────────────┐  ┌──────────────────┐
│  VectorService      │  │  VectorService   │
│  (vector_service)   │  │ (via workflow)   │
└──────────┬──────────┘  └────────┬─────────┘
           │                      │
           └──────────┬───────────┘
                      │
                      ▼
          ┌─────────────────────┐
          │ 1. AWS Bedrock      │  ← 쿼리 임베딩 생성
          │    Titan Embedding  │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────────────────┐
          │ 2. PostgreSQL pgvector 검색     │
          │    SELECT ... WHERE bot_id=123  │
          │    ORDER BY embedding <=> $1    │
          │    LIMIT top_k                  │
          └──────────┬──────────────────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │ 3. Anthropic Claude │  ← 검색된 문서 컨텍스트
          │    claude-sonnet-4  │  ← 사용자 질문
          └──────────┬──────────┘     ↓
                     │            최종 답변 생성
                     ▼
          ┌─────────────────────┐
          │  ChatResponse       │
          │  - response         │
          │  - sources[]        │
          │  - session_id       │
          └─────────────────────┘
```

### 3.3 보안 및 인증 플로우

```
┌──────────────────────────────────────────────────────────────────┐
│                     인증 플로우                                   │
└──────────────────────────────────────────────────────────────────┘

1. Google OAuth 로그인
   GET /api/v1/auth/login/google
     │
     ├─→ Google OAuth Consent Screen
     │
     ▼
   GET /api/v1/auth/callback/google?code=xxx
     │
     ├─→ Google Token Exchange
     │
     ▼
   생성:
     - JWT Access Token (15분)
     - JWT Refresh Token (7일)
     - Redis Session 저장

2. API 호출 (JWT)
   Authorization: Bearer <access_token>
     │
     ├─→ JWT 검증 (python-jose)
     ├─→ Redis 세션 확인
     │
     ▼
   인증 성공 → 요청 처리

3. Rate Limiting (SlowAPI + Redis)
   모든 API 요청
     │
     ├─→ Redis GET rate_limit:{ip}:{endpoint}
     ├─→ 제한 초과 시 429 Too Many Requests
     │
     ▼
   허용된 요청 처리
```

---

## 4. AWS 리소스 구성

### 4.1 컴퓨팅 (ECS Fargate)

**클러스터**: `rag-cluster`
**서비스**: `rag-backend-service`

```yaml
Task Definition: rag-backend-task:18
Launch Type: Fargate
Platform: LINUX/X86_64
CPU: 1024 (.5 vCPU)
Memory: 2048 MB
Desired Count: 1
Auto Scaling: 1-4 tasks

Container:
  Image: 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest
  Port: 8001
  Health Check: /health

Environment Variables:
  LLM_PROVIDER: anthropic
  ANTHROPIC_MODEL: claude-sonnet-4-5-20250929
  AWS_REGION: ap-northeast-2
  ENVIRONMENT: production
  LOG_LEVEL: INFO
  WORKERS: 2

Secrets (Secrets Manager):
  DATABASE_USER, DATABASE_PASSWORD
  REDIS_PASSWORD
  ANTHROPIC_API_KEY
  OPENAI_API_KEY (fallback)
  JWT_SECRET_KEY
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
```

### 4.2 데이터베이스

**Aurora PostgreSQL Serverless v2**:
```yaml
Cluster: rag-aurora-cluster
Endpoint: rag-aurora-cluster.cluster-c3ogyocuq2mg.ap-northeast-2.rds.amazonaws.com
Port: 5432
Database: ragdb
Engine: PostgreSQL 16.1
ACU: 0.5 - 4 (Auto Scaling)
Extensions: pgvector

테이블 구조:
  - users (사용자)
  - teams (팀)
  - bots (봇)
  - document_embeddings (문서 임베딩)
    ├─ bot_id INT (파티션 키)
    ├─ document_id VARCHAR
    ├─ chunk_id VARCHAR
    ├─ embedding VECTOR(1024)  ← pgvector
    ├─ content TEXT
    └─ metadata JSONB
```

**ElastiCache Redis**:
```yaml
Cluster: rag-redis
Endpoint: master.rag-redis.lmxewk.apn2.cache.amazonaws.com
Port: 6379
Node Type: cache.t4g.micro
Engine: Redis 7.1
TLS: Enabled (rediss://)
용도: Rate limiting, Session storage
```

### 4.3 네트워크

**VPC**: `vpc-0c0a3a3baf79f4c66` (10.0.0.0/16)

**Public Subnets** (ALB용):
- `subnet-0eae0db7a71c06ec7` (ap-northeast-2a): 10.0.1.0/24
- `subnet-058a57e99e0f5bab6` (ap-northeast-2c): 10.0.2.0/24

**Private Subnets** (ECS, Database):
- `subnet-084722ea7ba3c2f54` (ap-northeast-2a): 10.0.11.0/24
- `subnet-06652259d983dbb7d` (ap-northeast-2c): 10.0.12.0/24

**NAT Gateway**: `nat-0a8cd454c39cf2486`

**보안 그룹**:
| 이름 | ID | 인바운드 | 아웃바운드 |
|------|-------|---------|----------|
| ALB-SG | sg-01b326d770b46ac95 | 0.0.0.0/0:80,443 | ECS-SG:8001 |
| ECS-SG | sg-0995b6046621c25f8 | ALB-SG:8001 | VPC:443,5432,6379 |
| DB-SG | sg-08affcfa97baaeac1 | ECS-SG:5432,6379 | All |

### 4.4 로드 밸런서 및 DNS

**Application Load Balancer**:
```yaml
Name: RAG-ALB-Seoul
DNS: RAG-ALB-Seoul-87215195.ap-northeast-2.elb.amazonaws.com
Scheme: Internet-facing

Listeners:
  - HTTP:80 → Redirect to HTTPS:443
  - HTTPS:443 → Forward to RAG-Backend-TG

Target Group:
  Name: RAG-Backend-TG
  Protocol: HTTP
  Port: 8001
  Health Check: GET /health (200 OK)
```

**Route 53**:
```yaml
Hosted Zone: snapagent.store (Z10422941CZPPWN7MPPT8)
Record: api.snapagent.store → ALB (Alias)
```

**ACM Certificate**:
```yaml
ARN: arn:aws:acm:ap-northeast-2:868651351239:certificate/da2273d4-15a9-45ff-ba49-fdca26f6c0ad
Domain: api.snapagent.store
Validation: DNS
Valid Until: 2026-12-08
Auto-renewal: Enabled
```

### 4.5 컨테이너 레지스트리

**ECR Repository**:
```yaml
Name: rag-backend
URI: 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend
Image Scanning: Enabled
Tag: latest (2025-11-09 23:56 업데이트)
Platform: linux/amd64 (중요!)
```

### 4.6 AI 서비스

**AWS Bedrock** (Titan Embeddings):
```yaml
Region: ap-northeast-2
Model ID: amazon.titan-embed-text-v2:0
Dimensions: 1024
Normalize: true
Access: IAM Role via boto3
```

**Anthropic Claude** (External API):
```yaml
Model: claude-sonnet-4-5-20250929
Temperature: 0.7
Max Tokens: 2000
Access: API Key via Secrets Manager
```

---

## 5. 배포 프로세스

### 5.1 수동 배포 (현재 방식)

```bash
# 1. 코드 변경 후 커밋
cd /Users/leeseungheon/Documents/개발/크래프톤정글10기/나만무/Backend/Backend
git add .
git commit -m "refactor: bot_id 기반 문서 관리로 전환

- user_uuid → bot_id 파라미터 변경
- API 엔드포인트 업데이트 (bot_id 필수)
- WorkflowExecutionContext에 bot_id/db 추가
- 모든 서비스 레이어에서 bot_id 기반 처리

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>"

# 2. Docker 이미지 빌드 (⚠️ 플랫폼 명시 필수!)
docker build --platform linux/amd64 -t rag-backend:latest .

# 3. ECR 로그인
aws ecr get-login-password --region ap-northeast-2 | \
  docker login --username AWS --password-stdin \
  868651351239.dkr.ecr.ap-northeast-2.amazonaws.com

# 4. 이미지 태그 및 푸시
docker tag rag-backend:latest \
  868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest
docker push 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest

# 5. ECS 서비스 재배포
aws ecs update-service \
  --cluster rag-cluster \
  --service rag-backend-service \
  --force-new-deployment \
  --region ap-northeast-2

# 6. 구 태스크 강제 종료 (새 이미지 즉시 적용)
TASK_ID=$(aws ecs list-tasks \
  --cluster rag-cluster \
  --service-name rag-backend-service \
  --region ap-northeast-2 \
  --query 'taskArns[0]' --output text | cut -d'/' -f3)

aws ecs stop-task \
  --cluster rag-cluster \
  --task $TASK_ID \
  --reason "Deploy new version" \
  --region ap-northeast-2

# 7. 배포 확인 (30-60초 대기)
watch -n 5 'aws ecs describe-services \
  --cluster rag-cluster \
  --services rag-backend-service \
  --region ap-northeast-2 \
  --query "services[0].[deployments[0].rolloutState,runningCount]" \
  --output table'

# 8. 헬스체크
curl https://api.snapagent.store/health

# 9. 로그 확인
aws logs tail /ecs/rag-backend --follow --region ap-northeast-2
```

### 5.2 배포 체크리스트

**배포 전**:
- [ ] 로컬에서 테스트 완료
- [ ] DB 마이그레이션 필요 여부 확인
- [ ] Breaking Changes 있는지 확인 (API 스펙 변경)
- [ ] `--platform linux/amd64` 플래그 확인

**배포 중**:
- [ ] ECR 푸시 성공 확인
- [ ] ECS Task 정상 시작 확인
- [ ] CloudWatch Logs 에러 없는지 확인
- [ ] Health Check 통과 확인

**배포 후**:
- [ ] API 동작 테스트 (/docs에서 확인)
- [ ] 주요 기능 스모크 테스트
- [ ] 모니터링 대시보드 확인
- [ ] 롤백 가능 상태 유지 (이전 이미지 보관)

---

## 6. 핵심 트러블슈팅

### 6.1 Docker 플랫폼 불일치 ⭐️ (최신)

**발생일**: 2025-11-09 23:50

**증상**:
```
exec /app/entrypoint.sh: exec format error
```

**원인**:
- Mac M1/M2 (ARM64)에서 빌드 → Fargate x86_64 실행 불가

**해결**:
```bash
# ❌ 잘못된 빌드
docker build -t rag-backend:latest .

# ✅ 올바른 빌드
docker build --platform linux/amd64 -t rag-backend:latest .
```

**교훈**:
- M1/M2 Mac에서는 **반드시** `--platform linux/amd64` 지정
- `latest` 태그 사용 시 ECS가 캐시된 이미지를 사용할 수 있음
- 구 태스크를 stop하면 강제로 새 이미지를 pull

### 6.2 Redis TLS 연결 오류

**증상**:
```python
AbstractConnection.__init__() got an unexpected keyword argument 'ssl'
```

**원인**:
- URL 쿼리 파라미터 `?ssl_cert_reqs=none`와 `rediss://` 스킴 충돌

**해결**:
```python
# config.py
def get_redis_url(self) -> str:
    if self.redis_password:
        return f"rediss://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
    else:
        return f"rediss://{self.redis_host}:{self.redis_port}/{self.redis_db}"

# rate_limit.py
storage_options = {
    "socket_connect_timeout": 5,
    "socket_timeout": 5,
    "ssl_cert_reqs": "none",  # URL이 아닌 옵션으로 전달
}
```

### 6.3 Private 서브넷 라우팅

**증상**:
- ECS Task가 Redis, Aurora 연결 타임아웃

**원인**:
- Private 서브넷이 라우트 테이블과 연결되지 않음

**해결**:
```bash
aws ec2 associate-route-table \
  --route-table-id rtb-04e2df6bc0b88aced \
  --subnet-id subnet-084722ea7ba3c2f54
```

### 6.4 보안 그룹 아웃바운드

**증상**:
- 라우팅은 정상이지만 연결 실패

**원인**:
- ECS 보안 그룹에 443 포트만 허용, 5432/6379 차단

**해결**:
```bash
# Redis
aws ec2 authorize-security-group-egress \
  --group-id sg-0995b6046621c25f8 \
  --protocol tcp --port 6379 --cidr 10.0.0.0/16

# Aurora
aws ec2 authorize-security-group-egress \
  --group-id sg-0995b6046621c25f8 \
  --protocol tcp --port 5432 --cidr 10.0.0.0/16
```

---

## 7. 운영 가이드

### 7.1 모니터링

**헬스체크**:
```bash
curl https://api.snapagent.store/health
# {"status":"healthy","app_name":"RAG Platform Backend","version":"1.0.0"}
```

**ECS 서비스 상태**:
```bash
aws ecs describe-services \
  --cluster rag-cluster \
  --services rag-backend-service \
  --region ap-northeast-2 \
  --query 'services[0].{Status:status,Desired:desiredCount,Running:runningCount}'
```

**실시간 로그**:
```bash
aws logs tail /ecs/rag-backend --follow --region ap-northeast-2
```

**에러 로그만**:
```bash
aws logs filter-pattern /ecs/rag-backend \
  --filter-pattern "ERROR" \
  --region ap-northeast-2
```

### 7.2 스케일링

**수동 스케일링**:
```bash
aws ecs update-service \
  --cluster rag-cluster \
  --service rag-backend-service \
  --desired-count 2 \
  --region ap-northeast-2
```

**Auto Scaling** (향후):
- Target Tracking: CPU 70% 유지
- Min: 1, Max: 4

### 7.3 롤백

**이전 버전으로 롤백**:
```bash
# 1. 이전 이미지 확인
aws ecr describe-images --repository-name rag-backend --region ap-northeast-2

# 2. 이전 이미지 태그를 latest로 변경
docker pull 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:PREVIOUS_SHA
docker tag 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:PREVIOUS_SHA \
  868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest
docker push 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest

# 3. ECS 재배포
aws ecs update-service --cluster rag-cluster \
  --service rag-backend-service --force-new-deployment --region ap-northeast-2
```

---

## 8. 비용 분석

### 8.1 월간 예상 비용 (USD)

| 서비스 | 리소스 | 월 비용 |
|--------|--------|--------|
| **ECS Fargate** | 1 Task (.5 vCPU, 2GB) | ~$10 |
| **Aurora Serverless v2** | 0.5 ACU 평균 | ~$45 |
| **ElastiCache Redis** | cache.t4g.micro | ~$12 |
| **ALB** | 1 ALB + 트래픽 | ~$20 |
| **NAT Gateway** | 1 NAT + 데이터 전송 | ~$35 |
| **Route 53** | 1 Hosted Zone | ~$0.5 |
| **ACM** | 1 Certificate | $0 (무료) |
| **Secrets Manager** | 11 Secrets | ~$4.5 |
| **CloudWatch Logs** | 5GB/월 | ~$2.5 |
| **ECR** | 10GB 스토리지 | ~$1 |
| **Bedrock Titan** | 1M 토큰/월 | ~$0.1 |
| **Anthropic Claude** | API 호출 (변동) | ~$20-50 |
| **합계** | | **~$150-180/월** |

### 8.2 비용 최적화

**즉시 적용 가능**:
- CloudWatch Logs 보관 기간 7일
- 미사용 스냅샷 삭제
- Aurora ACU 0.5 Min 유지

**추후 검토**:
- Fargate Savings Plan
- NAT Gateway → VPC Endpoints (S3, Bedrock)

---

## 9. 향후 개선 사항

### 9.1 우선순위 높음

**CloudWatch 알람**:
- CPU > 80% (5분)
- Memory > 80% (5분)
- Target Unhealthy (1분)
- 5xx 에러율 > 1%

**Auto Scaling 정책**:
- Target Tracking: CPU 70%
- Min: 1, Max: 4

### 9.2 우선순위 중간

**WAF 설정**:
- Rate Limiting
- SQL Injection 차단
- XSS 공격 차단

**CI/CD 자동화**:
- GitHub Actions
- 자동 빌드/푸시/배포

### 9.3 우선순위 낮음

**X-Ray 분산 추적**
**Multi-AZ 고가용성**
**VPC Endpoints** (NAT 비용 절감)

---

## 부록: 빠른 참조

### A. 주요 ARN/ID

| 리소스 | 값 |
|--------|-----|
| VPC | vpc-0c0a3a3baf79f4c66 |
| ECS Cluster | rag-cluster |
| ECS Service | rag-backend-service |
| Task Definition | rag-backend-task:18 |
| ECR | 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend |
| Aurora | rag-aurora-cluster.cluster-c3ogyocuq2mg.ap-northeast-2.rds.amazonaws.com |
| Redis | master.rag-redis.lmxewk.apn2.cache.amazonaws.com |

### B. 환경 변수 (프로덕션)

```bash
# Core
ENVIRONMENT=production
LLM_PROVIDER=anthropic
AWS_REGION=ap-northeast-2

# Database
DATABASE_HOST=rag-aurora-cluster.cluster-c3ogyocuq2mg.ap-northeast-2.rds.amazonaws.com
DATABASE_NAME=ragdb

# Redis
REDIS_HOST=master.rag-redis.lmxewk.apn2.cache.amazonaws.com
REDIS_PORT=6379

# AI Models
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929

# Secrets (Secrets Manager)
DATABASE_USER, DATABASE_PASSWORD
REDIS_PASSWORD
ANTHROPIC_API_KEY
JWT_SECRET_KEY
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
```

---

**문서 버전**: 3.0 (bot_id 기반 리팩토링 반영)
**최종 업데이트**: 2025-11-09 23:57
**작성자**: Claude Code
**주요 변경사항**:
- 실제 사용 중인 기술 스택으로 정정 (pgvector, Bedrock Titan, Claude)
- 미사용 기술 명시 (ChromaDB, Sentence Transformers)
- bot_id 기반 데이터 격리 아키텍처 추가
- 워크플로우 엔진 플로우 다이어그램 추가
- Docker 플랫폼 이슈 최신 트러블슈팅 추가
- 실제 환경 변수 및 Secrets 목록 업데이트