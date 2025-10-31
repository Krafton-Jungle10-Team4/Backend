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

## 참고 자료

- [Docker 공식 문서](https://docs.docker.com/)
- [Nginx 공식 문서](https://nginx.org/en/docs/)
- [Let's Encrypt](https://letsencrypt.org/)
- [AWS EC2 문서](https://docs.aws.amazon.com/ec2/)

---

## 다음 단계

1. ✅ EC2 배포 완료
2. 📝 [GitHub Secrets 설정](./github-secrets-setup.md)
3. 🚀 자동 배포 테스트
4. 🌐 도메인 및 HTTPS 설정 (선택)
