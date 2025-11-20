# Slack OAuth 연동 가이드

이 가이드는 SnapAgent에서 Slack OAuth 방식 연동을 설정하는 방법을 설명합니다.

## 📋 개요

OAuth 방식을 사용하면 각 사용자가 자신의 Slack 워크스페이스를 SnapAgent에 안전하게 연결할 수 있습니다. 토큰은 암호화되어 데이터베이스에 저장되며, 워크플로우에서 Slack 노드를 사용할 때 자동으로 사용됩니다.

## 🔧 1. Slack App 생성

### 1.1 Slack API 사이트 접속

1. [https://api.slack.com/apps](https://api.slack.com/apps) 접속
2. "Create New App" 클릭
3. "From scratch" 선택
4. App 이름과 워크스페이스 선택 후 "Create App" 클릭

### 1.2 OAuth & Permissions 설정

1. 좌측 메뉴에서 "OAuth & Permissions" 클릭
2. **Redirect URLs** 섹션:
   - "Add New Redirect URL" 클릭
   - 개발 환경: `http://localhost:5173/slack/callback`
   - 프로덕션: `https://yourdomain.com/slack/callback`
   - "Add" 클릭 후 "Save URLs" 클릭

3. **Scopes** 섹션 (Bot Token Scopes):
   - `chat:write` - 메시지 전송
   - `channels:read` - Public 채널 목록 조회
   - `groups:read` - Private 채널 목록 조회
   - (선택) `channels:history` - 채널 메시지 읽기
   - (선택) `chat:write.public` - 봇이 속하지 않은 채널에 메시지 전송

### 1.3 Credentials 확인

1. 좌측 메뉴에서 "Basic Information" 클릭
2. **App Credentials** 섹션에서 다음 정보 확인:
   - **Client ID**: `SLACK_CLIENT_ID`로 사용
   - **Client Secret**: `SLACK_CLIENT_SECRET`으로 사용 ("Show" 클릭하여 확인)

## 🔑 2. 환경 변수 설정

### 2.1 Backend 환경 변수

`Backend/.env` 또는 `Backend/.env.local` 파일에 다음 내용 추가:

```bash
# Slack OAuth 연동
SLACK_CLIENT_ID=1234567890.1234567890123
SLACK_CLIENT_SECRET=abcd1234efgh5678ijkl9012mnop3456
SLACK_REDIRECT_URI=http://localhost:5173/slack/callback

# Slack 토큰 암호화 키 (Fernet 키)
# 아래 명령어로 생성:
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
SLACK_ENCRYPTION_KEY=your-generated-fernet-key-here
```

### 2.2 암호화 키 생성

터미널에서 다음 명령어 실행:

```bash
cd /Users/leeseungheon/Developer/projects/Backend
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

출력된 키를 `SLACK_ENCRYPTION_KEY`에 설정합니다.

### 2.3 프로덕션 환경

프로덕션에서는 다음 사항에 유의:

- `SLACK_REDIRECT_URI`를 실제 도메인으로 변경 (예: `https://yourdomain.com/slack/callback`)
- Slack App의 Redirect URL도 동일하게 업데이트
- `SLACK_ENCRYPTION_KEY`는 반드시 안전하게 관리 (환경 변수나 시크릿 매니저 사용)

## 📦 3. 의존성 설치

### 3.1 Backend

```bash
cd /Users/leeseungheon/Developer/projects/Backend
pip install slack-sdk cryptography
```

또는 `requirements.txt`가 업데이트된 경우:

```bash
pip install -r requirements.txt
```

### 3.2 Frontend

필요한 패키지는 이미 설치되어 있습니다 (axios, zustand, lucide-react 등).

## 🗄️ 4. 데이터베이스 마이그레이션

새로운 `slack_integrations` 테이블을 생성하기 위해 마이그레이션 실행:

```bash
cd /Users/leeseungheon/Developer/projects/Backend
alembic revision --autogenerate -m "Add slack_integrations table"
alembic upgrade head
```

또는 애플리케이션 시작 시 자동으로 실행되도록 설정되어 있습니다 (entrypoint.sh).

## 🚀 5. 사용 방법

### 5.1 Slack 연동하기

1. Frontend 실행: `http://localhost:5173`
2. 워크스페이스에서 봇 선택
3. 상단의 "배포" 버튼 클릭
4. "연동" 탭 클릭
5. "Slack 연동하기" 버튼 클릭
6. Slack 인증 페이지로 리다이렉트됨
7. 워크스페이스 선택 및 "허용" 클릭
8. 자동으로 SnapAgent로 돌아옴 (연동 완료)

### 5.2 워크플로우에서 Slack 노드 사용

1. 워크플로우 편집기에서 Slack 노드 추가
2. 노드 설정:
   - **Integration**: 연동한 Slack 워크스페이스 선택
   - **Channel**: 메시지를 보낼 채널 선택 (예: `#general`)
   - **Use Blocks**: 메시지 블록 사용 여부 (제목과 본문을 구분하여 표시)
3. 입력 포트 연결:
   - **text**: 전송할 메시지 (필수)
   - **title**: 메시지 제목 (선택, Use Blocks=true일 때 사용)

### 5.3 RESTful API로 호출

연동 후, API 키를 사용하여 외부에서 워크플로우를 실행하면 자동으로 Slack으로 메시지가 전송됩니다:

```bash
curl -X POST "https://api.snapagent.com/api/v1/public/workflows/run" \
  -H "X-API-Key: wk_your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "bot_id": "bot_1763531628_cf6bf41cdc",
    "inputs": {
      "topic": "AI 최신 뉴스"
    }
  }'
```

## 🔒 6. 보안

- **토큰 암호화**: Slack Access Token은 Fernet 대칭 암호화를 사용하여 DB에 저장됩니다.
- **HTTPS 사용**: 프로덕션에서는 반드시 HTTPS를 사용하세요.
- **환경 변수 관리**: `SLACK_ENCRYPTION_KEY`는 절대 Git에 커밋하지 마세요 (`.gitignore`에 `.env` 추가).
- **권한 범위**: Slack App에서 필요한 최소 권한만 요청하세요.

## 🛠️ 7. 트러블슈팅

### 7.1 "Invalid state" 에러

- OAuth state가 만료되었거나 잘못되었습니다.
- 다시 "Slack 연동하기" 버튼을 클릭하세요.

### 7.2 "Slack API Error: missing_scope"

- Slack App의 Bot Token Scopes가 부족합니다.
- OAuth & Permissions에서 필요한 scope를 추가하고 재설치하세요.

### 7.3 "Failed to decrypt token"

- `SLACK_ENCRYPTION_KEY`가 변경되었거나 잘못되었습니다.
- 키를 확인하고, 필요 시 기존 연동을 삭제하고 다시 연동하세요.

### 7.4 "Redirect URL mismatch"

- `SLACK_REDIRECT_URI`와 Slack App의 Redirect URL이 일치하지 않습니다.
- Slack App 설정에서 정확한 URL을 추가했는지 확인하세요.

## 📚 8. 추가 자료

- [Slack OAuth 공식 문서](https://api.slack.com/authentication/oauth-v2)
- [Slack Bot Token Scopes](https://api.slack.com/scopes)
- [Fernet 암호화](https://cryptography.io/en/latest/fernet/)

## ✅ 9. 체크리스트

- [ ] Slack App 생성 및 Redirect URL 설정
- [ ] Client ID, Client Secret 확인
- [ ] 필요한 Bot Token Scopes 추가
- [ ] Backend `.env` 파일에 환경 변수 추가
- [ ] `SLACK_ENCRYPTION_KEY` 생성 및 설정
- [ ] `slack-sdk`, `cryptography` 패키지 설치
- [ ] 데이터베이스 마이그레이션 실행
- [ ] Frontend에서 Slack 연동 테스트
- [ ] 워크플로우에서 Slack 노드 테스트
- [ ] RESTful API로 워크플로우 실행 테스트

---

구현이 완료되었습니다! 🎉

