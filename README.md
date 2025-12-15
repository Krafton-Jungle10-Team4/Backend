# SnapAgent: 노코드 기반 워크플로우 자동화 플랫폼

RAG(Retrieval-Augmented Generation) 기반의 AI Agent 생성 및 워크플로우 자동화 플랫폼입니다.
사용자가 직관적인 인터페이스를 통해 AI Agent를 생성하고, 복잡한 워크플로우를 시각적으로 설계하여 자동화할 수 있습니다.

<img width="451" height="225" alt="image" src="https://github.com/user-attachments/assets/a6cb1b39-8cc6-49dd-acf3-91d61f0598c7" />
<img width="919" height="571" alt="image" src="https://github.com/user-attachments/assets/7654c906-fe57-4f7b-85a1-750b49a39389" />
<img width="1006" height="420" alt="image" src="https://github.com/user-attachments/assets/06a891cd-1781-4411-832c-57194709f763" />
<img width="1285" height="668" alt="image" src="https://github.com/user-attachments/assets/e0ec112b-5c48-47f4-a0c0-a80a0b52a524" />

https://www.youtube.com/watch?v=L-uchJcRnBQ&feature=youtu.be

## 📋 목차

- [주요 기능](#주요-기능)
- [기술 스택](#기술-스택)
- [프로젝트 구조](#프로젝트-구조)
- [시작하기](#시작하기)
- [개발 환경 설정](#개발-환경-설정)
- [배포](#배포)
- [문서](#문서)

---

## ✨ 주요 기능

### 🤖 에이전트 관리
- **직관적인 봇 생성**: 4단계 마법사를 통한 쉬운 봇 생성
- **문서 기반 지식**: PDF, DOCX, TXT 파일 업로드 및 벡터 검색
- **실시간 채팅**: 웹 위젯을 통한 챗봇 대화
- **배포 관리**: API 키 기반 배포 및 사용량 모니터링

### 🔄 워크플로우 자동화
- **시각적 워크플로우 편집기**: 드래그 앤 드롭으로 복잡한 워크플로우 설계
- **다양한 노드 타입**: LLM, 지식 검색, HTTP 요청, Slack 통합, 조건 분기 등
- **실시간 실행**: 워크플로우 실행 상태 및 결과 추적
- **버전 관리**: 워크플로우 버전 관리 및 롤백
- **벡터 검색**: AWS Bedrock Titan Embeddings를 활용한 임베딩
- **다중 LLM 지원**: OpenAI, Anthropic Claude, Google Gemini 등
- **의미 기반 캐싱**: Redis 기반 시맨틱 캐시로 비용 절감
- **Slack 통합**: Slack OAuth를 통한 워크플로우 자동화
- **마켓플레이스**: 공개 워크플로우 템플릿 공유

---

## 🛠 기술 스택

### Backend

| 카테고리 | 기술 |
|---------|------|
| **웹 프레임워크** | FastAPI 0.109.0 |
| **데이터베이스** | PostgreSQL 15+ (pgvector 확장) |
| **캐시** | Redis 7+ |
| **벡터 DB** | ChromaDB 0.5.3 (로컬), pgvector (프로덕션) |
| **임베딩** | AWS Bedrock Titan Embeddings v2 |
| **LLM** | OpenAI, Anthropic Claude, Google Gemini |
| **ORM** | SQLAlchemy 2.0 |
| **마이그레이션** | Alembic 1.13 |
| **인증** | JWT, Google OAuth |
| **기타** | LangChain, Slack SDK, boto3 |

### Frontend

| 카테고리 | 기술 |
|---------|------|
| **프레임워크** | React 19.1 + TypeScript 5.9 |
| **빌드 도구** | Vite 7.1 |
| **스타일링** | TailwindCSS 4.1 |
| **상태 관리** | Zustand 5.0, TanStack Query 5.9 |
| **라우팅** | React Router 7.9 |
| **워크플로우 UI** | React Flow (@xyflow/react) |
| **UI 컴포넌트** | Radix UI |
| **폼 관리** | React Hook Form + Zod |
| **테스팅** | Vitest, Playwright |

### Infrastructure

- **컨테이너**: Docker, Docker Compose
- **클라우드**: AWS (ECS Fargate, RDS, ElastiCache)
- **배포**: GitHub Actions, Vercel (Frontend)

---

## 📁 프로젝트 구조

```
projects/
├── Backend/                 # FastAPI 백엔드 서버
│   ├── app/
│   │   ├── api/            # API 엔드포인트
│   │   ├── core/           # 핵심 기능 (LLM, 임베딩, 워크플로우)
│   │   ├── models/         # 데이터베이스 모델
│   │   ├── services/       # 비즈니스 로직
│   │   └── workers/        # 백그라운드 작업자
│   ├── alembic/            # 데이터베이스 마이그레이션
│   ├── scripts/            # 유틸리티 스크립트
│   ├── aws/                # AWS 관련 설정
│   └── docs/               # 백엔드 문서
│
├── Frontend/               # React 프론트엔드
│   └── my-project/
│       ├── src/
│       │   ├── app/        # 앱 설정 및 라우팅
│       │   ├── features/   # 기능별 모듈
│       │   │   ├── bot/    # 챗봇 관리
│       │   │   ├── workflow/  # 워크플로우 편집기
│       │   │   ├── chat/   # 채팅 인터페이스
│       │   │   └── ...
│       │   └── shared/     # 공통 컴포넌트
│       └── public/         # 정적 파일
│
└── LLM_Production_Programming/  # LLM 프로덕션 프로그래밍 유틸리티
```

---

## 📚 주요 문서

### Backend
- [배포 가이드](Backend/docs/deployment-guide.md)
- [AWS 인프라 가이드](Backend/docs/aws_infrastructure_overview.md)
- [워크플로우 V2 가이드](Backend/docs/workflow_v2_current_plan.md)
- [마이그레이션 가이드](Backend/docs/MIGRATION_GUIDE.md)

### Frontend
- [프로젝트 요약](Frontend/dev_md/Form_PROJECT_SUMMARY.md)
- [개발 프로세스](Frontend/dev_md/Form_WorkProcess.md)
- [Git Flow 전략](Frontend/GitFlow.md)

---

##  배포

### Backend (AWS ECS Fargate)

자세한 배포 가이드는 [AWS 배포 종합 가이드](Backend/AWS_배포_종합_가이드.md)를 참고

### Frontend (Vercel)



## 📊 프로젝트 통계

- **Backend**: ~15,000+ 라인 (Python)
- **Frontend**: ~20,000+ 라인 (TypeScript/TSX)
- **API 엔드포인트**: 50+ 개
- **워크플로우 노드 타입**: 15+ 개
- **데이터베이스 모델**: 15+ 개


