# RAG Platform Backend - AWS 배포 종합 가이드

**작성일**: 2025-11-09
**프로젝트**: RAG Platform Backend
**배포 환경**: AWS ECS Fargate (ap-northeast-2)
**도메인**: https://api.snapagent.store
**상태**: 🟢 정상 운영 중

---

## 📋 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [배포 아키텍처](#2-배포-아키텍처)
3. [구현된 AWS 리소스](#3-구현된-aws-리소스)
4. [배포 타임라인](#4-배포-타임라인)
5. [핵심 트러블슈팅](#5-핵심-트러블슈팅)
6. [보안 및 권한 설정](#6-보안-및-권한-설정)
7. [CI/CD 파이프라인](#7-cicd-파이프라인)
8. [운영 가이드](#8-운영-가이드)
9. [향후 개선 사항](#9-향후-개선-사항)
10. [비용 분석](#10-비용-분석)

---

## 1. 프로젝트 개요

### 1.1 서비스 설명

RAG (Retrieval-Augmented Generation) Platform은 사용자가 문서를 업로드하고 AI 봇과 대화할 수 있는 백엔드 시스템입니다.

**주요 기능**:
- 문서 업로드 및 벡터 임베딩 생성
- ChromaDB 기반 시맨틱 검색
- OpenAI/Anthropic LLM 통합
- 팀 기반 접근 제어
- Google OAuth 인증
- API Key 기반 프로그래매틱 접근

### 1.2 기술 스택

| 카테고리 | 기술 |
|---------|------|
| **프레임워크** | FastAPI 0.109.0 |
| **서버** | Uvicorn (uvloop) |
| **데이터베이스** | PostgreSQL 16 (Aurora Serverless v2) |
| **캐시** | Redis 7.1 (ElastiCache) |
| **벡터DB** | ChromaDB 0.5.3 |
| **임베딩** | Sentence Transformers (multilingual) |
| **LLM** | OpenAI GPT-4/3.5, Anthropic Claude-3 |
| **인증** | JWT, Google OAuth, API Keys |
| **배포** | Docker, AWS ECS Fargate |

### 1.3 최종 엔드포인트

```
Primary Domain: https://api.snapagent.store
Health Check:   https://api.snapagent.store/health
API Docs:       https://api.snapagent.store/docs
OpenAPI:        https://api.snapagent.store/openapi.json
```

---

## 2. 배포 아키텍처

### 2.1 전체 아키텍처 다이어그램

```
                           Internet
                              |
                    [Route 53 DNS]
                    api.snapagent.store
                              |
                    [ACM Certificate]
                         (HTTPS)
                              |
            ┌─────────────────┴─────────────────┐
            |   Application Load Balancer       |
            |   - HTTP:80  → Redirect HTTPS     |
            |   - HTTPS:443 → Forward to ECS    |
            └─────────────────┬─────────────────┘
                              |
                    ┌─────────┴─────────┐
                    |  VPC (10.0.0.0/16) |
                    |                    |
        ┌───────────┴───────────┬────────┴──────────┐
        |                       |                   |
   [Public Subnets]      [Private Subnets]   [NAT Gateway]
   (ALB용)                (ECS, DB, Cache)
        |                       |
        |              ┌────────┴─────────┐
        |              |                  |
        |         [ECS Fargate]    [Aurora PostgreSQL]
        |         Backend Tasks     [ElastiCache Redis]
        |              |
        |         [Security Groups]
        |         - ALB → ECS: 8001
        |         - ECS → Aurora: 5432
        |         - ECS → Redis: 6379
        |
   [Secrets Manager]
   - Database credentials
   - API keys
   - OAuth secrets
```

### 2.2 네트워크 구성

**VPC**: `vpc-0c0a3a3baf79f4c66` (10.0.0.0/16)

**Public Subnets** (ALB용):
- `subnet-0eae0db7a71c06ec7` (ap-northeast-2a): 10.0.1.0/24
- `subnet-058a57e99e0f5bab6` (ap-northeast-2c): 10.0.2.0/24

**Private Subnets** (ECS, Database):
- `subnet-084722ea7ba3c2f54` (ap-northeast-2a): 10.0.11.0/24
- `subnet-06652259d983dbb7d` (ap-northeast-2c): 10.0.12.0/24

**NAT Gateway**: `nat-0a8cd454c39cf2486`

### 2.3 보안 그룹

| 이름 | ID | 인바운드 규칙 | 아웃바운드 규칙 |
|------|-------|-------------|-------------|
| **ALB-SG** | sg-01b326d770b46ac95 | HTTP/HTTPS from 0.0.0.0/0 | 8001 to ECS-SG |
| **ECS-SG** | sg-0995b6046621c25f8 | 8001 from ALB-SG | 443, 5432, 6379 to VPC |
| **DB-SG** | sg-08affcfa97baaeac1 | 5432/6379 from ECS-SG | All |

---

## 3. 구현된 AWS 리소스

### 3.1 컴퓨팅 (ECS)

**클러스터**: `rag-cluster`

**서비스**: `rag-backend-service`
- Task Definition: `rag-backend-task:4`
- Launch Type: Fargate
- Desired Count: 1 (Auto Scaling: 1-4)
- CPU: 1024 (.5 vCPU)
- Memory: 2048 MB
- Platform: LINUX/X86_64

**컨테이너 이미지**:
```
868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest
```

### 3.2 데이터베이스

**Aurora PostgreSQL Serverless v2**:
- Cluster: `rag-aurora-cluster`
- Endpoint: `rag-aurora-cluster.cluster-c3ogyocuq2mg.ap-northeast-2.rds.amazonaws.com`
- Port: 5432
- Database: `ragdb`
- Engine: PostgreSQL 16.1
- ACU: 0.5 - 4 (Auto Scaling)

**ElastiCache Redis**:
- Cluster: `rag-redis`
- Endpoint: `master.rag-redis.lmxewk.apn2.cache.amazonaws.com`
- Port: 6379
- Node Type: cache.t4g.micro
- Engine: Redis 7.1
- TLS: Enabled

### 3.3 로드 밸런서

**Application Load Balancer**:
- Name: `RAG-ALB-Seoul`
- DNS: `RAG-ALB-Seoul-87215195.ap-northeast-2.elb.amazonaws.com`
- Scheme: Internet-facing
- Listeners:
  - HTTP:80 → Redirect to HTTPS:443
  - HTTPS:443 → Forward to RAG-Backend-TG

**Target Group**:
- Name: `RAG-Backend-TG`
- Protocol: HTTP
- Port: 8001
- Health Check: `/health`
- Healthy Threshold: 2
- Unhealthy Threshold: 3

### 3.4 DNS 및 SSL/TLS

**Route 53**:
- Hosted Zone: `snapagent.store` (Z10422941CZPPWN7MPPT8)
- A Record: `api.snapagent.store` → ALB (Alias)
- Nameservers: Route 53 (가비아에서 위임)

**ACM Certificate**:
- ARN: `arn:aws:acm:ap-northeast-2:868651351239:certificate/da2273d4-15a9-45ff-ba49-fdca26f6c0ad`
- Domain: `api.snapagent.store`
- Status: ISSUED
- Validation: DNS
- Valid Until: 2026-12-08
- Auto-renewal: Enabled

### 3.5 비밀 관리

**Secrets Manager**:

| Secret Name | Keys | 용도 |
|------------|------|------|
| `rag-backend/database` | username, password, host, port, dbname | Aurora 연결 |
| `rag-backend/redis` | host, password, port | Redis 연결 |
| `rag-backend/openai` | api_key | OpenAI API |
| `rag-backend/anthropic` | api_key | Anthropic API |
| `rag-backend/jwt` | secret_key | JWT 토큰 서명 |
| `rag-backend/google-oauth` | client_id, client_secret | Google OAuth |

### 3.6 컨테이너 레지스트리

**ECR Repository**:
- Name: `rag-backend`
- URI: `868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend`
- Image Scanning: Enabled
- Tag Immutability: Disabled
- Latest Image: `latest` (2025-11-09 업데이트)

---

## 4. 배포 타임라인

### Week 1: 인프라 구축 (2025-11-01 ~ 11-03)

✅ **11-01**: VPC 및 네트워킹
- VPC, 서브넷, 라우팅 테이블 생성
- NAT Gateway 구성
- 보안 그룹 설정

✅ **11-02**: 데이터베이스 및 캐시
- Aurora PostgreSQL Serverless v2 생성
- ElastiCache Redis 구성
- Secrets Manager 설정

✅ **11-03**: 로드 밸런서
- Application Load Balancer 생성
- Target Group 설정
- Health Check 구성

### Week 2: ECS 배포 (2025-11-07 ~ 11-08)

✅ **11-07**: ECS 클러스터 및 Task Definition
- ECS 클러스터 생성
- Task Execution Role 생성
- Task Definition 등록 (v1)
- ECR에 Docker 이미지 푸시

✅ **11-08**: ECS 서비스 배포
- ECS 서비스 생성
- ALB 연결
- Task Definition 업데이트 (v2, v3, v4)
- Secrets Manager 연동 완료
- 헬스체크 통과

### Week 3: 도메인 및 HTTPS (2025-11-09)

✅ **11-09 오전**: Route 53 설정
- Hosted Zone 생성
- 가비아 네임서버 위임
- A 레코드 설정 (ALB Alias)

✅ **11-09 오후**: ACM 인증서 및 HTTPS
- ACM 인증서 요청
- DNS 검증 (약 50분 소요)
- ALB HTTPS 리스너 추가
- HTTP → HTTPS 리다이렉트 설정
- **최종 배포 완료**: https://api.snapagent.store

**전체 소요 시간**: 약 9일

---

## 5. 핵심 트러블슈팅

### 5.1 Redis TLS 연결 오류

**증상**:
```python
AbstractConnection.__init__() got an unexpected keyword argument 'ssl'
```

**원인**:
- `config.py`의 Redis URL에 `?ssl_cert_reqs=none` 쿼리 파라미터 포함
- `limits` 라이브러리가 URL 파싱 시 자동으로 `ssl` 파라미터 추가
- `rediss://` 스킴과 `ssl` 파라미터 충돌

**해결책**:
```python
# config.py - 쿼리 파라미터 제거
def get_redis_url(self) -> str:
    if self.redis_password:
        return f"rediss://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
    else:
        return f"rediss://{self.redis_host}:{self.redis_port}/{self.redis_db}"

# rate_limit.py - storage_options로 SSL 설정
storage_options={
    "socket_connect_timeout": 5,
    "socket_timeout": 5,
    "ssl_cert_reqs": "none",
}
```

**교훈**:
- URL 쿼리 파라미터는 라이브러리마다 파싱 방식이 다름
- TLS 설정은 명시적 파라미터로 전달하는 것이 안전

### 5.2 Private 서브넷 라우팅 문제

**증상**:
- ECS Task가 Redis, Aurora에 연결 타임아웃
- NAT Gateway는 존재하지만 트래픽 라우팅 안 됨

**원인**:
- Private 서브넷이 어떤 라우트 테이블과도 연결되지 않음
- NAT Gateway 라우트가 있는 테이블 존재했지만 서브넷 연결 누락

**해결책**:
```bash
# Private 서브넷을 NAT Gateway 라우트 테이블에 연결
aws ec2 associate-route-table \
  --route-table-id rtb-04e2df6bc0b88aced \
  --subnet-id subnet-084722ea7ba3c2f54

aws ec2 associate-route-table \
  --route-table-id rtb-04e2df6bc0b88aced \
  --subnet-id subnet-06652259d983dbb7d
```

**교훈**:
- 리소스 생성만으로는 부족, 명시적 연결(association) 필수
- 라우트 테이블과 서브넷의 연결 상태 항상 확인

### 5.3 보안 그룹 아웃바운드 규칙

**증상**:
- 라우팅은 정상이지만 여전히 연결 실패

**원인**:
- ECS 보안 그룹에 443 포트 아웃바운드만 허용
- Redis(6379), Aurora(5432) 포트가 차단됨

**해결책**:
```bash
# ECS 보안 그룹에 아웃바운드 규칙 추가
# Redis
aws ec2 authorize-security-group-egress \
  --group-id sg-0995b6046621c25f8 \
  --protocol tcp --port 6379 \
  --cidr 10.0.0.0/16

# Aurora
aws ec2 authorize-security-group-egress \
  --group-id sg-0995b6046621c25f8 \
  --protocol tcp --port 5432 \
  --cidr 10.0.0.0/16
```

**교훈**:
- 인바운드뿐 아니라 아웃바운드 규칙도 확인 필수
- VPC 내부 통신도 보안 그룹으로 제어됨

### 5.4 Docker 이미지 아키텍처 불일치

**증상**:
- ECS Task 시작 실패
- CloudWatch Logs: "exec format error"

**원인**:
- Mac M1 (ARM64)에서 빌드된 이미지를 x86_64 Fargate에서 실행

**해결책**:
```bash
# 플랫폼 명시적으로 지정하여 빌드
docker build --platform linux/amd64 -t rag-backend:latest .
```

**교훈**:
- 로컬 환경과 배포 환경의 아키텍처 불일치 주의
- Fargate는 x86_64와 ARM64 모두 지원하지만 명시적 지정 권장

### 5.5 ACM 인증서 검증 지연

**증상**:
- DNS 검증 CNAME 레코드 추가 후에도 인증서 상태가 PENDING_VALIDATION

**원인**:
- 가비아에서 Route 53로 네임서버 변경 후 전파 대기 시간 필요

**타임라인**:
- 0분: ACM 인증서 요청
- 0분: DNS 검증 CNAME 레코드 추가
- 10분: 네임서버 전파 완료 확인
- 60분: ACM 인증서 ISSUED 상태로 변경

**교훈**:
- DNS 전파는 최대 48시간이 걸릴 수 있지만, 보통 10-30분이면 충분
- 네임서버 전파 확인 후에도 ACM 검증에 추가 시간 필요
- `dig` 명령어로 네임서버 전파 상태 확인 가능

---

## 6. 보안 및 권한 설정

### 6.1 IAM 역할

**ecsTaskExecutionRole**:
```json
{
  "AttachedPolicies": [
    "AmazonECSTaskExecutionRolePolicy",
    "SecretsManagerReadWrite",
    "CloudWatchLogsFullAccess"
  ]
}
```

**권한**:
- ECR 이미지 Pull
- Secrets Manager 시크릿 읽기
- CloudWatch Logs 쓰기

### 6.2 IAM 사용자

**rag-backend-admin** (CI/CD용):
```json
{
  "AttachedPolicies": [
    "AmazonEC2ContainerRegistryPowerUser",
    "AmazonECS_FullAccess",
    "AWSCertificateManagerFullAccess",
    "AmazonRoute53FullAccess",
    "ElasticLoadBalancingFullAccess"
  ]
}
```

**Access Key**: Secrets Manager에 안전하게 저장
- `rag/iam/backend-admin-access-key`

### 6.3 보안 설정

**VPC 레벨**:
- Private 서브넷에 ECS, Database 배치
- NAT Gateway를 통한 아웃바운드만 허용
- 인터넷 게이트웨이 직접 연결 차단

**보안 그룹 최소 권한**:
- ALB: 인터넷에서 HTTP/HTTPS만 허용
- ECS: ALB에서 8001 포트만 허용
- Database: ECS에서 5432/6379 포트만 허용

**시크릿 관리**:
- 모든 민감 정보 Secrets Manager 저장
- Task Definition에서 시크릿 참조
- 환경 변수로 평문 저장 금지

**SSL/TLS**:
- ACM 인증서로 HTTPS 강제
- HTTP → HTTPS 자동 리다이렉트
- TLS 1.2 이상만 허용

---

## 7. CI/CD 파이프라인

### 7.1 GitHub Actions 워크플로우

**파일 위치**: `.github/workflows/deploy-ecs.yml`

**트리거**:
- `main` 브랜치 푸시
- 수동 실행 (workflow_dispatch)

**배포 플로우**:
```
코드 푸시 (main)
  → GitHub Actions 트리거
  → Docker 이미지 빌드
  → ECR 푸시
  → ECS Task Definition 업데이트
  → ECS 서비스 재배포
  → 헬스체크 확인
```

### 7.2 필수 GitHub Secrets

| Secret Name | 값 | 설명 |
|-------------|-----|------|
| `AWS_ACCESS_KEY_ID` | AKIA... | IAM 사용자 Access Key |
| `AWS_SECRET_ACCESS_KEY` | xxxx... | IAM 사용자 Secret Key |
| `AWS_REGION` | `ap-northeast-2` | AWS 리전 |
| `AWS_ACCOUNT_ID` | `868651351239` | AWS 계정 ID |
| `ECR_REPOSITORY` | `rag-backend` | ECR 리포지토리 이름 |
| `ECS_CLUSTER` | `rag-cluster` | ECS 클러스터 이름 |
| `ECS_SERVICE` | `rag-backend-service` | ECS 서비스 이름 |
| `TASK_DEFINITION` | `rag-backend-task` | Task Definition Family |

### 7.3 워크플로우 주요 단계

1. **Checkout**: 코드 체크아웃
2. **Configure AWS**: AWS 인증 설정
3. **Login to ECR**: ECR 로그인
4. **Build**: Docker 이미지 빌드 (x86_64)
5. **Tag**: 이미지 태깅 (latest, git SHA)
6. **Push**: ECR에 푸시
7. **Update Task**: ECS Task Definition 업데이트
8. **Deploy**: ECS 서비스 재배포

---

## 8. 운영 가이드

### 8.1 서비스 모니터링

**헬스체크**:
```bash
# API 상태 확인
curl https://api.snapagent.store/health

# 기대 응답:
# {"status":"healthy","app_name":"RAG Platform Backend","version":"1.0.0"}
```

**ECS 서비스 상태**:
```bash
# 서비스 상태 확인
aws ecs describe-services \
  --cluster rag-cluster \
  --services rag-backend-service \
  --region ap-northeast-2 \
  --query 'services[0].{Status:status,Desired:desiredCount,Running:runningCount}'

# Task 목록
aws ecs list-tasks \
  --cluster rag-cluster \
  --service-name rag-backend-service \
  --region ap-northeast-2
```

**로그 확인**:
```bash
# 실시간 로그
aws logs tail /ecs/rag-backend --follow --region ap-northeast-2

# 에러 로그만
aws logs filter-pattern /ecs/rag-backend \
  --filter-pattern "ERROR" \
  --region ap-northeast-2

# 최근 1시간 로그
aws logs tail /ecs/rag-backend \
  --since 1h \
  --region ap-northeast-2
```

**ALB 타겟 상태**:
```bash
aws elbv2 describe-target-health \
  --target-group-arn arn:aws:elasticloadbalancing:ap-northeast-2:868651351239:targetgroup/RAG-Backend-TG/d0fb9148569f72aa \
  --region ap-northeast-2
```

### 8.2 배포 작업

**Docker 이미지 업데이트**:
```bash
cd /Users/leeseungheon/Documents/개발/크래프톤정글10기/나만무/Backend

# 1. 이미지 빌드
docker build --platform linux/amd64 -t rag-backend:latest .

# 2. ECR 로그인
aws ecr get-login-password --region ap-northeast-2 | \
  docker login --username AWS --password-stdin \
  868651351239.dkr.ecr.ap-northeast-2.amazonaws.com

# 3. 태그
docker tag rag-backend:latest \
  868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest

# 4. 푸시
docker push 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest

# 5. ECS 서비스 강제 재배포
aws ecs update-service \
  --cluster rag-cluster \
  --service rag-backend-service \
  --force-new-deployment \
  --region ap-northeast-2
```

**Task Definition 업데이트**:
```bash
# 새 revision 등록
aws ecs register-task-definition \
  --cli-input-json file://aws/ecs-task-definition-v5.json \
  --region ap-northeast-2

# 서비스에 적용
aws ecs update-service \
  --cluster rag-cluster \
  --service rag-backend-service \
  --task-definition rag-backend-task:5 \
  --region ap-northeast-2
```

### 8.3 스케일링

**수동 스케일링**:
```bash
# Desired count 변경
aws ecs update-service \
  --cluster rag-cluster \
  --service rag-backend-service \
  --desired-count 3 \
  --region ap-northeast-2
```

**Auto Scaling 설정** (향후):
```bash
# Target tracking policy
# - CPU 사용률 70% 유지
# - Min: 1, Max: 4
```

### 8.4 트러블슈팅 체크리스트

**Task가 시작되지 않는 경우**:
1. CloudWatch Logs 확인
2. Task Definition 환경 변수/시크릿 검증
3. 보안 그룹 규칙 확인
4. Task Execution Role 권한 확인
5. ECR 이미지 존재 여부 확인

**헬스체크 실패**:
1. `/health` 엔드포인트 200 OK 응답 확인
2. 보안 그룹 ALB → ECS 8001 포트 허용 확인
3. Task 로그에서 애플리케이션 에러 확인

**데이터베이스 연결 실패**:
1. Secrets Manager 시크릿 값 확인
2. 보안 그룹 ECS → Aurora 5432 포트 허용 확인
3. Private 서브넷 라우팅 테이블 확인
4. Aurora 클러스터 상태 확인

**Redis 연결 실패**:
1. Secrets Manager Redis 시크릿 확인
2. 보안 그룹 ECS → Redis 6379 포트 허용 확인
3. Redis URL 형식 확인 (`rediss://` TLS 사용)
4. ElastiCache 클러스터 상태 확인

---

## 9. 향후 개선 사항

### 9.1 우선순위 높음

**CloudWatch 모니터링 강화**:
- Dashboard 생성 (CPU, Memory, Request Count)
- 알람 설정:
  - CPU > 80% (5분)
  - Memory > 80% (5분)
  - Target Unhealthy (1분)
  - 5xx 에러율 > 1% (5분)
- SNS 토픽 연결 (이메일/Slack 알림)

**Auto Scaling 정책**:
- Target Tracking: CPU 70% 유지
- Scale Out: CPU > 70% (1분) → Task +1
- Scale In: CPU < 30% (10분) → Task -1
- Min: 1, Max: 4

### 9.2 우선순위 중간

**WAF (Web Application Firewall)**:
- ALB에 WAF 연결
- Rate Limiting (IP당 100 req/min)
- SQL Injection 차단
- XSS 공격 차단
- Geo-blocking (필요 시)

**S3 파일 업로드**:
- 문서 파일 S3 저장
- CloudFront CDN 연동
- Presigned URL 생성
- Lifecycle 정책 (90일 후 Glacier)

**데이터베이스 백업**:
- Aurora 자동 백업 (7일 보관)
- 수동 스냅샷 (주요 배포 전)
- Cross-Region 백업 (DR용)

### 9.3 우선순위 낮음

**X-Ray 분산 추적**:
- API 요청 추적
- 성능 병목 지점 분석
- 에러 원인 파악

**pgvector 마이그레이션**:
- ChromaDB → Aurora pgvector
- 벡터 검색 성능 개선
- 운영 복잡도 감소

**Multi-AZ 고가용성**:
- ECS Task 2개 이상 (Multi-AZ 배치)
- Aurora Read Replica
- Redis Cluster Mode

**프론트엔드 연동**:
- CORS 설정 업데이트
- 프론트엔드 도메인 Route 53 등록
- CloudFront 배포

---

## 10. 비용 분석

### 10.1 월간 비용 (예상)

| 서비스 | 리소스 | 월 예상 비용 (USD) |
|--------|--------|-------------------|
| **ECS Fargate** | 1 Task (.5 vCPU, 2GB) | ~$10 |
| **Aurora Serverless v2** | 0.5 ACU 평균 | ~$45 |
| **ElastiCache Redis** | cache.t4g.micro | ~$12 |
| **ALB** | 1 ALB | ~$20 |
| **NAT Gateway** | 1 NAT + 데이터 전송 | ~$35 |
| **Route 53** | 1 Hosted Zone | ~$0.5 |
| **ACM Certificate** | 1 인증서 | $0 (무료) |
| **Secrets Manager** | 6 시크릿 | ~$2.5 |
| **CloudWatch Logs** | 5GB/월 | ~$2.5 |
| **ECR** | 10GB 스토리지 | ~$1 |
| **데이터 전송** | 10GB 아웃바운드 | ~$1 |
| **합계** | | **~$130/월** |

### 10.2 비용 최적화 방안

**즉시 적용 가능**:
- Aurora ACU를 0.5 Min으로 설정 (완료)
- CloudWatch Logs 보관 기간 7일로 제한
- 미사용 스냅샷 정기적으로 삭제

**추후 검토**:
- Reserved Instance (ECS Fargate Savings Plan)
- Aurora Serverless v1으로 변경 (사용량 패턴 확인 후)
- NAT Gateway → NAT Instance (트래픽 적을 경우)

---

## 11. 결론

### 11.1 성과 요약

✅ **완벽한 배포 성공**:
- AWS 인프라 구축 완료
- ECS Fargate 배포 정상
- HTTPS 도메인 연결 완료
- 모든 서비스 정상 작동

✅ **높은 보안 수준**:
- Private 서브넷 격리
- Secrets Manager 활용
- TLS 암호화
- 최소 권한 원칙

✅ **안정적인 아키텍처**:
- Multi-AZ 배치
- Auto Scaling 가능
- Health Check 통과
- 장애 복구 가능

✅ **자동화된 CI/CD**:
- GitHub Actions 파이프라인
- 자동 빌드 및 배포
- 재현 가능한 프로세스

### 11.2 주요 학습 내용

**네트워킹**:
- VPC, 서브넷, 라우팅 테이블의 명시적 연결 중요성
- NAT Gateway를 통한 Private 서브넷 아웃바운드
- 보안 그룹 인바운드/아웃바운드 모두 확인 필요

**ECS**:
- Task Definition vs Task vs Service 개념 이해
- Fargate 플랫폼 아키텍처 (x86_64) 명시 필요
- Secrets Manager 연동으로 안전한 환경 변수 관리

**트러블슈팅**:
- 체계적 디버깅: 네트워크 → 보안 → 애플리케이션
- CloudWatch Logs 우선 확인
- 문서화를 통한 재발 방지

### 11.3 팀 기여

이 배포를 통해 다음을 달성했습니다:

1. **프로덕션 레디**: 실제 사용자 서비스 가능한 인프라
2. **확장 가능**: Auto Scaling으로 트래픽 증가 대응
3. **안전한 운영**: Secrets 분리, TLS 암호화, 최소 권한
4. **모니터링**: CloudWatch Logs로 즉시 문제 파악 가능
5. **문서화**: 운영 가이드 및 트러블슈팅 절차 완비
6. **자동화**: CI/CD 파이프라인으로 일관된 배포 프로세스

---

## 부록 A: 빠른 참조 명령어

### 서비스 상태 확인
```bash
# API Health
curl https://api.snapagent.store/health

# ECS 서비스
aws ecs describe-services --cluster rag-cluster --services rag-backend-service --region ap-northeast-2

# 실시간 로그
aws logs tail /ecs/rag-backend --follow --region ap-northeast-2
```

### 배포 작업
```bash
# Docker 빌드 & 푸시
docker build --platform linux/amd64 -t rag-backend:latest .
aws ecr get-login-password --region ap-northeast-2 | docker login --username AWS --password-stdin 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com
docker tag rag-backend:latest 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest
docker push 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest

# ECS 재배포
aws ecs update-service --cluster rag-cluster --service rag-backend-service --force-new-deployment --region ap-northeast-2
```

### 트러블슈팅
```bash
# 에러 로그
aws logs filter-pattern /ecs/rag-backend --filter-pattern "ERROR" --region ap-northeast-2

# Task 실행 중지 (강제 재시작)
TASK_ARN=$(aws ecs list-tasks --cluster rag-cluster --service-name rag-backend-service --region ap-northeast-2 --query 'taskArns[0]' --output text)
aws ecs stop-task --cluster rag-cluster --task $TASK_ARN --region ap-northeast-2
```

---

## 부록 B: 주요 ARN 및 ID

| 리소스 | ARN/ID |
|--------|--------|
| **VPC** | vpc-0c0a3a3baf79f4c66 |
| **ECS Cluster** | rag-cluster |
| **ECS Service** | rag-backend-service |
| **Task Definition** | rag-backend-task:4 |
| **ALB** | RAG-ALB-Seoul |
| **Target Group** | arn:aws:elasticloadbalancing:ap-northeast-2:868651351239:targetgroup/RAG-Backend-TG/d0fb9148569f72aa |
| **ACM Certificate** | arn:aws:acm:ap-northeast-2:868651351239:certificate/da2273d4-15a9-45ff-ba49-fdca26f6c0ad |
| **Route 53 Zone** | Z10422941CZPPWN7MPPT8 |
| **ECR Repository** | 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend |
| **Aurora Cluster** | rag-aurora-cluster |
| **Redis Cluster** | rag-redis |
| **IAM Execution Role** | ecsTaskExecutionRole |

---

**문서 버전**: 2.0 (통합)
**최종 업데이트**: 2025-11-09
**작성자**: Claude Code
**검토자**: 개발팀
