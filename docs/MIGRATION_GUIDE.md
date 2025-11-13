# 워크플로우 V2 마이그레이션 가이드

이 문서는 기존 워크플로우를 V2 시스템으로 마이그레이션하는 방법을 설명합니다.

## 목차

1. [개요](#개요)
2. [사전 준비](#사전-준비)
3. [마이그레이션 절차](#마이그레이션-절차)
4. [검증 및 테스트](#검증-및-테스트)
5. [롤백 절차](#롤백-절차)
6. [트러블슈팅](#트러블슈팅)
7. [FAQ](#faq)

---

## 개요

### 왜 V2로 마이그레이션해야 하나요?

워크플로우 V2는 다음과 같은 개선사항을 제공합니다:

- **포트 기반 데이터 흐름**: 명시적인 입출력 포트로 타입 안전성 강화
- **변수 시스템**: 노드 간 데이터 전달이 명확하고 추적 가능
- **버전 관리**: Draft/Published 버전 관리 및 이력 추적
- **실행 기록**: 상세한 실행 로그 및 디버깅 지원
- **확장성**: 조건 분기, 루프, 병렬 실행 등 고급 기능 준비

### 마이그레이션 영향

- **하위 호환성**: 기존 워크플로우는 계속 작동합니다
- **데이터 안전성**: 기존 워크플로우는 `legacy_workflow` 필드에 백업됩니다
- **수동 활성화**: V2로 전환은 검증 후 수동으로 활성화합니다

---

## 사전 준비

### 1. 백업

마이그레이션 전에 반드시 데이터베이스를 백업하세요:

```bash
# PostgreSQL 백업
pg_dump -h <host> -U <user> -d <database> -f backup_$(date +%Y%m%d_%H%M%S).sql

# 또는 전체 클러스터 백업
pg_dumpall -h <host> -U <user> -f backup_all_$(date +%Y%m%d_%H%M%S).sql
```

### 2. 환경 확인

필요한 테이블이 생성되어 있는지 확인:

```bash
# Alembic 마이그레이션 적용
cd Backend
alembic upgrade head
```

확인할 테이블:
- `bot_workflow_versions`
- `workflow_execution_runs`
- `workflow_node_executions`

### 3. 테스트 스크립트 실행

마이그레이션 스크립트가 정상 작동하는지 테스트:

```bash
python scripts/test_migration.py
```

모든 테스트가 통과해야 합니다.

---

## 마이그레이션 절차

### 1단계: Dry Run (시뮬레이션)

실제 변경 없이 마이그레이션을 시뮬레이션합니다:

```bash
# 전체 봇 시뮬레이션
python scripts/migrate_workflows_to_v2.py --dry-run --verbose

# 특정 봇만 시뮬레이션
python scripts/migrate_workflows_to_v2.py --dry-run --bot-id <bot_id> --verbose
```

**출력 예시:**
```
============================================================
워크플로우 V1 → V2 마이그레이션
============================================================
⚠️  DRY RUN 모드: 실제 변경 없이 시뮬레이션만 수행합니다

📋 총 10개 봇 마이그레이션 시작...

[1/10] 봇 처리 중...
  ✅ 봇 abc-123: 변환 성공 (dry run)
     노드 수: 4, 엣지 수: 3

[2/10] 봇 처리 중...
  ⏭️  봇 def-456: 워크플로우 없음, 스킵
...
```

### 2단계: 소규모 마이그레이션

먼저 몇 개의 봇만 마이그레이션하여 검증:

```bash
# 최대 5개 봇만 마이그레이션
python scripts/migrate_workflows_to_v2.py --limit 5 --verbose
```

### 3단계: 변환 결과 검증

마이그레이션된 봇의 draft 버전을 확인:

```bash
# API를 통해 확인
curl -X GET "http://localhost:8000/api/v1/bots/<bot_id>/workflow-versions" \
     -H "Authorization: Bearer <token>"
```

또는 데이터베이스에서 직접 확인:

```sql
-- Draft 버전 조회
SELECT
    bot_id,
    version,
    status,
    created_at,
    jsonb_array_length(graph->'nodes') as node_count,
    jsonb_array_length(graph->'edges') as edge_count
FROM bot_workflow_versions
WHERE status = 'draft'
ORDER BY created_at DESC;

-- 특정 봇의 draft 그래프 확인
SELECT graph
FROM bot_workflow_versions
WHERE bot_id = '<bot_id>' AND status = 'draft';
```

### 4단계: 테스트 실행

변환된 워크플로우를 테스트 환경에서 실행:

1. **UI에서 Draft 확인**:
   - 봇 설정 > 워크플로우 > Draft 버전 선택
   - 노드와 엣지 연결 확인
   - 포트 매핑 확인

2. **테스트 메시지 전송**:
   ```bash
   curl -X POST "http://localhost:8000/api/v1/chat/test" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer <token>" \
        -d '{
          "bot_id": "<bot_id>",
          "message": "테스트 질문입니다",
          "session_id": "test_session"
        }'
   ```

3. **실행 기록 확인**:
   ```bash
   curl -X GET "http://localhost:8000/api/v1/bots/<bot_id>/workflow-executions?limit=10" \
        -H "Authorization: Bearer <token>"
   ```

### 5단계: Draft 발행

테스트가 성공하면 draft를 발행:

```bash
curl -X POST "http://localhost:8000/api/v1/bots/<bot_id>/workflow-versions/<version_id>/publish" \
     -H "Authorization: Bearer <token>"
```

발행하면:
- Draft가 `v1.0` 버전으로 변경됨
- 봇의 `use_workflow_v2` 플래그가 자동으로 활성화됨
- 새로운 빈 draft가 생성됨

### 6단계: 전체 마이그레이션

소규모 테스트가 성공하면 전체 봇 마이그레이션:

```bash
# 전체 봇 마이그레이션 (한 번에 100개씩 권장)
python scripts/migrate_workflows_to_v2.py --limit 100 --verbose

# 나머지 봇 마이그레이션
python scripts/migrate_workflows_to_v2.py --verbose
```

### 7단계: 모니터링

마이그레이션 후 모니터링:

```sql
-- 마이그레이션 현황
SELECT
    COUNT(*) as total_bots,
    SUM(CASE WHEN use_workflow_v2 THEN 1 ELSE 0 END) as v2_bots,
    SUM(CASE WHEN legacy_workflow IS NOT NULL THEN 1 ELSE 0 END) as migrated_bots
FROM bots
WHERE workflow IS NOT NULL;

-- V2 실행 성공률
SELECT
    status,
    COUNT(*) as count,
    ROUND(AVG(elapsed_time)) as avg_time_ms,
    ROUND(AVG(total_tokens)) as avg_tokens
FROM workflow_execution_runs
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY status;
```

---

## 검증 및 테스트

### 자동화 테스트

테스트 스크립트로 변환 로직 검증:

```bash
python scripts/test_migration.py
```

### 수동 검증 체크리스트

각 마이그레이션된 봇에 대해 확인:

- [ ] Draft 버전이 생성되었는가?
- [ ] 모든 노드에 포트가 정의되었는가?
- [ ] 모든 엣지에 source_port, target_port가 있는가?
- [ ] 입력이 있는 노드에 variable_mappings가 있는가?
- [ ] 테스트 메시지 실행이 성공하는가?
- [ ] 실행 기록이 정상적으로 저장되는가?

### 성능 테스트

V1과 V2의 성능 비교:

```bash
# V1 실행 (use_workflow_v2=false)
time curl -X POST "http://localhost:8000/api/v1/chat/test" \
     -H "Content-Type: application/json" \
     -d '{"bot_id": "<bot_id>", "message": "test", "session_id": "test1"}'

# V2 실행 (use_workflow_v2=true)
time curl -X POST "http://localhost:8000/api/v1/chat/test" \
     -H "Content-Type: application/json" \
     -d '{"bot_id": "<bot_id>", "message": "test", "session_id": "test2"}'
```

**목표**: V2 오버헤드 < 500ms

---

## 롤백 절차

문제 발생 시 V1로 롤백하는 방법입니다.

### 방법 1: 봇별 롤백 (권장)

특정 봇만 V1으로 복구:

```sql
-- 봇의 V2 비활성화
UPDATE bots
SET use_workflow_v2 = FALSE
WHERE bot_id = '<bot_id>';
```

기존 워크플로우는 `legacy_workflow` 필드에 백업되어 있으므로 즉시 V1로 복구됩니다.

### 방법 2: 전체 롤백

모든 봇을 V1으로 복구:

```sql
-- 모든 봇의 V2 비활성화
UPDATE bots
SET use_workflow_v2 = FALSE
WHERE use_workflow_v2 = TRUE;
```

### 방법 3: 데이터베이스 복구

심각한 문제 발생 시 백업에서 복구:

```bash
# PostgreSQL 복구
psql -h <host> -U <user> -d <database> -f backup_<timestamp>.sql
```

**주의**: 복구 시점 이후의 모든 데이터가 손실됩니다.

---

## 트러블슈팅

### 문제 1: 마이그레이션 스크립트 실행 오류

**증상:**
```
ImportError: cannot import name 'SessionLocal' from 'app.core.database'
```

**해결:**
```bash
# 프로젝트 루트에서 실행했는지 확인
cd Backend

# PYTHONPATH 설정
export PYTHONPATH=$PYTHONPATH:$(pwd)

# 다시 실행
python scripts/migrate_workflows_to_v2.py --dry-run
```

### 문제 2: Draft 생성 실패

**증상:**
```
sqlalchemy.exc.IntegrityError: duplicate key value violates unique constraint
```

**원인**: 이미 draft가 존재함

**해결:**
```sql
-- 기존 draft 확인
SELECT * FROM bot_workflow_versions
WHERE bot_id = '<bot_id>' AND status = 'draft';

-- 기존 draft 삭제 (신중하게!)
DELETE FROM bot_workflow_versions
WHERE bot_id = '<bot_id>' AND status = 'draft';

-- 다시 마이그레이션 실행
python scripts/migrate_workflows_to_v2.py --bot-id <bot_id>
```

### 문제 3: V2 실행 실패

**증상:**
```
ValueError: vector_service not found in service container
```

**해결:**
1. **ServiceContainer 확인**:
   ```python
   # app/services/chat_service.py에서
   services = ServiceContainer(
       vector_service=self.vector_service,  # 확인
       llm_service=self.llm_service,        # 확인
       db_session=self.db,                  # 확인
       bot_id=bot.bot_id                    # 추가 필요할 수 있음
   )
   ```

2. **로그 확인**:
   ```bash
   # 실행 로그 확인
   tail -f logs/app.log | grep "WorkflowExecutorV2"
   ```

### 문제 4: 포트 연결 오류

**증상:**
```
KeyError: "노드 knowledge_1가 아직 실행되지 않았습니다"
```

**원인**: 노드 실행 순서 문제 또는 포트 매핑 오류

**해결:**
1. **그래프 검증**:
   ```sql
   -- 순환 참조 확인
   SELECT graph FROM bot_workflow_versions
   WHERE bot_id = '<bot_id>' AND status = 'draft';
   ```

2. **variable_mappings 확인**:
   - 모든 입력 포트가 올바른 소스에 매핑되어 있는지 확인
   - 소스 노드가 타겟 노드보다 먼저 실행되는지 확인

3. **수동 수정**:
   ```bash
   # UI에서 워크플로우 편집
   # 또는 API로 graph 수정
   curl -X POST "http://localhost:8000/api/v1/bots/<bot_id>/workflow-versions/draft" \
        -H "Content-Type: application/json" \
        -d @fixed_graph.json
   ```

### 문제 5: 성능 저하

**증상**: V2 실행이 V1보다 현저히 느림

**해결:**
1. **실행 기록 확인**:
   ```sql
   SELECT
       node_id,
       node_type,
       elapsed_time,
       status
   FROM workflow_node_executions
   WHERE workflow_run_id = '<run_id>'
   ORDER BY execution_order;
   ```

2. **병목 노드 식별** 및 최적화

3. **DB 인덱스 확인**:
   ```sql
   -- 필요한 인덱스 추가
   CREATE INDEX IF NOT EXISTS idx_node_exec_run_id
   ON workflow_node_executions(workflow_run_id);
   ```

---

## FAQ

### Q1: 마이그레이션은 필수인가요?

**A**: 아니요. V1 워크플로우는 계속 지원됩니다. 하지만 새로운 기능(조건 분기, 루프, 병렬 실행 등)은 V2에서만 사용할 수 있습니다.

### Q2: 마이그레이션 중에 서비스가 중단되나요?

**A**: 아니요. 마이그레이션은 draft 버전만 생성하며, 발행하기 전까지 기존 워크플로우가 계속 작동합니다.

### Q3: 부분적으로 마이그레이션할 수 있나요?

**A**: 네. 봇별로 개별적으로 마이그레이션하고 활성화할 수 있습니다.

### Q4: V2로 전환 후 다시 V1으로 돌아갈 수 있나요?

**A**: 네. `use_workflow_v2` 플래그를 `false`로 설정하면 즉시 V1으로 복구됩니다.

### Q5: 커스텀 노드는 어떻게 마이그레이션하나요?

**A**: 커스텀 노드의 경우:
1. `NodeAdapter`를 사용하여 V2 인터페이스로 래핑
2. 또는 `BaseNodeV2`를 상속하여 V2 노드로 재작성
3. `NodeRegistryV2`에 등록

자세한 내용은 개발 문서를 참조하세요.

### Q6: 마이그레이션 스크립트를 수정할 수 있나요?

**A**: 네. 프로젝트별 특수한 요구사항이 있다면 스크립트를 수정할 수 있습니다. 수정 후 반드시 테스트 스크립트로 검증하세요.

### Q7: 실행 기록은 언제 삭제되나요?

**A**: 실행 기록은 자동으로 삭제되지 않습니다. 필요시 `WorkflowExecutionService`의 정리 메서드를 사용하거나 수동으로 삭제하세요:

```sql
-- 30일 이상 된 기록 삭제
DELETE FROM workflow_execution_runs
WHERE created_at < NOW() - INTERVAL '30 days';
```

---

## 추가 리소스

- **개발 문서**: `workflow_v2_refactoring_plan.md`
- **프론트엔드 통합**: `workflow_v2_frontend_backend_flow.md`
- **API 문서**: `http://localhost:8000/docs`
- **이슈 트래킹**: GitHub Issues

---

## 지원

문제가 발생하면:

1. **로그 확인**: `logs/app.log`, `logs/migration.log`
2. **문서 확인**: 이 가이드와 개발 문서
3. **이슈 생성**: 상세한 오류 메시지와 함께 이슈 등록
4. **팀 문의**: Slack #workflow-v2 채널

---

**마지막 업데이트**: 2025-01-13
**버전**: 1.0
