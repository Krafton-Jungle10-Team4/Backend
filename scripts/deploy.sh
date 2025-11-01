#!/bin/bash
# FastAPI RAG Backend 배포 스크립트 (Docker Hub Pull 방식)

set -e  # 에러 발생 시 즉시 종료

echo "========================================"
echo "  FastAPI RAG Backend 배포 시작"
echo "========================================"

# 프로젝트 디렉토리
DEPLOY_DIR="${HOME}/Backend"
cd "${DEPLOY_DIR}" || exit 1

# Docker 이미지 이름 (환경 변수로 전달됨)
DOCKER_IMAGE="${DOCKER_IMAGE:-$DOCKERHUB_USERNAME/backend:latest}"

echo "🐳 Docker 이미지: ${DOCKER_IMAGE}"

# 환경 변수 파일 확인
if [ ! -f .env.local ]; then
    echo "❌ .env.local 파일이 없습니다. 먼저 설정해주세요."
    exit 1
fi

# docker-compose.yml 존재 확인
if [ ! -f docker-compose.yml ]; then
    echo "❌ docker-compose.yml 파일이 없습니다."
    exit 1
fi

# 기존 컨테이너 중지 (데이터는 보존)
echo "🛑 기존 백엔드 컨테이너 중지 중..."
docker-compose stop backend || true

# ChromaDB 및 Nginx 인프라 확인
echo "🔍 인프라 서비스 확인 중..."
if ! docker-compose ps 2>/dev/null | grep -q "chromadb.*Up"; then
    echo "📦 ChromaDB 시작 (최초 배포)..."
    docker-compose up -d chromadb
    echo "⏳ ChromaDB 초기화 대기 중 (30초)..."
    sleep 30

    # ChromaDB 상태 확인
    if ! docker-compose ps | grep -q "chromadb.*Up"; then
        echo "❌ ChromaDB 시작 실패"
        docker-compose logs chromadb
        exit 1
    fi
    echo "✅ ChromaDB 시작 완료"
else
    echo "✅ ChromaDB 이미 실행 중"
fi

if ! docker-compose ps 2>/dev/null | grep -q "nginx.*Up"; then
    echo "📦 Nginx 시작..."
    docker-compose up -d nginx
    sleep 5
    echo "✅ Nginx 시작 완료"
else
    echo "✅ Nginx 이미 실행 중"
fi

# 최신 이미지 Pull (Docker Hub에서)
echo "🐳 Docker Hub에서 최신 이미지 다운로드 중..."
echo "   이미지: ${DOCKER_IMAGE}"
docker pull "${DOCKER_IMAGE}"
echo "✅ 이미지 다운로드 완료"

# 오래된 이미지 정리
echo "🧹 오래된 이미지 정리 중..."
docker image prune -f

# 백엔드 컨테이너 재시작 (다운타임 최소화)
echo "🔨 백엔드 컨테이너 재시작 중..."
docker-compose up -d --no-deps backend
echo "✅ 백엔드 배포 완료"

# 헬스 체크 대기
echo "⏳ 서비스 헬스 체크 중..."
sleep 10

# Backend 헬스 체크 (최대 60초)
echo "🔍 Backend 헬스 체크..."
for i in {1..12}; do
    if curl -f http://localhost/health > /dev/null 2>&1; then
        echo "✅ Backend 서비스 정상 작동 중"
        break
    fi
    if [ $i -eq 12 ]; then
        echo "❌ Backend 헬스 체크 실패"
        echo ""
        echo "📝 Backend 로그:"
        docker-compose logs --tail=50 backend
        exit 1
    fi
    echo "   대기 중... ($i/12)"
    sleep 5
done

# 실행 중인 컨테이너 확인
echo ""
echo "📊 실행 중인 컨테이너:"
docker-compose ps

# 최근 로그 확인
echo ""
echo "📝 최근 로그:"
docker-compose logs --tail=20 backend

# 디스크 사용량 확인
echo ""
echo "💾 디스크 사용량:"
df -h | grep -E "Filesystem|/dev/root"

echo ""
echo "========================================"
echo "  ✅ 배포 완료!"
echo "========================================"
echo "  Backend: http://localhost"
echo "  Health: http://localhost/health"
echo "  Docs: http://localhost/docs"
echo "========================================"
