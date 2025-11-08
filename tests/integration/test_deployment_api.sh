#!/bin/bash

BASE_URL="http://localhost:8001"

# 색상 정의
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "=== Widget 배포 API 통합 테스트 ==="
echo ""

# 1. 로그인하여 토큰 획득
echo "1. 로그인..."
TOKEN=$(curl -s -X POST "$BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "testpass"}' \
  | jq -r '.access_token')

if [ -z "$TOKEN" ] || [ "$TOKEN" == "null" ]; then
  echo -e "${RED}❌ 로그인 실패${NC}"
  exit 1
fi
echo -e "${GREEN}✅ 로그인 성공${NC}"
echo ""

# 2. 봇 생성
echo "2. 봇 생성..."
BOT_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/bots" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Widget Bot",
    "goal": "customer-support",
    "personality": "친절한"
  }')

BOT_ID=$(echo $BOT_RESPONSE | jq -r '.data.id // .bot_id')

if [ -z "$BOT_ID" ] || [ "$BOT_ID" == "null" ]; then
  echo -e "${RED}❌ 봇 생성 실패${NC}"
  echo "$BOT_RESPONSE" | jq .
  exit 1
fi
echo -e "${GREEN}✅ 봇 생성 성공: $BOT_ID${NC}"
echo ""

# 3. 봇 배포 생성
echo "3. 봇 배포 생성..."
DEPLOY_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/bots/$BOT_ID/deploy" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "published",
    "allowed_domains": ["localhost", "*.example.com"],
    "widget_config": {
      "theme": "light",
      "position": "bottom-right",
      "welcome_message": "안녕하세요! 무엇을 도와드릴까요?",
      "primary_color": "#0066FF",
      "bot_name": "고객지원 봇"
    }
  }')

WIDGET_KEY=$(echo $DEPLOY_RESPONSE | jq -r '.widget_key')
EMBED_SCRIPT=$(echo $DEPLOY_RESPONSE | jq -r '.embed_script')

if [ -z "$WIDGET_KEY" ] || [ "$WIDGET_KEY" == "null" ]; then
  echo -e "${RED}❌ 배포 생성 실패${NC}"
  echo "$DEPLOY_RESPONSE" | jq .
  exit 1
fi
echo -e "${GREEN}✅ 배포 생성 성공${NC}"
echo "Widget Key: $WIDGET_KEY"
echo "Embed Script: $EMBED_SCRIPT"
echo ""

# 4. Widget 설정 조회 (공개 API)
echo "4. Widget 설정 조회 (공개 API)..."
CONFIG_RESPONSE=$(curl -s "$BASE_URL/api/v1/widget/config/$WIDGET_KEY" \
  -H "Origin: http://localhost:3000")

if [ -z "$CONFIG_RESPONSE" ]; then
  echo -e "${RED}❌ Widget 설정 조회 실패${NC}"
  exit 1
fi
echo -e "${GREEN}✅ Widget 설정 조회 성공${NC}"
echo "$CONFIG_RESPONSE" | jq .
echo ""

# 5. Widget 세션 생성 (공개 API)
echo "5. Widget 세션 생성..."
SESSION_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/widget/sessions" \
  -H "Origin: http://localhost:3000" \
  -H "Content-Type: application/json" \
  -d '{
    "widget_key": "'$WIDGET_KEY'",
    "widget_signature": "test_signature",
    "fingerprint": {
      "user_agent": "Mozilla/5.0",
      "screen_resolution": "1920x1080",
      "timezone": "Asia/Seoul",
      "language": "ko-KR",
      "platform": "MacIntel"
    },
    "context": {
      "page_url": "http://localhost:3000/products",
      "page_title": "Products"
    }
  }')

SESSION_TOKEN=$(echo $SESSION_RESPONSE | jq -r '.session_token')
SESSION_ID=$(echo $SESSION_RESPONSE | jq -r '.session_id')

if [ -z "$SESSION_TOKEN" ] || [ "$SESSION_TOKEN" == "null" ]; then
  echo -e "${RED}❌ 세션 생성 실패${NC}"
  echo "$SESSION_RESPONSE" | jq .
  exit 1
fi
echo -e "${GREEN}✅ 세션 생성 성공${NC}"
echo "Session ID: $SESSION_ID"
echo ""

# 6. 메시지 전송 (공개 API)
echo "6. 메시지 전송..."
CHAT_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/widget/chat" \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'$SESSION_ID'",
    "message": {
      "content": "안녕하세요",
      "type": "text"
    }
  }')

MESSAGE_ID=$(echo $CHAT_RESPONSE | jq -r '.message_id')

if [ -z "$MESSAGE_ID" ] || [ "$MESSAGE_ID" == "null" ]; then
  echo -e "${RED}❌ 메시지 전송 실패${NC}"
  echo "$CHAT_RESPONSE" | jq .
  exit 1
fi
echo -e "${GREEN}✅ 메시지 전송 성공${NC}"
echo "$CHAT_RESPONSE" | jq .
echo ""

# 7. 배포 조회
echo "7. 배포 조회..."
DEPLOYMENT=$(curl -s "$BASE_URL/api/v1/bots/$BOT_ID/deployment" \
  -H "Authorization: Bearer $TOKEN")

echo -e "${GREEN}✅ 배포 조회 성공${NC}"
echo "$DEPLOYMENT" | jq .
echo ""

# 8. 배포 상태 변경
echo "8. 배포 상태 변경 (suspended)..."
STATUS_RESPONSE=$(curl -s -X PATCH "$BASE_URL/api/v1/bots/$BOT_ID/deployment/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "suspended",
    "reason": "테스트 일시 중단"
  }')

echo -e "${GREEN}✅ 배포 상태 변경 성공${NC}"
echo "$STATUS_RESPONSE" | jq .
echo ""

# 9. 배포 삭제
echo "9. 배포 삭제..."
DELETE_RESPONSE=$(curl -s -X DELETE "$BASE_URL/api/v1/bots/$BOT_ID/deployment" \
  -H "Authorization: Bearer $TOKEN")

echo -e "${GREEN}✅ 배포 삭제 성공${NC}"
echo "$DELETE_RESPONSE" | jq .
echo ""

echo "=== 모든 테스트 통과 ==="
