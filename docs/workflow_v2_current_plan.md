# 워크플로우 V2 현재 이식 계획

본 문서는 **Dify 기반 피드백 워크플로우**를 우리 V2 실행 엔진 구조로 이식할 때 필요한 백엔드 변경만을 집중 정리합니다.  
포트/변수 스키마, Validator 제약, Assigner 입력 설계, 대화 상태 관리 등 즉시 구현해야 할 항목만 포함합니다.

---

## 1. 확인된 문제 상황

| 구분 | 상세 | 영향 |
| --- | --- | --- |
| Assigner 입력 누락 | Dify 그래프를 그대로 넣으면서 `operation_0_value` 등 필수 포트 매핑이 빠짐. `assigner_node_v2.py`는 입력이 없으면 즉시 예외를 던짐 | 워크플로우 저장/실행 모두 차단 |
| Answer → End 미연결 | 브랜치마다 Answer 노드를 두거나 End에 연결되지 않아 `validator.py:447-520`의 구조 검증 실패 | Validator 통과 불가 |
| 대화 변수 미정의 | Dify는 대화 변수를 자동 저장하지만, 우리 엔진은 `conv.*` 셀렉터를 직접 정의해야 함. `feedback_stage`, `pending_response`, `latest_summary`, `last_query`, `last_feedback` 등이 없음 | 다음 턴 분기 조건 평가 불가, 피드백 루프 동작 안 함 |

---

## 2. 목표 개요

1. **대화 상태 선 정의**: `conversation_variables` 기본값과 Assigner 작업을 통해 `conv.*` 상태를 명시적으로 관리  
2. **단일 Answer 체인**: 모든 분기에서 `conv.pending_response`를 채우고 단일 Answer → End로 수렴  
3. **Validator 준수**: 모든 포트/엣지/variable_mappings가 채워진 상태로 그래프 저장  
4. **피드백 루프 재현**: 사용자 답변에 따라 Tavily → LLM 체인을 재호출하거나 SNS 변환으로 종료  

---

## 3. Dify 기준 사용자 여정 & 상태 매핑

| 단계 | Dify 워크플로우 동작 | 우리 V2에서의 구현 포인트 |
| --- | --- | --- |
| 1. 최초 질문 수신 | Start → Knowledge/Search → LLM → “요약 + 마음에 드셨나요?” 출력 | StartNodeV2에서 `start-1.query`를 노출하고, Tavily/LLM 체인이 `conv.latest_summary`, `conv.pending_response`, `conv.feedback_stage="wait_feedback"`를 설정 |
| 2. 피드백 입력 | 사용자가 “마음에 듦/안 듦” 등 텍스트를 입력하면 Dify가 같은 런 안에서 분기 | 우리는 **다음 사용자 턴**에서 `conv.feedback_stage` 값을 읽어 IfElse/Classifier 분기. 즉, 상태 머신으로 피드백 루프를 재현 |
| 3.A 불만족 분기 | 즉시 재검색 후 새로운 요약 제안 | Negative 분기는 Tavily → LLM → Assigner 체인을 재실행하면서 `conv.feedback_stage` 유지 |
| 3.B 만족 분기 | SNS 공유용 메시지나 후속 작업 후 종료 | Positive 분기는 SNS LLM → Assigner로 최종 응답 생성 후 `conv.feedback_stage=""` |
| 4. Answer/End | 모든 결과가 Answer 노드 한 개로 모여 End 노드와 연결 | AnswerNodeV2 템플릿을 `{{conv.pending_response}}`로 고정하고 Validator 요구사항 충족 |

### 3.1 상태 전이 모델

```
feedback_stage=""
   │ (첫 질문)
   ▼
wait_feedback
   │ (사용자 피드백 미입력)
   ├─ 사용자 입력=부정 ──> wait_feedback (재검색 루프 유지)
   └─ 사용자 입력=긍정 ──> done (또는 빈 문자열로 초기화)
```

- `pending_response`는 현재 턴에서 사용자에게 보여줄 문장을 항상 가지고 있어야 하므로, 브랜치 진입/탈출 시 즉시 업데이트.
- `last_query`, `last_feedback`은 템플릿이나 후속 노드에서 참조할 수 있도록 최신 값을 보관.
- 이 상태 머신은 **한 번의 실행(run)** 이 아니라 **세션 단위(stateful)** 로 동작함을 명시적으로 문서화해 프론트엔드/백엔드가 동일 인식을 가지도록 한다.

---

## 4. Phase별 실행 계획 (상세)

### Phase 1 – 상태 관리 기반 구축

- Workflow JSON의 `conversation_variables`에 다음 키를 기본값으로 정의  
  `feedback_stage=""`, `pending_response=""`, `latest_summary=""`, `last_query=""`, `last_feedback=""`.
- StartNodeV2 → IfElseNodeV2 구간에서 필요한 `variable_mappings` 설계.  
  - Start 노드 출력 포트: `query`, `session_id` (필요 시)  
  - IfElse 노드 입력 포트: `sys.user_message`, `conv.feedback_stage`, `conv.pending_response` 등  
  - 첫 케이스는 `conv.feedback_stage`가 비어 있는지를 조건으로 사용 (Start → Phase2 브랜치)
- Assigner 노드 operation별 `write_mode`, `input_type`, `constant_value`를 명확히 지정하고  
  `operation_i_target`이 `conv.*` 또는 `start-1.*` 셀렉터를 바라보도록 포트 매핑을 완성.
- **필수 구현 상세**
  1. `operations` 배열에 case별 작업 정의 (예: 0: `conv.latest_summary` overwrite, 1: `conv.pending_response` overwrite, 2: `conv.feedback_stage` set 등)  
  2. `operation_i_value`는 VARIABLE/CONSTANT 여부에 따라 포트 연결 or 상수 지정  
  3. Validator 자동 보정에만 의존하지 말고, 그래프 JSON에 명시적으로 입력

### Phase 2 – 최초 요청 및 재검색 파이프라인

- Case #1 브랜치에 Tavily Search → LLM 요약 체인을 배치.  
  - Tavily `query` ← `start-1.query`  
  - LLM `context` ← Tavily `context` 출력  
  - LLM `query` ← `start-1.query`
- 요약 완료 후 Assigner가 아래 상태를 갱신  
  - `conv.latest_summary` ← LLM 요약  
  - `conv.pending_response` ← “요약 + 마음에 드셨나요?” 문장  
  - `conv.feedback_stage` ← `"wait_feedback"`  
  - `conv.last_query` ← `start-1.query`
- 재검색 브랜치에서도 동일한 LLM 템플릿/Tavily 구성을 재사용하거나 모듈화하여 배선 일관성 확보.
- **포트/매핑 체크리스트**
  - Tavily 노드 입력 `query` → `start-1.query`  
  - Tavily 출력 `context` / `documents` → LLM 입력 `context` / `documents` (필요한 경우)  
  - LLM 출력 `response` → Assigner `operation_0_value` (latest_summary 등에 저장)  
  - Assigner가 `conv.pending_response`를 채운 후 Answer 노드에서 소비할 수 있도록 `conversation_variables` sync

### Phase 3 – 피드백 분류 및 분기

- ELSE 브랜치에 QuestionClassifierNodeV2을 배치하고 class를 “마음에 듦 / 들지 않음”으로 정의.  
  사용자 입력은 `start-1.query` 대신 `start-1.query`와 최신 피드백 텍스트로 구성.
- `class_<id>_branch`를 사용해 두 개의 엣지를 생성:  
  - **Negative 브랜치**: Phase 2의 Tavily → LLM → Assigner 체인을 다시 호출, `conv.feedback_stage` 유지.  
  - **Positive 브랜치**: SNS 변환용 LLM을 실행하고 `conv.feedback_stage`를 `""` 또는 `"done"`으로 초기화.
- 사용자 피드백 메시지를 `conv.last_feedback`에 저장하여 다음 응답에서 참조 가능하게 함.
- **Implementation Tips**
  - Classifier 입력 `text`는 `start-1.query` 대신 `sys.user_message`(가장 최근 유저 발화)와 `conv.pending_response`를 결합한 템플릿으로 구성하여 “이전 제안+답변” 맥락을 포함  
  - Negative 브랜치는 Phase 2 체인을 **하나의 재사용 가능한 Subgraph**처럼 간주하여 포트 복사를 최소화  
  - Positive 브랜치에서는 SNS 변환용 LLM 출력이 곧 `conv.pending_response`가 되므로 Assigner 작업 개수를 줄일 수 있음

### Phase 4 – 응답 수렴 및 Validator 정합성

- 모든 경로에서 `conv.pending_response`가 최종 답변을 가지도록 Assigner 구성.  
- AnswerNodeV2 템플릿을 `{{conv.pending_response}}`로 고정하고 End 노드의 `response` 포트에 연결.  
- Validator 요구사항 충족을 위해 다음을 재검토  
  - Answer → End 엣지가 존재하는지  
  - 모든 필수 포트가 variable_mappings로 채워졌는지  
  - Assigner `operation_i_target/value` 포트와 엣지 `source_port/target_port`가 정확한지
- 필요 시 Validator에 새 제약(예: `feedback_stage` 필수 키) 추가를 검토하되, 우선은 그래프 레벨에서 해결

### Phase 5 – 통합 테스트 및 상태 검증

1. **시나리오 테스트 스크립트**
   - (1) 첫 질문 → 요약 + 피드백 질문  
   - (2) “마음에 안 듦” → 재검색 재실행  
   - (3) “마음에 듦” → SNS 변환 후 종료
   - 각 단계에서 `conversation_variables` 변화 로그 출력
2. **DB 영속성 확인**  
   `conversation_variables` 테이블에 상태가 저장되는지, 세션 재요청 시 IfElse/Classifier 분기가 기대대로 동작하는지 점검.
3. **에러 대비**  
   Tavily/LLM 실패 시 `conv.pending_response`에 대체 응답을 기록하는 fallback Assigner 또는 예외 전달 전략 마련.

---

## 5. 추가 가드레일

- **동일 런 재호출 대비**: 현재 설계는 “다음 사용자 턴”을 전제로 하지만, 향후 동일 런 내 재수행이 필요하면 ExecutorV2가 특정 노드를 재큐잉할 수 있도록 별도 플래그를 고려.  
- **템플릿 안전성**: Answer/SNS LLM 템플릿에서 `conv.*`가 비어 있을 가능성에 대비해 기본값 제공 (`{{ conv.latest_summary | default('요약을 찾지 못했습니다.') }}` 같은 문법 도입 고려).  
- **서비스 실패 핸들링**: Tavily, LLM 호출 실패 시 재시도/대체 메시지 여부를 Assigner fallback으로 명시.  
- **프론트엔드 연계**: ReactFlow/FE 측에서 포트/variable_mappings를 시각적으로 노출, 누락 시 바로 경고가 나가도록 협업.

---

## 6. 참고 파일

- `app/core/workflow/nodes_v2/assigner_node_v2.py` – Assigner 입력/출력 규칙  
- `app/core/workflow/validator.py (447-520)` – Answer → End 및 포트/매핑 검증 로직  
- `app/core/workflow/executor_v2.py` – `conversation_variables` 병합·저장 흐름  
- `Backend/workflow_v2_refactoring_plan.md` – 전체 리팩토링 문서 (장기 계획 포함)

이 문서를 기준으로 백엔드 팀은 즉시 필요한 작업을 수행하고, 추가 요구 사항이 생기면 Phase 계획에 맞춰 업데이트하면 됩니다.
