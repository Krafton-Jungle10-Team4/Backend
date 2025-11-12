# EC2 배포 가이드

FastAPI RAG Backend를 AWS EC2 무료 티어에 배포하는 전체 가이드입니다.

## 목차

1. [EC2 인스턴스 생성](#1-ec2-인스턴스-생성)
2. [보안 그룹 설정](#2-보안-그룹-설정)
3. [서버 초기 설정](#3-서버-초기-설정)
4. [Docker 설치](#4-docker-설치)
5. [프로젝트 배포](#5-프로젝트-배포)
6. [GitHub Actions 설정](#6-github-actions-설정)
7. [도메인 및 HTTPS 설정](#7-도메인-및-https-설정-선택)

---

## 1. EC2 인스턴스 생성

### 1.1 AWS 콘솔 접속
1. [AWS Console](https://console.aws.amazon.com) 로그인
2. EC2 대시보드로 이동
3. **인스턴스 시작** 클릭

### 1.2 인스턴스 설정

**AMI 선택:**
- Ubuntu Server 22.04 LTS (무료 티어 사용 가능)

**인스턴스 유형:**
- t2.micro (무료 티어)
- vCPU: 1, RAM: 1GB

**키 페어:**
- 새 키 페어 생성 또는 기존 키 사용
- 형식: .pem (Linux/Mac) 또는 .ppk (Windows)
- **중요:** 다운로드한 키 파일 안전하게 보관

**스토리지:**
- 30GB gp3 (무료 티어 최대)

---

## 2. 보안 그룹 설정

EC2 인스턴스의 보안 그룹에서 다음 인바운드 규칙 추가:

| 유형 | 프로토콜 | 포트 범위 | 소스 | 설명 |
|------|----------|-----------|------|------|
| SSH | TCP | 22 | 내 IP | SSH 접속용 |
| HTTP | TCP | 80 | 0.0.0.0/0 | 웹 서비스 |
| HTTPS | TCP | 443 | 0.0.0.0/0 | HTTPS (선택) |
| Custom TCP | TCP | 81 | 내 IP | ChromaDB 관리 (선택) |

**보안 권장사항:**
- SSH는 가능한 한 특정 IP만 허용
- 81 포트는 개발 중에만 열고, 프로덕션에서는 닫기

---

## 3. 서버 초기 설정

### 3.1 SSH 접속

```bash
# 키 파일 권한 설정
chmod 400 your-key.pem

# EC2 접속
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>
```

### 3.2 시스템 업데이트

```bash
sudo apt update && sudo apt upgrade -y
```

### 3.3 필수 패키지 설치

```bash
sudo apt install -y \
    curl \
    git \
    htop \
    vim
```

---

## 4. Docker 설치

### 4.1 Docker 설치

```bash
# Docker 공식 GPG 키 추가
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Docker 저장소 추가
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Docker 설치
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io
```

### 4.2 Docker Compose 설치

```bash
# Docker Compose 다운로드
sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose

# 실행 권한 부여
sudo chmod +x /usr/local/bin/docker-compose

# 버전 확인
docker-compose --version
```

### 4.3 Docker 권한 설정

```bash
# ubuntu 사용자를 docker 그룹에 추가
sudo usermod -aG docker ubuntu

# 변경사항 적용 (재접속 필요)
exit
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>

# 권한 확인
docker ps
```

---

## 5. 프로젝트 배포

### 5.1 프로젝트 클론

```bash
cd /home/ubuntu
git clone https://github.com/your-username/your-repo.git Backend
cd Backend
```

### 5.2 환경 변수 설정

```bash
# .env.local 파일 생성
cp .env.example .env.local

# 환경 변수 편집
vim .env.local
```

**필수 설정 항목:**
```bash
# AWS 설정
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
S3_BUCKET_NAME=your_bucket_name

# ChromaDB 설정 (Docker 환경)
CHROMA_HOST=chromadb
CHROMA_PORT=8000

# 기타 설정은 .env.example 참고
```

### 5.3 데이터 디렉토리 생성

```bash
mkdir -p data/chroma_data data/uploads data/huggingface_cache
```

### 5.4 배포 스크립트 실행 권한

```bash
chmod +x scripts/deploy.sh
```

### 5.5 초기 배포

```bash
# Docker 이미지 빌드 및 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f backend
```

### 5.6 서비스 확인

```bash
# Health check
curl http://localhost/health

# API 문서
curl http://localhost/docs
```

---

## 6. GitHub Actions 설정

자세한 내용은 [github-secrets-setup.md](./github-secrets-setup.md)를 참고하세요.

**필요한 Secrets:**
- `EC2_HOST`: EC2 퍼블릭 IP
- `EC2_USER`: ubuntu
- `EC2_SSH_KEY`: SSH private key 전체 내용

**배포 플로우:**
1. main 브랜치에 push
2. GitHub Actions 자동 트리거
3. EC2에 SSH 접속
4. deploy.sh 실행
5. 헬스 체크

---

## 7. 도메인 및 HTTPS 설정 (선택)

### 7.1 도메인 연결

1. 도메인 구입 (예: 가비아, Route53)
2. A 레코드 설정: `your-domain.com` → `EC2_PUBLIC_IP`

### 7.2 Let's Encrypt SSL 인증서

```bash
# Certbot 설치
sudo apt install -y certbot python3-certbot-nginx

# 인증서 발급
sudo certbot --nginx -d your-domain.com

# 자동 갱신 테스트
sudo certbot renew --dry-run
```

### 7.3 Nginx HTTPS 설정

Certbot이 자동으로 nginx.conf를 수정합니다.

**수동 설정이 필요한 경우:**
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # 나머지 설정은 기존과 동일
    location / {
        proxy_pass http://backend;
        # ...
    }
}
```

---

## 8. 모니터링 및 유지보수

### 8.1 로그 확인

```bash
# 실시간 로그
docker-compose logs -f backend

# 최근 100줄
docker-compose logs --tail=100 backend
```

### 8.2 디스크 용량 확인

```bash
df -h
docker system df
```

### 8.3 Docker 정리

```bash
# 사용하지 않는 이미지/컨테이너 삭제
docker system prune -a

# 볼륨은 유지하고 정리
docker system prune
```

### 8.4 수동 배포

```bash
cd /home/ubuntu/Backend
bash scripts/deploy.sh
```

---

## 트러블슈팅

### 메모리 부족

**증상:** 컨테이너가 자주 재시작

**해결:**
```bash
# 스왑 메모리 추가 (2GB)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 영구 설정
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 포트 충돌

**증상:** 포트가 이미 사용 중

**해결:**
```bash
# 포트 사용 프로세스 확인
sudo lsof -i :80
sudo lsof -i :8000

# 프로세스 종료
sudo kill -9 <PID>
```

### Docker 빌드 실패

**증상:** 이미지 빌드 중 오류

**해결:**
```bash
# 캐시 없이 빌드
docker-compose build --no-cache

# 로그 확인
docker-compose logs backend
```

---

---

## 9. AWS ECS 배포 (선택)

ECS Fargate를 사용한 컨테이너 배포 가이드입니다.

### 9.1 아키텍처 요구사항

**중요:** ECS Fargate는 기본적으로 **AMD64 (X86_64)** 아키텍처를 사용합니다.

```bash
# Docker 빌드 시 반드시 AMD64 플랫폼 지정
docker build --platform linux/amd64 -t your-image:latest .
```

**ARM64로 빌드 시 발생하는 오류:**
```
exec /app/entrypoint.sh: exec format error
```

### 9.2 ECR 이미지 푸시

```bash
# 1. ECR 로그인
aws ecr get-login-password --region ap-northeast-2 | \
  docker login --username AWS --password-stdin \
  YOUR_ACCOUNT_ID.dkr.ecr.ap-northeast-2.amazonaws.com

# 2. 이미지 빌드 (AMD64 필수!)
docker build --no-cache \
  --platform linux/amd64 \
  -t YOUR_ACCOUNT_ID.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest .

# 3. ECR에 푸시
docker push YOUR_ACCOUNT_ID.dkr.ecr.ap-northeast-2.amazonaws.com/rag-backend:latest

# 4. ECS 서비스 업데이트
aws ecs update-service \
  --cluster rag-cluster \
  --service rag-backend-service \
  --force-new-deployment \
  --region ap-northeast-2
```

### 9.3 데이터베이스 마이그레이션 전략

#### Option 1: Alembic 자동 마이그레이션 (권장)

`entrypoint.sh`에서 Alembic 마이그레이션 자동 실행:

```bash
# 4. Alembic 마이그레이션 실행
echo "📦 Running alembic migrations..."
if alembic upgrade head; then
    echo "✅ Alembic migrations completed successfully!"
else
    echo "⚠️  Alembic migration failed, but continuing startup..."
fi
```

**장점:**
- 컨테이너 시작 시 자동으로 DB 스키마 업데이트
- 버전 관리 및 롤백 가능
- 복잡한 마이그레이션 지원

#### Option 2: SQL 직접 실행 (백업용)

entrypoint.sh에 SQL 마이그레이션 코드 추가 (Alembic 실패 시 백업):

```bash
# 3. SQL 마이그레이션 실행
echo "📦 Running SQL migrations..."
python << EOF
import os
from sqlalchemy import create_engine, text, inspect

database_url = os.getenv("DATABASE_URL")
database_url = database_url.replace('+asyncpg', '')

try:
    engine = create_engine(database_url)
    with engine.connect() as conn:
        inspector = inspect(engine)

        if 'documents' not in inspector.get_table_names():
            print("🔧 Creating documents table...")
            # CREATE TABLE 문 실행
            conn.execute(text("CREATE TABLE documents (...);"))
            conn.commit()
            print("✅ documents table created successfully!")
except Exception as e:
    print(f"⚠️  SQL migration failed (will retry with alembic): {e}")
EOF
```

**주의사항:**
- PostgreSQL 문법 주의: `DO $$` 블록 사용 시 문법 오류 가능
- 동기 SQLAlchemy 사용 (`create_engine`, not `create_async_engine`)
- `database_url`에서 `+asyncpg` 제거 필요

### 9.4 ECS 로그 확인

```bash
# 최근 로그 확인
aws logs tail /ecs/rag-backend --region ap-northeast-2 --since 5m --format short

# 특정 키워드 필터링
aws logs tail /ecs/rag-backend --region ap-northeast-2 --since 5m --format short | grep "ERROR\|Starting\|Migration"

# 실시간 로그 스트리밍
aws logs tail /ecs/rag-backend --region ap-northeast-2 --follow
```

### 9.5 ECS 배포 상태 확인

```bash
# 서비스 상태 확인
aws ecs describe-services \
  --cluster rag-cluster \
  --services rag-backend-service \
  --region ap-northeast-2 \
  --query 'services[0].deployments[*].{Status:status,DesiredCount:desiredCount,RunningCount:runningCount,CreatedAt:createdAt}' \
  --output table

# 실행 중인 태스크 확인
aws ecs list-tasks \
  --cluster rag-cluster \
  --service-name rag-backend-service \
  --region ap-northeast-2
```

### 9.6 일반적인 ECS 트러블슈팅

#### 1. "exec format error" - 아키텍처 불일치

**원인:** ARM64 이미지를 AMD64 환경에서 실행

**해결:**
```bash
# 이미지 재빌드 (AMD64 플랫폼 명시)
docker build --platform linux/amd64 --no-cache -t IMAGE_URI .
docker push IMAGE_URI

# ECS 서비스 강제 재배포
aws ecs update-service --cluster CLUSTER --service SERVICE --force-new-deployment
```

#### 2. 데이터베이스 연결 실패

**증상:** "relation 'documents' does not exist"

**원인:** 마이그레이션 미실행 또는 실패

**해결:**
1. CloudWatch Logs에서 마이그레이션 로그 확인
2. entrypoint.sh의 마이그레이션 코드 검증
3. Alembic 버전 확인: `alembic current`
4. 수동 마이그레이션 실행 (필요시)

#### 3. VPC 네트워크 접근 문제

**증상:** RDS 연결 타임아웃

**해결:**
- ECS 태스크와 RDS가 같은 VPC에 있는지 확인
- RDS 보안 그룹에서 ECS 보안 그룹 허용
- RDS 서브넷 그룹 설정 확인

#### 4. 컨테이너 재시작 반복

**원인:** 헬스체크 실패 또는 애플리케이션 크래시

**해결:**
```bash
# 최근 로그 확인하여 오류 식별
aws logs tail /ecs/rag-backend --since 10m | grep -E "ERROR|CRITICAL|Exception"

# 헬스체크 엔드포인트 확인
curl http://YOUR_ALB_DNS/health
```

### 9.7 배포 체크리스트

배포 전 확인사항:

- [ ] Docker 이미지가 **AMD64** 플랫폼으로 빌드되었는가?
- [ ] 환경변수가 ECS Task Definition에 올바르게 설정되었는가?
- [ ] RDS 연결 정보가 정확한가? (호스트, 포트, 자격증명)
- [ ] Alembic 마이그레이션 파일이 최신인가?
- [ ] entrypoint.sh 파일의 Line Ending이 LF인가? (CRLF 아님)
- [ ] ECS 태스크 역할에 필요한 권한이 있는가? (S3, ECR 등)
- [ ] 보안 그룹 설정이 올바른가? (RDS, Redis 접근)

---

## 참고 자료

- [Docker 공식 문서](https://docs.docker.com/)
- [Nginx 공식 문서](https://nginx.org/en/docs/)
- [Let's Encrypt](https://letsencrypt.org/)
- [AWS EC2 문서](https://docs.aws.amazon.com/ec2/)
- [AWS ECS 문서](https://docs.aws.amazon.com/ecs/)
- [AWS RDS 문서](https://docs.aws.amazon.com/rds/)
- [Alembic 문서](https://alembic.sqlalchemy.org/)

---

## 다음 단계

1. ✅ EC2 배포 완료
2. 📝 [GitHub Secrets 설정](./github-secrets-setup.md)
3. 🚀 자동 배포 테스트
4. 🌐 도메인 및 HTTPS 설정 (선택)
5. 🐳 ECS Fargate 배포 (선택)
