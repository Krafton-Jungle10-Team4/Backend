-- pgvector 확장 자동 활성화 스크립트
-- Docker 컨테이너 시작 시 자동으로 실행됨

-- pgvector 확장 활성화
CREATE EXTENSION IF NOT EXISTS vector;

-- 확인 메시지
DO $$
BEGIN
  RAISE NOTICE '✅ pgvector extension enabled successfully';
END $$;
