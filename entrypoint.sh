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

# 3. Alembic 마이그레이션 실행
echo "📦 Running database migrations..."
if alembic upgrade head; then
    echo "✅ Database migrations completed successfully!"
else
    echo "⚠️  Migration failed, but continuing startup..."
fi

# 4. 애플리케이션 시작
echo "🚀 Starting FastAPI application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8001
