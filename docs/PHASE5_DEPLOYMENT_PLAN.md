# Phase 5 배포 계획서

**작성일**: 2025-01-13
**대상 환경**: AWS ECS Fargate (ap-northeast-2)
**도메인**: https://api.snapagent.store

---

## 📋 목차

1. [Git 커밋 전략](#git-커밋-전략)
2. [배포 전 체크리스트](#배포-전-체크리스트)
3. [배포 프로세스](#배포-프로세스)
4. [배포 후 검증](#배포-후-검증)
5. [롤백 계획](#롤백-계획)
6. [모니터링 대시보드](#모니터링-대시보드)

---

## Git 커밋 전략

### 권장 커밋 메시지

```bash
feat: 워크플로우 V2 시스템 구현 완료 (Phase 1-5)

워크플로우 V2 포트 기반 시스템의 전체 Phase를 완료했습니다.

Phase 1: 스키마 & DB
- 포트 시스템 (PortDefinition, NodePortSchema) 추가
- 변수 선택자 (ValueSelector, VariableMapping) 추가
- WorkflowNode/Edge에 V2 필드 추가 (ports, source_port, target_port)
- 워크플로우 버전 관리 테이블 생성 (bot_workflow_versions)
- 실행 기록 테이블 생성 (workflow_execution_runs, workflow_node_executions)

Phase 2: 변수 시스템
- VariablePool 클래스 구현 (포트별 데이터 관리)
- ServiceContainer 클래스 구현 (의존성 주입)
- BaseNodeV2 인터페이스 생성
- V2 노드 구현 (StartNodeV2, KnowledgeNodeV2, LLMNodeV2, EndNodeV2)
- NodeAdapter 구현 (V1-V2 하위 호환성)

Phase 3: 실행 엔진
- WorkflowExecutorV2 구현 (포트 기반 데이터 흐름)
- NodeRegistryV2 구현 (V2 노드 관리)
- ChatService V1/V2 분기 처리
- 실행 기록 DB 저장 기능

Phase 4: API
- 워크플로우 버전 관리 API (draft 생성/발행)
- 실행 기록 API (목록/상세/통계)
- WorkflowVersionService/ExecutionService 구현

Phase 5: 마이그레이션 & 배포
- 마이그레이션 스크립트 (migrate_workflows_to_v2.py)
- 테스트 스크립트 (test_migration.py)
- 운영 가이드 (MIGRATION_GUIDE.md)
- 배포 계획서 (PHASE5_DEPLOYMENT_PLAN.md)

Breaking Changes:
- 없음 (하위 호환성 유지)

Migration:
- 기존 워크플로우는 legacy_workflow에 백업
- V2 전환은 수동 활성화 (use_workflow_v2 플래그)


```

### 개별 파일 커밋 (선택사항)

대규모 변경이므로 단일 커밋 권장하지만, 필요시 분리 가능:

```bash
# Phase 5 파일들만 커밋
git add scripts/migrate_workflows_to_v2.py
git add scripts/test_migration.py
git add docs/MIGRATION_GUIDE.md
git add docs/PHASE5_DEPLOYMENT_PLAN.md
git add workflow_v2_refactoring_plan.md

git commit -m "feat: Phase 5 마이그레이션 스크립트 및 배포 계획 추가

- V1→V2 마이그레이션 스크립트 (migrate_workflows_to_v2.py)
- 마이그레이션 테스트 스크립트 (test_migration.py)
- 운영 가이드 문서 (MIGRATION_GUIDE.md)
- 배포 계획서 (PHASE5_DEPLOYMENT_PLAN.md)


```

---

## 배포 전 체크리스트

### 1. 코드 검증

- [ ] **테스트 스크립트 실행**
  ```bash
  cd Backend
  python scripts/test_migration.py
  ```
  - 모든 테스트 통과 확인

- [ ] **마이그레이션 Dry-run**
  ```bash
  python scripts/migrate_workflows_to_v2.py --dry-run --verbose
  ```
  - 변환 로직 정상 작동 확인
  - 에러 없이 완료 확인

- [ ] **로컬 서버 테스트**
  ```bash
  # 로컬에서 서버 실행
  uvicorn app.main:app --reload

  # API 문서 확인
  open http://localhost:8000/docs
  ```
  - 새로운 API 엔드포인트 확인
  - 기존 API 정상 작동 확인

### 2. 데이터베이스 준비

- [ ] **프로덕션 DB 백업**
  ```bash
  # RDS 스냅샷 생성
  aws rds create-db-snapshot \
    --db-instance-identifier rag-db-instance \
    --db-snapshot-identifier rag-db-backup-$(date +%Y%m%d-%H%M%S) \
    --region ap-northeast-2
  ```

- [ ] **Alembic 마이그레이션 확인**
  ```bash
  # 현재 마이그레이션 상태 확인
  alembic current

  # 적용할 마이그레이션 확인
  alembic history
  ```

  **⚠️ 중요**: Phase 5는 DB 마이그레이션이 **없습니다** (Phase 1에서 완료)
  - 기존 테이블: `bot_workflow_versions`, `workflow_execution_runs`, `workflow_node_executions`
  - 이미 프로덕션에 적용되어 있어야 함

- [ ] **테이블 존재 여부 확인**
  ```sql
  -- 프로덕션 DB에서 확인
  \dt bot_workflow_versions
  \dt workflow_execution_runs
  \dt workflow_node_executions
  ```

### 3. 환경 변수 확인

- [ ] **Secrets Manager 확인**
  ```bash
  # Secrets 조회
  aws secretsmanager get-secret-value \
    --secret-id rag-backend-secrets \
    --region ap-northeast-2 \
    --query SecretString --output text | jq .
  ```

- [ ] **필요한 환경 변수**
  - `DATABASE_URL`: PostgreSQL 연결 문자열
  - `ANTHROPIC_API_KEY`: Claude API 키
  - `AWS_BEDROCK_REGION`: Bedrock 리전
  - 기타 기존 환경 변수들

### 4. 의존성 확인

- [ ] **requirements.txt 변경 없음**
  - Phase 5는 새로운 의존성 추가 없음
  - 기존 의존성만 사용

---

## 배포 프로세스

### Step 1: Git Push

```bash
cd Backend

# 현재 브랜치 확인
git branch

# 커밋 (위의 추천 메시지 사용)
git add .
git commit -m "feat: 워크플로우 V2 시스템 구현 완료 (Phase 1-5)
(... 전체 메시지 ...)
"

# 리모트 푸시
git push origin main
```

### Step 2: Docker 이미지 빌드

```bash
cd Backend

# ⚠️ 플랫폼 명시 필수! (M1/M2 Mac 사용자)
docker build --platform linux/amd64 -t rag-backend:phase5 .

# 이미지 확인
docker images | grep rag-backend
```

**주의사항**:
- M1/M2 Mac에서는 반드시 `--platform linux/amd64` 사용
- ECS Fargate는 x86_64 아키텍처만 지원

### Step 3: ECR 푸시

```bash
# ECR 로그인
aws ecr get-login-password --region ap-northeast-2 | \
  docker login --username AWS --password-stdin \
  868651351239.dkr.ecr.ap-northeast-2.amazonaws.com

# 이미지 태그
docker tag rag-backend:phase5 \
  868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest

docker tag rag-backend:phase5 \
  868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:phase5

# 푸시 (latest와 phase5 태그 모두)
docker push 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest
docker push 868651351239.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:phase5
```

**Tip**: `phase5` 태그는 롤백용으로 보관

### Step 4: ECS 배포

```bash
# ECS 서비스 재배포
aws ecs update-service \
  --cluster rag-cluster \
  --service rag-backend-service \
  --force-new-deployment \
  --region ap-northeast-2

# 배포 상태 모니터링
watch -n 5 'aws ecs describe-services \
  --cluster rag-cluster \
  --services rag-backend-service \
  --region ap-northeast-2 \
  --query "services[0].[deployments[0].rolloutState,runningCount,desiredCount]" \
  --output table'
```

**예상 시간**: 2-3분

### Step 5: 헬스 체크

```bash
# Health 엔드포인트 확인
curl https://api.snapagent.store/health

# API 문서 확인
curl https://api.snapagent.store/docs

# 새로운 API 엔드포인트 테스트
curl -X GET "https://api.snapagent.store/api/v1/bots/{bot_id}/workflow-versions" \
     -H "Authorization: Bearer <token>"
```

### Step 6: 로그 확인

```bash
# 실시간 로그 모니터링
aws logs tail /ecs/rag-backend --follow --region ap-northeast-2

# 또는 필터링
aws logs tail /ecs/rag-backend --follow --region ap-northeast-2 \
  --filter-pattern "ERROR"
```

**확인 사항**:
- 시작 로그에 에러 없는지
- WorkflowExecutorV2 로딩 성공
- API 엔드포인트 등록 확인

---

## 배포 후 검증

### 1. API 기능 테스트

#### 기존 API (V1) 정상 작동 확인

```bash
# 챗봇 대화 테스트 (V1 워크플로우)
curl -X POST "https://api.snapagent.store/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "bot_id": "<bot_id>",
    "message": "테스트 질문입니다",
    "session_id": "test_session"
  }'
```

**예상 결과**: 정상 응답

#### 새로운 API (V2) 테스트

```bash
# 1. 워크플로우 버전 목록 조회
curl -X GET "https://api.snapagent.store/api/v1/bots/<bot_id>/workflow-versions" \
  -H "Authorization: Bearer <token>"

# 2. 실행 기록 조회
curl -X GET "https://api.snapagent.store/api/v1/bots/<bot_id>/workflow-executions?limit=10" \
  -H "Authorization: Bearer <token>"

# 3. 실행 통계 조회
curl -X GET "https://api.snapagent.store/api/v1/bots/<bot_id>/workflow-executions/statistics" \
  -H "Authorization: Bearer <token>"
```

**예상 결과**: 정상 응답 (빈 배열일 수 있음)

### 2. 마이그레이션 기능 검증

**⚠️ 프로덕션에서 바로 실행하지 말 것!**

먼저 Staging 또는 개발 환경에서 테스트:

```bash
# Staging 환경 접속 후
python scripts/migrate_workflows_to_v2.py --dry-run --limit 1 --verbose
```

**검증 항목**:
- [ ] 스크립트 정상 실행
- [ ] 변환 로직 에러 없음
- [ ] Draft 버전 생성 확인

### 3. 성능 체크

```bash
# V1 워크플로우 응답 시간 측정
time curl -X POST "https://api.snapagent.store/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"bot_id": "<bot_id>", "message": "test", "session_id": "perf_test"}'
```

**목표**: 기존과 동일한 성능 유지

### 4. 모니터링 지표 확인

CloudWatch에서 다음 지표 확인:

- **CPU 사용률**: 평상시 수준 유지
- **메모리 사용률**: 평상시 수준 유지
- **에러 로그**: 새로운 에러 없음
- **응답 시간**: 평상시 수준 유지

---

## 롤백 계획

### 문제 발생 시 즉시 롤백

#### 방법 1: 이전 Docker 이미지로 복구

```bash
# 1. 이전 이미지 찾기
aws ecr describe-images \
  --repository-name rag-backend \
  --region ap-northeast-2 \
  --query 'sort_by(imageDetails,& imagePushedAt)[-5:]' \
  --output table

# 2. Task Definition에서 이미지 변경
aws ecs describe-task-definition \
  --task-definition rag-backend-task \
  --region ap-northeast-2 > current-task.json

# current-task.json 편집 (이미지 태그 변경)
# ...

# 3. 새로운 Task Definition 등록
aws ecs register-task-definition --cli-input-json file://rollback-task.json

# 4. 서비스 업데이트
aws ecs update-service \
  --cluster rag-cluster \
  --service rag-backend-service \
  --task-definition rag-backend-task:PREVIOUS_VERSION \
  --force-new-deployment \
  --region ap-northeast-2
```

#### 방법 2: Git 리버트

```bash
# 1. 문제가 있는 커밋 찾기
git log --oneline -5

# 2. 리버트
git revert <commit-hash>

# 3. 재배포
# (Step 2-6 반복)
```

#### 방법 3: DB 롤백 (극단적 상황)

```bash
# RDS 스냅샷에서 복구
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier rag-db-instance-rollback \
  --db-snapshot-identifier rag-db-backup-<timestamp> \
  --region ap-northeast-2
```

**⚠️ 주의**: Phase 5는 DB 변경이 없으므로 DB 롤백은 불필요

### 롤백 판단 기준

다음 상황에서 즉시 롤백:

- [ ] **치명적 에러**: 서비스 전체가 다운됨
- [ ] **API 장애**: 기존 API가 작동하지 않음
- [ ] **성능 저하**: 응답 시간이 2배 이상 증가
- [ ] **데이터 손실**: 사용자 데이터가 손실됨

다음 상황은 롤백 불필요:

- [ ] **새로운 API만 에러**: 기존 기능은 정상
- [ ] **경미한 성능 저하**: 10% 미만
- [ ] **로그 경고**: 기능에 영향 없음

---

## 모니터링 대시보드

### CloudWatch 대시보드 생성

```bash
# 대시보드 JSON 생성
cat > phase5-dashboard.json <<'EOF'
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/ECS", "CPUUtilization", {"stat": "Average"}],
          [".", "MemoryUtilization", {"stat": "Average"}]
        ],
        "period": 300,
        "region": "ap-northeast-2",
        "title": "ECS 리소스 사용률"
      }
    },
    {
      "type": "log",
      "properties": {
        "query": "SOURCE '/ecs/rag-backend' | fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 20",
        "region": "ap-northeast-2",
        "title": "최근 에러 로그"
      }
    },
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/ApplicationELB", "TargetResponseTime", {"stat": "Average"}],
          [".", "RequestCount", {"stat": "Sum"}]
        ],
        "period": 300,
        "region": "ap-northeast-2",
        "title": "API 응답 시간 및 요청 수"
      }
    }
  ]
}
EOF

# 대시보드 생성
aws cloudwatch put-dashboard \
  --dashboard-name "RAG-Backend-Phase5" \
  --dashboard-body file://phase5-dashboard.json \
  --region ap-northeast-2
```

### 주요 모니터링 지표

| 지표 | 정상 범위 | 경고 임계값 | 위험 임계값 |
|------|----------|-----------|-----------|
| CPU 사용률 | 10-30% | 50% | 70% |
| 메모리 사용률 | 30-50% | 70% | 85% |
| 응답 시간 | 200-500ms | 1s | 2s |
| 에러율 | 0-0.1% | 1% | 5% |

### 알람 설정

```bash
# 고 CPU 사용률 알람
aws cloudwatch put-metric-alarm \
  --alarm-name rag-backend-high-cpu \
  --alarm-description "ECS CPU 사용률이 70% 초과" \
  --metric-name CPUUtilization \
  --namespace AWS/ECS \
  --statistic Average \
  --period 300 \
  --threshold 70 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2 \
  --region ap-northeast-2

# 에러 로그 알람
aws cloudwatch put-metric-alarm \
  --alarm-name rag-backend-errors \
  --alarm-description "1분간 에러 로그 10건 초과" \
  --metric-name ErrorCount \
  --namespace RAGBackend \
  --statistic Sum \
  --period 60 \
  --threshold 10 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1 \
  --region ap-northeast-2
```

---

## 배포 후 마일스톤

### 즉시 (배포 후 1시간)

- [ ] 헬스 체크 통과
- [ ] 기존 API 정상 작동
- [ ] 새로운 API 엔드포인트 접근 가능
- [ ] 에러 로그 없음

### 1일 후

- [ ] 안정적인 운영 (재시작 없음)
- [ ] 성능 지표 정상
- [ ] 사용자 불만 없음

### 1주일 후

- [ ] Staging 환경에서 마이그레이션 테스트
- [ ] 소규모 봇 (5-10개) 마이그레이션
- [ ] V2 워크플로우 실행 검증

### 1개월 후

- [ ] 점진적 마이그레이션 시작 (10% → 50% → 100%)
- [ ] V2 실행 성공률 > 99%
- [ ] 전체 시스템 안정화

---

## 긴급 연락망

| 역할 | 담당자 | 연락처 |
|------|-------|--------|
| 백엔드 개발 | [이름] | [연락처] |
| DevOps | [이름] | [연락처] |
| 프로덕트 | [이름] | [연락처] |

**Slack 채널**: #workflow-v2-deployment

---

## 참고 문서

- **마이그레이션 가이드**: `docs/MIGRATION_GUIDE.md`
- **리팩토링 계획**: `workflow_v2_refactoring_plan.md`
- **AWS 배포 가이드**: `AWS_배포_종합_가이드.md`
- **API 문서**: https://api.snapagent.store/docs

---

**작성자**: AI Assistant (Claude Code)
**검토자**: [담당자 이름]
**승인일**: [승인 날짜]
