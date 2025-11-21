#!/bin/bash
# Slack OAuth 빠른 설정 스크립트
# 로컬 개발 환경용

set -e

echo "🚀 Slack OAuth 빠른 설정 시작..."
echo ""

# 현재 디렉토리 확인
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# .env.local 파일 존재 확인
if [ ! -f ".env.local" ]; then
    echo "❌ .env.local 파일이 없습니다."
    echo "   .env.example을 복사하여 .env.local을 먼저 생성하세요."
    exit 1
fi

# 이미 Slack 설정이 있는지 확인
if grep -q "SLACK_CLIENT_ID=" .env.local 2>/dev/null; then
    echo "⚠️  .env.local에 이미 Slack 설정이 있습니다."
    echo "   기존 설정을 유지하시겠습니까? (y/N)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "   기존 설정을 제거하고 계속합니다..."
        # Slack 관련 라인 제거
        sed -i.bak '/^SLACK_/d' .env.local
    else
        echo "   기존 설정을 유지합니다. 종료합니다."
        exit 0
    fi
fi

# 암호화 키 생성
echo "🔐 Slack 토큰 암호화 키 생성 중..."
ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null)

if [ -z "$ENCRYPTION_KEY" ]; then
    echo "❌ 암호화 키 생성 실패. cryptography 패키지가 설치되어 있는지 확인하세요."
    echo "   설치: pip install cryptography"
    exit 1
fi

# .env.local에 추가
echo "" >> .env.local
echo "# ============================================" >> .env.local
echo "# Slack OAuth 연동 (로컬 개발)" >> .env.local
echo "# ============================================" >> .env.local
echo "# 1. Slack App 생성: https://api.slack.com/apps" >> .env.local
echo "# 2. OAuth Redirect URL 추가: http://localhost:5173/slack/callback" >> .env.local
echo "# 3. Bot Token Scopes 추가: chat:write, channels:read, groups:read" >> .env.local
echo "# 4. Basic Information에서 Client ID와 Secret 확인" >> .env.local
echo "# 5. 아래 YOUR_SLACK_CLIENT_ID와 YOUR_SLACK_CLIENT_SECRET를 실제 값으로 교체" >> .env.local
echo "" >> .env.local
echo "SLACK_CLIENT_ID=YOUR_SLACK_CLIENT_ID_HERE" >> .env.local
echo "SLACK_CLIENT_SECRET=YOUR_SLACK_CLIENT_SECRET_HERE" >> .env.local
echo "SLACK_REDIRECT_URI=http://localhost:5173/slack/callback" >> .env.local
echo "SLACK_ENCRYPTION_KEY=$ENCRYPTION_KEY" >> .env.local
echo "" >> .env.local

echo "✅ .env.local 파일 업데이트 완료!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 다음 단계를 진행하세요:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1️⃣  Slack App 생성"
echo "   👉 https://api.slack.com/apps"
echo "   - 'Create New App' → 'From scratch' 선택"
echo "   - App 이름: SnapAgent Dev (또는 원하는 이름)"
echo "   - 워크스페이스 선택"
echo ""
echo "2️⃣  OAuth Redirect URL 설정"
echo "   - 좌측 메뉴 'OAuth & Permissions' 클릭"
echo "   - Redirect URLs 섹션에서 'Add New Redirect URL' 클릭"
echo "   - 입력: http://localhost:5173/slack/callback"
echo "   - 'Save URLs' 클릭"
echo ""
echo "3️⃣  Bot Token Scopes 추가"
echo "   - 같은 페이지에서 'Scopes' 섹션으로 스크롤"
echo "   - Bot Token Scopes에 다음 추가:"
echo "     • chat:write"
echo "     • channels:read"
echo "     • groups:read"
echo "     • channels:history (선택사항)"
echo ""
echo "4️⃣  Client ID와 Secret 확인"
echo "   - 좌측 메뉴 'Basic Information' 클릭"
echo "   - App Credentials 섹션에서:"
echo "     • Client ID 복사"
echo "     • Client Secret 복사 ('Show' 클릭)"
echo ""
echo "5️⃣  .env.local 파일 수정"
echo "   - 에디터로 .env.local 파일 열기"
echo "   - YOUR_SLACK_CLIENT_ID_HERE → 복사한 Client ID로 교체"
echo "   - YOUR_SLACK_CLIENT_SECRET_HERE → 복사한 Client Secret으로 교체"
echo "   - 저장"
echo ""
echo "6️⃣  Docker 재시작"
echo "   👉 docker-compose down && docker-compose up -d"
echo ""
echo "7️⃣  환경 변수 확인"
echo "   👉 docker-compose exec backend printenv | grep SLACK"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📝 생성된 암호화 키 (참고용):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "$ENCRYPTION_KEY"
echo ""
echo "⚠️  암호화 키는 이미 .env.local에 저장되었습니다."
echo "   별도로 복사할 필요 없습니다."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "💡 Slack 연동이 필요하지 않다면:"
echo "   .env.local에서 SLACK_CLIENT_ID 라인만 주석 처리하면 됩니다."
echo "   (앞에 # 추가)"
echo ""

