"""
위젯 API와 일반 API를 구분하여 CORS 적용
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from app.config import settings


class WidgetCORSMiddleware(BaseHTTPMiddleware):
    """
    경로별 CORS 정책 적용 미들웨어

    - /api/v1/widget/* : 모든 도메인 허용 (외부 임베딩)
    - 그 외 API : 설정된 도메인만 허용 (보안)
    """

    async def dispatch(self, request, call_next):
        # 위젯 API 경로 확인
        is_widget_api = request.url.path.startswith("/api/v1/widget/")

        # OPTIONS 요청 (Preflight)
        if request.method == "OPTIONS":
            if is_widget_api:
                # 위젯 API: 모든 도메인 허용
                return Response(
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type, Authorization, Origin, Referer",
                    }
                )
            else:
                # 일반 API: 설정된 도메인만 허용
                origin = request.headers.get("origin")
                # 와일드카드("*") 지원 추가
                if "*" in settings.cors_origins:
                    # 와일드카드가 설정된 경우 모든 Origin 허용
                    return Response(
                        status_code=200,
                        headers={
                            "Access-Control-Allow-Origin": origin or "*",
                            "Access-Control-Allow-Credentials": "true",
                            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
                            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With, Accept, Origin, Referer",
                        }
                    )
                elif origin in settings.cors_origins:
                    # 특정 Origin이 허용 목록에 있는 경우
                    return Response(
                        status_code=200,
                        headers={
                            "Access-Control-Allow-Origin": origin,
                            "Access-Control-Allow-Credentials": "true",
                            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
                            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With, Accept, Origin, Referer",
                        }
                    )
                else:
                    return Response(status_code=403)

        # 실제 요청 처리
        response = await call_next(request)

        # CORS 헤더 추가
        if is_widget_api:
            # 위젯 API: 모든 도메인 허용, Credentials 없음
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Origin, Referer"
        else:
            # 일반 API: 설정된 도메인만 허용, Credentials 있음
            origin = request.headers.get("origin")
            # 와일드카드 처리 추가
            if "*" in settings.cors_origins:
                # 와일드카드가 설정된 경우 모든 Origin 허용
                response.headers["Access-Control-Allow-Origin"] = origin or "*"
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept, Origin, Referer"
            elif origin in settings.cors_origins:
                # 특정 Origin이 허용 목록에 있는 경우
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept, Origin, Referer"

        return response
