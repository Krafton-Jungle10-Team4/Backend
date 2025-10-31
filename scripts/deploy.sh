#!/bin/bash
# FastAPI RAG Backend 배포 스크립트

set -e  # 에러 발생 시 즉시 종료

echo "========================================"
echo "  FastAPI RAG Backend 배포 시작"
echo "========================================"

# 프로젝트 디렉토리로 이동
cd /home/ec2-user/Backend || exit 1

# Git 최신 코드 가져오기
echo "📥 최신 코드 가져오는 중..."
git fetch origin
git reset --hard origin/main
echo "✅ 코드 업데이트 완료"

# 환경 변수 파일 확인
if [ ! -f .env.local ]; then
    echo "❌ .env.local 파일이 없습니다. 먼저 설정해주세요."
    exit 1
fi

# 인프라 컨테이너 확인 (Nginx, ChromaDB)
echo "🔍 인프라 서비스 확인 중..."
if ! docker-compose ps | grep -q "chromadb.*Up"; then
    echo "📦 인프라 서비스 시작 (최초 배포)..."
    docker-compose up -d chromadb nginx
    echo "⏳ ChromaDB 초기화 대기 중..."
    sleep 15
fi
echo "✅ 인프라 서비스 실행 중"

# 백엔드 이미지 Pull (Docker Hub에서)
echo "🐳 Docker Hub에서 최신 이미지 다운로드 중..."
docker-compose pull backend
echo "✅ 이미지 다운로드 완료"

# 백엔드만 재배포 (다운타임 최소화)
echo "🔨 백엔드 컨테이너 재시작 중..."
docker-compose up -d --no-deps backend
echo "✅ 백엔드 배포 완료"

# 헬스 체크 대기
echo "⏳ 서비스 헬스 체크 중..."
sleep 10

# Backend 헬스 체크
for i in {1..12}; do
    if curl -f http://localhost/health > /dev/null 2>&1; then
        echo "✅ Backend 서비스 정상 작동 중"
        break
    fi
    if [ $i -eq 12 ]; then
        echo "❌ Backend 헬스 체크 실패"
        docker-compose logs backend
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

echo ""
echo "========================================"
echo "  ✅ 배포 완료!"
echo "========================================"
echo "  Backend: http://localhost"
echo "  Health: http://localhost/health"
echo "  Docs: http://localhost/docs"
echo "========================================"
