"""
RESTful API 배포 기능 - 슬랙봇 자동화 예시

이 스크립트는 SnapAgent의 뉴스 요약 워크플로우를 
슬랙봇으로 연동하는 예시입니다.

사용법:
1. 환경변수 설정: SNAPAGENT_API_KEY, SLACK_BOT_TOKEN, SLACK_APP_TOKEN
2. 슬랙 앱 생성 및 Socket Mode 활성화
3. 실행: python restfulapi.py
"""

import os
import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ==========================================
# 1. 환경 설정
# ==========================================

# SnapAgent API 설정
SNAPAGENT_API_KEY = os.environ.get("SNAPAGENT_API_KEY", "")
SNAPAGENT_API_URL = os.environ.get(
    "SNAPAGENT_API_URL", 
    "https://api.snapagent.com/api/v1/public/workflows/run"
)

# Slack 설정
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "xoxb-your-bot-token")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "xapp-your-app-token")

# Slack Bolt 앱 초기화
app = App(token=SLACK_BOT_TOKEN)


# ==========================================
# 2. SnapAgent API 호출 함수
# ==========================================

def call_snapagent_workflow(user_query: str) -> dict:
    """
    SnapAgent 워크플로우 실행
    
    Args:
        user_query: 사용자 질문 (예: "엔비디아 소식을 알고싶어")
    
    Returns:
        워크플로우 실행 결과 딕셔너리
    """
    try:
        response = requests.post(
            SNAPAGENT_API_URL,
            headers={
                "X-API-Key": SNAPAGENT_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "inputs": {
                    "user_query": user_query
                },
                "response_mode": "blocking"
            },
            timeout=30  # 30초 타임아웃
        )
        
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.Timeout:
        return {
            "error": "⏱️ API 요청 시간 초과 (30초)",
            "status": "timeout"
        }
    except requests.exceptions.RequestException as e:
        return {
            "error": f"❌ API 호출 실패: {str(e)}",
            "status": "error"
        }


# ==========================================
# 3. 슬랙 명령어 핸들러
# ==========================================

@app.command("/뉴스")
def handle_news_command(ack, command, say):
    """
    슬랙 명령어: /뉴스 [키워드]
    
    예시:
    - /뉴스 엔비디아
    - /뉴스 삼성전자
    - /뉴스 오늘의 IT 뉴스
    """
    # 명령어 수신 확인 (3초 내 응답 필수)
    ack()
    
    # 검색 키워드 추출
    keyword = command.get('text', '').strip()
    
    if not keyword:
        say("❓ 사용법: `/뉴스 [키워드]`\n예시: `/뉴스 엔비디아`")
        return
    
    # 로딩 메시지
    say(f"🔍 '{keyword}' 관련 뉴스를 검색 중입니다...")
    
    # SnapAgent API 호출
    user_query = f"{keyword} 소식을 알고싶어"
    result = call_snapagent_workflow(user_query)
    
    # 에러 처리
    if "error" in result:
        say(result["error"])
        return
    
    # 결과 포맷팅 및 전송
    answer = result.get('outputs', {}).get('answer', '결과를 찾을 수 없습니다.')
    usage = result.get('usage', {})
    
    message_blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📰 {keyword} 뉴스 요약",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": answer
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🤖 AI 요약 | 토큰 사용: {usage.get('total_tokens', 0)} | 실행 ID: `{result.get('workflow_run_id', 'N/A')}`"
                }
            ]
        }
    ]
    
    say(blocks=message_blocks, text=answer)


@app.command("/nvidia")
def handle_nvidia_command(ack, say):
    """
    슬랙 명령어: /nvidia
    엔비디아 전용 단축 명령어
    """
    ack()
    say("🔍 엔비디아 최신 뉴스를 검색 중입니다...")
    
    result = call_snapagent_workflow("엔비디아 소식을 알고싶어")
    
    if "error" in result:
        say(result["error"])
        return
    
    answer = result.get('outputs', {}).get('answer', '결과를 찾을 수 없습니다.')
    say(f"*🎮 NVIDIA 최신 소식*\n\n{answer}")


# ==========================================
# 4. 멘션 이벤트 핸들러
# ==========================================

@app.event("app_mention")
def handle_app_mention(event, say):
    """
    봇 멘션 시 자동 응답
    
    예시: @뉴스봇 테슬라 소식 알려줘
    """
    user_text = event.get('text', '')
    
    # 멘션 제거하고 실제 질문만 추출
    query = user_text.split('>', 1)[-1].strip()
    
    if not query:
        say("안녕하세요! 궁금한 뉴스 키워드를 말씀해주세요.\n예: `@뉴스봇 엔비디아 소식 알려줘`")
        return
    
    say("🔍 검색 중입니다...")
    
    result = call_snapagent_workflow(query)
    
    if "error" in result:
        say(result["error"])
        return
    
    answer = result.get('outputs', {}).get('answer', '결과를 찾을 수 없습니다.')
    say(answer)


# ==========================================
# 5. 정기 뉴스레터 (스케줄링)
# ==========================================

import schedule
import time
from threading import Thread

def send_daily_nvidia_report():
    """매일 오전 9시 엔비디아 뉴스 요약을 특정 채널에 전송"""
    result = call_snapagent_workflow("엔비디아 어제 소식 요약해줘")
    
    if "error" not in result:
        answer = result.get('outputs', {}).get('answer', '')
        
        # 특정 채널에 메시지 전송 (채널 ID는 환경변수로 설정)
        channel_id = os.environ.get("SLACK_NEWS_CHANNEL", "C12345678")
        
        try:
            app.client.chat_postMessage(
                channel=channel_id,
                text=f"*📅 일일 리포트 - NVIDIA 뉴스*\n\n{answer}"
            )
            print(f"✅ 정기 뉴스레터 전송 완료: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            print(f"❌ 뉴스레터 전송 실패: {e}")


def run_schedule():
    """스케줄 실행 (별도 스레드)"""
    schedule.every().day.at("09:00").do(send_daily_nvidia_report)
    
    while True:
        schedule.run_pending()
        time.sleep(60)


# ==========================================
# 6. 메인 실행
# ==========================================

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 SnapAgent 슬랙봇 시작")
    print("=" * 50)
    print(f"✅ API URL: {SNAPAGENT_API_URL}")
    print(f"✅ API Key: {SNAPAGENT_API_KEY[:20]}...")
    print(f"✅ Slack Bot: 연결 중...")
    print("=" * 50)
    
    # 정기 뉴스레터 스레드 시작 (옵션)
    # scheduler_thread = Thread(target=run_schedule, daemon=True)
    # scheduler_thread.start()
    # print("📅 정기 뉴스레터 스케줄러 활성화 (매일 오전 9시)")
    
    # Socket Mode로 슬랙봇 실행
    try:
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        print("✅ 슬랙봇 연결 성공! 명령어를 기다리는 중...")
        print("\n사용 가능한 명령어:")
        print("  - /뉴스 [키워드]")
        print("  - /nvidia")
        print("  - @봇_멘션 [질문]\n")
        handler.start()
    except KeyboardInterrupt:
        print("\n👋 슬랙봇 종료")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")

