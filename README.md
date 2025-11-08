# RAG Platform - Backend

FastAPI 기반 RAG(Retrieval-Augmented Generation) 플랫폼 백엔드

## 주요 기능

- **문서 업로드 및 처리**: PDF, DOCX, TXT 파일 지원
- **임베딩**: AWS Bedrock Titan Embeddings (1024차원)
- **벡터 검색**: ChromaDB 기반 유사도 검색
- **LLM 통합**: OpenAI, Anthropic Claude 지원
- **사용자 인증**: JWT 기반 인증 + Google OAuth
- **API 문서**: FastAPI 자동 생성 (Swagger UI)

## 기술 스택

- **웹 프레임워크**: FastAPI 0.109.0
- **임베딩**: AWS Bedrock Titan Embeddings v2
- **벡터 DB**: ChromaDB 0.5.3
- **데이터베이스**: PostgreSQL + SQLAlchemy
- **캐시**: Redis
- **LLM**: OpenAI, Anthropic Claude

## 빠른 시작

### 1. 환경 변수 설정

```bash
cp .env.local.example .env.local
```

필수 환경 변수:
```bash
# AWS Bedrock (임베딩)
AWS_REGION=ap-northeast-2
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret

# 데이터베이스
DATABASE_URL=postgresql://user:password@localhost:5432/ragdb

# LLM
OPENAI_API_KEY=sk-...
# 또는
ANTHROPIC_API_KEY=sk-ant-...
```

### 2. 패키지 설치

```bash
pip install -r requirements.txt
```

### 3. 서버 실행

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. API 문서 확인

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## AWS Bedrock 설정

임베딩에 AWS Bedrock Titan Embeddings를 사용합니다.

### 설정 가이드
자세한 내용은 [aws/docs/BEDROCK_SETUP_GUIDE.md](aws/docs/BEDROCK_SETUP_GUIDE.md) 참고

### 테스트
```bash
python scripts/test_bedrock_connection.py
```

## 개발 환경

### Docker Compose
```bash
docker-compose up -d
```

서비스:
- Backend API: http://localhost:8001
- PostgreSQL: localhost:5432
- ChromaDB: http://localhost:8001
- Redis: localhost:6379

### 마이그레이션

```bash
# 마이그레이션 생성
alembic revision --autogenerate -m "description"

# 마이그레이션 적용
alembic upgrade head
```

## 프로젝트 구조

```
Backend/
├── app/
│   ├── core/           # 핵심 기능 (임베딩, 설정)
│   ├── api/            # API 엔드포인트
│   ├── models/         # DB 모델
│   ├── services/       # 비즈니스 로직
│   └── main.py         # 애플리케이션 진입점
├── scripts/            # 유틸리티 스크립트
├── aws/                # AWS 관련 문서 및 스크립트
├── requirements.txt    # Python 의존성
└── docker-compose.yml  # Docker 설정
```

## 브랜치 전략

- `main`: 프로덕션
- `develop`: 개발 통합
- `feature/*`: 기능 개발
- `bugfix/*`: 버그 수정
- `hotfix/*`: 긴급 수정

## 성능 최적화

### 임베딩 성능
- **이전**: CPU 기반 로컬 모델 (느림)
- **현재**: AWS Bedrock API (2-5배 빠름)
- **비용**: 월 $0.10 미만

### 권장 설정
- 배치 크기: 16 (config.py)
- 벡터 차원: 1024
- 정규화: 활성화

## 트러블슈팅

### Bedrock 연결 오류
```bash
# 1. AWS credentials 확인
aws sts get-caller-identity

# 2. Model access 확인
aws bedrock list-foundation-models --region ap-northeast-2
```

### ChromaDB 연결 오류
```bash
# Docker 컨테이너 상태 확인
docker-compose ps

# 로그 확인
docker-compose logs chromadb
```

## 라이선스

MIT License
