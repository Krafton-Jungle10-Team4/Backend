# Docker Hub 설정 가이드

Docker Hub를 통한 이미지 기반 배포 설정 방법입니다.

## 1. Docker Hub 계정 생성

### 1.1 회원가입
```
https://hub.docker.com/signup
→ Email, Username, Password 입력
→ 이메일 인증
```

**Username 기억하기!** (예: `myusername`)

---

## 2. Docker Hub Repository 생성

### 2.1 새 Repository 만들기
```
https://hub.docker.com/
→ Repositories 탭
→ Create Repository 클릭
```

### 2.2 Repository 설정
```
Name: fastapi-rag-backend
Visibility: Public (무료) 또는 Private (Pro 계정)
Description: FastAPI RAG Backend
```

**Repository 이름:** `myusername/fastapi-rag-backend`

---

## 3. Access Token 생성

### 3.1 계정 설정
```
https://hub.docker.com/settings/security
→ New Access Token 클릭
```

### 3.2 토큰 설정
```
Access Token Description: github-actions
Access permissions: Read, Write, Delete
```

### 3.3 토큰 복사
```
⚠️ 토큰은 한 번만 표시됩니다!
즉시 복사해서 안전하게 보관하세요.
```

**토큰 예시:**
```
dckr_pat_1234567890abcdefghijklmnopqrstuvwxyz
```

---

## 4. GitHub Secrets 추가

### 4.1 GitHub Repository 설정
```
Repository → Settings
→ Secrets and variables → Actions
→ New repository secret
```

### 4.2 필수 Secrets 추가

**DOCKERHUB_USERNAME**
```
Name: DOCKERHUB_USERNAME
Value: myusername
```

**DOCKERHUB_TOKEN**
```
Name: DOCKERHUB_TOKEN
Value: dckr_pat_1234567890abcdefghijklmnopqrstuvwxyz
```

---

## 5. 전체 GitHub Secrets 목록

배포에 필요한 모든 Secrets:

| Secret 이름 | 값 | 설명 |
|------------|-----|------|
| EC2_HOST | `3.35.123.456` | EC2 IP |
| EC2_USER | `ec2-user` | SSH 사용자 |
| EC2_SSH_KEY | `-----BEGIN...` | SSH Key |
| **DOCKERHUB_USERNAME** | `myusername` | Docker Hub 사용자명 |
| **DOCKERHUB_TOKEN** | `dckr_pat_...` | Docker Hub 토큰 |
| AWS_ACCESS_KEY_ID | `` | AWS 키 (선택) |
| AWS_SECRET_ACCESS_KEY | `` | AWS 키 (선택) |
| S3_BUCKET_NAME | `` | S3 버킷 (선택) |

**총 8개 Secrets**

---

## 6. 배포 플로우 (변경 후)

### 기존 방식 (Git + 빌드)
```
00:00 - git push
00:30 - EC2에서 빌드 (30초)
01:00 - 컨테이너 재시작
01:30 - 모델 로딩
02:00 - 완료
```

### Docker Hub 방식 (이미지)
```
00:00 - git push
00:10 - GitHub에서 빌드 (30초)
00:40 - Docker Hub 푸시 (10초)
00:50 - EC2에서 pull (5초)
00:55 - 컨테이너 재시작
01:25 - 모델 로딩
01:30 - 완료 (30초 단축!)
```

**장점:**
- ✅ EC2 CPU/메모리 부하 감소
- ✅ 배포 속도 향상
- ✅ 이미지 버전 관리 가능
- ✅ 여러 서버에 동일 이미지 배포

---

## 7. 이미지 태깅 전략

### latest 태그 (기본)
```
myusername/fastapi-rag-backend:latest
```
- main 브랜치 푸시 시 자동 업데이트
- 항상 최신 버전

### 커밋 해시 태그 (권장)
```
myusername/fastapi-rag-backend:abc1234
```
- 특정 커밋으로 롤백 가능
- 버전 추적 용이

### 날짜 태그
```
myusername/fastapi-rag-backend:2025-01-15
```
- 배포 날짜 기록
- 시간순 정렬

---

## 8. Docker Hub 무료 티어 제한

### Public Repository
```
무제한 Public Repositories
무제한 이미지 Pull
무제한 이미지 Push
```

### Rate Limits
```
익명: 100 pulls / 6시간
로그인: 200 pulls / 6시간
Pro: 무제한
```

**MVP에 충분합니다!** ✅

---

## 9. 트러블슈팅

### 401 Unauthorized
```
원인: DOCKERHUB_TOKEN 오류
해결: Access Token 재생성 및 Secrets 업데이트
```

### Image not found
```
원인: Repository 이름 오류
해결: docker-compose.yml에서 이미지 이름 확인
```

### Push 실패
```
원인: 토큰 권한 부족
해결: Access Token에 Write 권한 추가
```

---

## 10. 로컬 테스트

### Docker Hub에 수동 푸시
```bash
# 로그인
docker login -u myusername

# 빌드
docker build -t myusername/fastapi-rag-backend:latest .

# 푸시
docker push myusername/fastapi-rag-backend:latest

# EC2에서 pull
ssh ec2-user@EC2_HOST
docker pull myusername/fastapi-rag-backend:latest
docker-compose up -d
```

---

## 요약

**설정 순서:**
1. Docker Hub 계정 생성
2. Repository 생성: `myusername/fastapi-rag-backend`
3. Access Token 생성
4. GitHub Secrets 추가: DOCKERHUB_USERNAME, DOCKERHUB_TOKEN
5. 코드 변경 (deploy.yml, docker-compose.yml, deploy.sh)
6. git push origin main → 자동 배포!

**다음 단계:** 코드 변경 작업 진행

**Docker Hub 배포 준비 완료!** 🐳
