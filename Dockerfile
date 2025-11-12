# 멀티스테이지 빌드로 이미지 크기 최적화
FROM python:3.11-slim as builder

WORKDIR /build

# 빌드 도구 설치 (컴파일 필요한 패키지용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 의존성 설치 (--user로 /root/.local에 설치)
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# 최종 런타임 이미지
FROM python:3.11-slim

WORKDIR /app

# 런타임 필수 패키지만 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 빌더 스테이지에서 설치된 Python 패키지만 복사
COPY --from=builder /root/.local /root/.local

# 애플리케이션 코드 복사
COPY . .

# 디렉토리 생성
RUN mkdir -p /app/data/uploads /app/data/huggingface_cache

# entrypoint 스크립트 line ending 수정 및 실행 권한 부여
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh || echo "Warning: entrypoint.sh not found, using inline script"

# Python 패키지 경로 설정
ENV PATH=/root/.local/bin:$PATH \
    PYTHONPATH=/app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# entrypoint 스크립트 사용
ENTRYPOINT ["/app/entrypoint.sh"]