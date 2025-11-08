-- pgvector 확장 활성화 스크립트
-- Aurora PostgreSQL 15.12 이상에서 실행 가능

-- pgvector 확장 활성화
CREATE EXTENSION IF NOT EXISTS vector;

-- 설치 확인
SELECT * FROM pg_extension WHERE extname = 'vector';

-- 버전 확인
SELECT extversion FROM pg_extension WHERE extname = 'vector';

-- 사용 가능한 pgvector 연산자 확인
\dx+ vector

-- 테스트: 간단한 벡터 생성 및 검색
-- (이 부분은 실제 테이블이 생성된 후 실행 가능)
-- SELECT embedding <=> '[0.1, 0.2, 0.3, ...]' AS distance
-- FROM document_embeddings
-- WHERE bot_id = 1
-- ORDER BY distance
-- LIMIT 5;
