#!/bin/bash
# RESTful API 배포 테스트 스크립트
# 사용법: ./test_restful_api.sh <API_KEY>

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 설정
BASE_URL="${BASE_URL:-http://localhost:8000}"
API_KEY="${1:-}"

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}  RESTful API 배포 테스트${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

# API 키 확인
if [ -z "$API_KEY" ]; then
    echo -e "${RED}❌ 오류: API 키가 제공되지 않았습니다.${NC}"
    echo -e "${YELLOW}사용법: ./test_restful_api.sh <API_KEY>${NC}"
    echo ""
    echo -e "${YELLOW}API 키 생성 방법:${NC}"
    echo "1. http://localhost:5173 접속"
    echo "2. 봇 생성 → 워크플로우 배포"
    echo "3. '배포' 탭 → 'API 키 생성'"
    echo ""
    exit 1
fi

echo -e "${GREEN}✅ API 키: ${API_KEY:0:20}...${NC}"
echo -e "${GREEN}✅ Base URL: $BASE_URL${NC}"
echo ""

# 테스트 1: 서버 상태 확인
echo -e "${BLUE}[테스트 1] 서버 상태 확인${NC}"
if curl -s -f "$BASE_URL/docs" > /dev/null; then
    echo -e "${GREEN}✅ 서버 정상 응답${NC}"
else
    echo -e "${RED}❌ 서버 응답 없음. 서버가 실행 중인지 확인하세요.${NC}"
    exit 1
fi
echo ""

# 테스트 2: 워크플로우 실행 (간단한 쿼리)
echo -e "${BLUE}[테스트 2] 워크플로우 실행 (단순 쿼리)${NC}"
RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/public/workflows/run" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "user_query": "안녕하세요"
    },
    "response_mode": "blocking"
  }')

# 응답 확인
if echo "$RESPONSE" | jq -e '.workflow_run_id' > /dev/null 2>&1; then
    WORKFLOW_RUN_ID=$(echo "$RESPONSE" | jq -r '.workflow_run_id')
    echo -e "${GREEN}✅ 워크플로우 실행 성공${NC}"
    echo -e "${GREEN}   - 실행 ID: $WORKFLOW_RUN_ID${NC}"
    
    # outputs가 있는지 확인
    if echo "$RESPONSE" | jq -e '.outputs' > /dev/null 2>&1; then
        ANSWER=$(echo "$RESPONSE" | jq -r '.outputs.answer // "N/A"' | head -c 100)
        echo -e "${GREEN}   - 답변: $ANSWER...${NC}"
    fi
    
    # 토큰 사용량
    if echo "$RESPONSE" | jq -e '.usage' > /dev/null 2>&1; then
        TOTAL_TOKENS=$(echo "$RESPONSE" | jq -r '.usage.total_tokens // 0')
        echo -e "${GREEN}   - 토큰 사용량: $TOTAL_TOKENS${NC}"
    fi
else
    echo -e "${RED}❌ 워크플로우 실행 실패${NC}"
    echo -e "${YELLOW}응답:${NC}"
    echo "$RESPONSE" | jq '.' || echo "$RESPONSE"
    exit 1
fi
echo ""

# 테스트 3: 실행 결과 조회
if [ -n "$WORKFLOW_RUN_ID" ]; then
    echo -e "${BLUE}[테스트 3] 실행 결과 조회${NC}"
    DETAIL_RESPONSE=$(curl -s -X GET "$BASE_URL/api/v1/public/workflows/runs/$WORKFLOW_RUN_ID" \
      -H "X-API-Key: $API_KEY")
    
    if echo "$DETAIL_RESPONSE" | jq -e '.workflow_run_id' > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 실행 결과 조회 성공${NC}"
        STATUS=$(echo "$DETAIL_RESPONSE" | jq -r '.status // "unknown"')
        echo -e "${GREEN}   - 상태: $STATUS${NC}"
    else
        echo -e "${YELLOW}⚠️  실행 결과 조회 실패 (엔드포인트 미구현 가능성)${NC}"
    fi
    echo ""
fi

# 테스트 4: 복잡한 쿼리 (뉴스 검색)
echo -e "${BLUE}[테스트 4] 워크플로우 실행 (복잡한 쿼리)${NC}"
COMPLEX_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/public/workflows/run" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "user_query": "엔비디아 최신 뉴스 알려줘"
    },
    "response_mode": "blocking",
    "user": "test-user-001",
    "session_id": "test-session-001",
    "metadata": {
      "source": "test_script",
      "test_id": "complex_query"
    }
  }')

if echo "$COMPLEX_RESPONSE" | jq -e '.workflow_run_id' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 복잡한 쿼리 실행 성공${NC}"
    
    # 실행 시간
    if echo "$COMPLEX_RESPONSE" | jq -e '.elapsed_time' > /dev/null 2>&1; then
        ELAPSED=$(echo "$COMPLEX_RESPONSE" | jq -r '.elapsed_time // 0')
        echo -e "${GREEN}   - 실행 시간: ${ELAPSED}초${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  복잡한 쿼리 실행 실패${NC}"
    echo "$COMPLEX_RESPONSE" | jq '.' 2>/dev/null || echo "$COMPLEX_RESPONSE"
fi
echo ""

# 테스트 5: 잘못된 입력 (에러 핸들링 확인)
echo -e "${BLUE}[테스트 5] 에러 핸들링 확인 (빈 입력)${NC}"
ERROR_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/public/workflows/run" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "response_mode": "blocking"
  }')

if echo "$ERROR_RESPONSE" | jq -e '.detail' > /dev/null 2>&1; then
    ERROR_CODE=$(echo "$ERROR_RESPONSE" | jq -r '.detail.code // "UNKNOWN"')
    echo -e "${GREEN}✅ 에러 핸들링 정상 작동${NC}"
    echo -e "${GREEN}   - 에러 코드: $ERROR_CODE${NC}"
else
    echo -e "${YELLOW}⚠️  예상과 다른 응답${NC}"
fi
echo ""

# 최종 결과
echo -e "${BLUE}================================${NC}"
echo -e "${GREEN}✅ 테스트 완료!${NC}"
echo -e "${BLUE}================================${NC}"
echo ""
echo -e "${YELLOW}다음 단계:${NC}"
echo "1. Demo App에서 시각적으로 테스트 (http://localhost:5173)"
echo "2. Slack Bot 연동 테스트 (python restfulapi.py)"
echo "3. Postman Collection 사용"
echo ""

