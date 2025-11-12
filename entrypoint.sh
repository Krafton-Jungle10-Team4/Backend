#!/bin/bash
set -e

echo "🚀 Starting application initialization..."

# 1. 데이터베이스 연결 대기
echo "⏳ Waiting for database connection..."
python << EOF
import time
import sys
import os
from sqlalchemy import create_engine, text

# 환경변수에서 직접 DATABASE_URL 가져오기
database_url = os.getenv("DATABASE_URL")
if not database_url:
    # DATABASE_URL이 없으면 개별 환경변수로 구성
    user = os.getenv("DATABASE_USER", os.getenv("POSTGRES_USER", "postgres"))
    password = os.getenv("DATABASE_PASSWORD", os.getenv("POSTGRES_PASSWORD", ""))
    host = os.getenv("DATABASE_HOST", "localhost")
    port = os.getenv("DATABASE_PORT", "5432")
    db = os.getenv("DATABASE_NAME", os.getenv("POSTGRES_DB", "ragdb"))
    database_url = f"postgresql://{user}:{password}@{host}:{port}/{db}"

# +asyncpg가 있으면 제거 (동기 연결용)
database_url = database_url.replace('+asyncpg', '')

print(f"📡 Connecting to: postgresql://***:***@{os.getenv('DATABASE_HOST', 'localhost')}:{os.getenv('DATABASE_PORT', '5432')}/{os.getenv('DATABASE_NAME', 'ragdb')}")

max_retries = 30
retry_interval = 2

for attempt in range(max_retries):
    try:
        engine = create_engine(database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ Database connection successful!")
        sys.exit(0)
    except Exception as e:
        if attempt < max_retries - 1:
            print(f"⏳ Attempt {attempt + 1}/{max_retries} failed, retrying in {retry_interval}s...")
            time.sleep(retry_interval)
        else:
            print(f"❌ Failed to connect to database after {max_retries} attempts: {e}")
            sys.exit(1)
EOF

# 2. 컬럼 이름 수정 (metadata -> doc_metadata)
echo "🔧 Fixing column name if needed..."
python << EOF
import os
from sqlalchemy import create_engine, text, inspect

# 환경변수에서 직접 DATABASE_URL 가져오기
database_url = os.getenv("DATABASE_URL")
if not database_url:
    user = os.getenv("DATABASE_USER", os.getenv("POSTGRES_USER", "postgres"))
    password = os.getenv("DATABASE_PASSWORD", os.getenv("POSTGRES_PASSWORD", ""))
    host = os.getenv("DATABASE_HOST", "localhost")
    port = os.getenv("DATABASE_PORT", "5432")
    db = os.getenv("DATABASE_NAME", os.getenv("POSTGRES_DB", "ragdb"))
    database_url = f"postgresql://{user}:{password}@{host}:{port}/{db}"

database_url = database_url.replace('+asyncpg', '')

try:
    engine = create_engine(database_url)
    with engine.connect() as conn:
        # 테이블 존재 여부 확인
        inspector = inspect(engine)
        if 'document_embeddings' not in inspector.get_table_names():
            print("ℹ️  Table document_embeddings does not exist yet")
        else:
            # 컬럼 이름 확인
            columns = [col['name'] for col in inspector.get_columns('document_embeddings')]

            if 'metadata' in columns and 'doc_metadata' not in columns:
                print("🔧 Renaming column 'metadata' to 'doc_metadata'...")
                conn.execute(text("ALTER TABLE document_embeddings RENAME COLUMN metadata TO doc_metadata"))
                conn.commit()
                print("✅ Column renamed successfully!")
            elif 'doc_metadata' in columns:
                print("✅ Column 'doc_metadata' already exists")
            else:
                print("ℹ️  Neither 'metadata' nor 'doc_metadata' column exists yet")
except Exception as e:
    print(f"⚠️  Column fix failed (will retry with migration): {e}")
EOF

# 3. SQL 마이그레이션 실행 (documents 테이블, document_id, embedded_at 추가)
echo "📦 Running SQL migrations..."
python << EOF
import os
from sqlalchemy import create_engine, text, inspect

# 환경변수에서 직접 DATABASE_URL 가져오기
database_url = os.getenv("DATABASE_URL")
if not database_url:
    user = os.getenv("DATABASE_USER", os.getenv("POSTGRES_USER", "postgres"))
    password = os.getenv("DATABASE_PASSWORD", os.getenv("POSTGRES_PASSWORD", ""))
    host = os.getenv("DATABASE_HOST", "localhost")
    port = os.getenv("DATABASE_PORT", "5432")
    db = os.getenv("DATABASE_NAME", os.getenv("POSTGRES_DB", "ragdb"))
    database_url = f"postgresql://{user}:{password}@{host}:{port}/{db}"

database_url = database_url.replace('+asyncpg', '')

try:
    engine = create_engine(database_url)
    with engine.connect() as conn:
        inspector = inspect(engine)

        # 0. documents 테이블 생성 (존재하지 않으면)
        if 'documents' not in inspector.get_table_names():
            print("🔧 Creating documents table...")

            # DocumentStatus enum 생성 (DO 블록 대신 CREATE TYPE IF NOT EXISTS 사용 불가하므로 예외 처리)
            try:
                conn.execute(text("CREATE TYPE documentstatus AS ENUM ('uploaded', 'queued', 'processing', 'done', 'failed')"))
            except Exception as e:
                if 'already exists' not in str(e):
                    raise

            # documents 테이블 생성
            conn.execute(text("""
                CREATE TABLE documents (
                    id SERIAL PRIMARY KEY,
                    document_id VARCHAR(36) NOT NULL,
                    bot_id VARCHAR(50) NOT NULL,
                    user_uuid VARCHAR(36) NOT NULL,
                    original_filename VARCHAR(255) NOT NULL,
                    file_extension VARCHAR(10) NOT NULL,
                    file_size INTEGER NOT NULL,
                    s3_uri TEXT,
                    status documentstatus NOT NULL DEFAULT 'queued',
                    error_message TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER,
                    processing_time INTEGER,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE,
                    queued_at TIMESTAMP WITH TIME ZONE,
                    processing_started_at TIMESTAMP WITH TIME ZONE,
                    completed_at TIMESTAMP WITH TIME ZONE,
                    embedded_at TIMESTAMP WITH TIME ZONE
                )
            """))

            # 인덱스 생성
            conn.execute(text("CREATE INDEX ix_documents_id ON documents(id)"))
            conn.execute(text("CREATE UNIQUE INDEX ix_documents_document_id ON documents(document_id)"))
            conn.execute(text("CREATE INDEX ix_documents_bot_id ON documents(bot_id)"))
            conn.execute(text("CREATE INDEX ix_documents_user_uuid ON documents(user_uuid)"))
            conn.execute(text("CREATE INDEX ix_documents_status ON documents(status)"))
            conn.execute(text("CREATE INDEX ix_documents_created_at ON documents(created_at)"))

            conn.commit()
            print("✅ documents table created successfully!")
        else:
            print("✅ documents table already exists")

        # 1. document_embeddings 테이블에 document_id 추가
        if 'document_embeddings' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('document_embeddings')]

            if 'document_id' not in columns:
                print("🔧 Adding document_id to document_embeddings...")
                conn.execute(text("ALTER TABLE document_embeddings ADD COLUMN document_id VARCHAR(36)"))
                conn.execute(text("CREATE INDEX ix_document_embeddings_document_id ON document_embeddings (document_id)"))
                conn.commit()
                print("✅ document_id column added successfully!")
            else:
                print("✅ document_id column already exists")

        # 2. documents 테이블에 embedded_at 추가 (이미 위에서 생성되었으면 스킵)
        if 'documents' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('documents')]

            if 'embedded_at' not in columns:
                print("🔧 Adding embedded_at to documents...")
                conn.execute(text("ALTER TABLE documents ADD COLUMN embedded_at TIMESTAMP WITH TIME ZONE"))
                conn.commit()
                print("✅ embedded_at column added successfully!")
            else:
                print("✅ embedded_at column already exists")

        # 3. alembic_version 업데이트
        result = conn.execute(text("SELECT version_num FROM alembic_version"))
        current_version = result.scalar()
        if current_version != 'e4f5g6h7i8j9':
            print(f"🔧 Updating alembic version from {current_version} to e4f5g6h7i8j9...")
            conn.execute(text("UPDATE alembic_version SET version_num = 'e4f5g6h7i8j9'"))
            conn.commit()
            print("✅ Alembic version updated!")
        else:
            print("✅ Already at version e4f5g6h7i8j9")

except Exception as e:
    print(f"⚠️  SQL migration failed (will retry with alembic): {e}")
EOF

# 4. Alembic 마이그레이션 실행
echo "📦 Running alembic migrations..."
if alembic upgrade head; then
    echo "✅ Alembic migrations completed successfully!"
else
    echo "⚠️  Alembic migration failed, but continuing startup..."
fi

# 5. 애플리케이션 시작
echo "🚀 Starting FastAPI application..."

# 환경에 따라 reload 옵션 설정
if [ "$ENVIRONMENT" = "development" ] || [ "$DEBUG" = "true" ]; then
    echo "🔄 Development mode: Auto-reload enabled"
    exec uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
else
    echo "🚀 Production mode: Auto-reload disabled"
    exec uvicorn app.main:app --host 0.0.0.0 --port 8001
fi
