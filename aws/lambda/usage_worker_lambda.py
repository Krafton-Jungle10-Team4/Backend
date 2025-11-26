"""
Usage Queue 소비용 Lambda 함수
--------------------------------
- SQS `snapagent-usage-queue`에서 메시지를 읽어 Aurora(PostgreSQL)에 저장
- psycopg2 (또는 psycopg) 드라이버가 레이어/패키지로 포함되어야 함
"""
import json
import logging
import os
from typing import Any, Dict

import boto3
import psycopg2

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL")
IDEMPOTENCY_TABLE = os.environ.get("IDEMPOTENCY_TABLE", "llm_usage_events")
DB_SECRET_ARN = os.environ.get("DB_SECRET_ARN")
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "ragdb")

_CONNECTION = None
_SECRET_CACHE: Dict[str, Any] = {}
_SECRETS_CLIENT = boto3.client("secretsmanager") if DB_SECRET_ARN else None


def _build_conn_string() -> str:
    """
    DATABASE_URL 우선, 없으면 Secrets Manager에서 사용자/비밀번호를 받아 구성
    """
    if DATABASE_URL:
        return DATABASE_URL

    if not (DB_SECRET_ARN and DB_HOST):
        raise RuntimeError("DATABASE_URL 또는 DB_SECRET_ARN/DB_HOST 환경 변수가 필요합니다.")

    if DB_SECRET_ARN not in _SECRET_CACHE:
        response = _SECRETS_CLIENT.get_secret_value(SecretId=DB_SECRET_ARN)
        secret_string = response.get("SecretString")
        if not secret_string:
            raise RuntimeError("SecretString이 비어 있습니다.")
        _SECRET_CACHE[DB_SECRET_ARN] = json.loads(secret_string)

    secret = _SECRET_CACHE[DB_SECRET_ARN]
    user = secret.get("username")
    password = secret.get("password")
    if not all([user, password]):
        raise RuntimeError("Secret에 username/password가 없습니다.")

    host = DB_HOST
    port = DB_PORT or "5432"
    name = DB_NAME or "postgres"

    return f"dbname={name} user={user} password={password} host={host} port={port}"


def get_connection():
    """Lambda 재사용 기간 동안 DB 커넥션을 캐시"""
    global _CONNECTION
    if _CONNECTION is None or _CONNECTION.closed:
        conn_str = _build_conn_string()
        _CONNECTION = psycopg2.connect(conn_str)
        _CONNECTION.autocommit = False
    return _CONNECTION


def ensure_idempotency_table(conn) -> None:
    """최초 실행 시 이벤트 잠금 테이블 생성"""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {IDEMPOTENCY_TABLE} (
                idempotency_key VARCHAR(255) PRIMARY KEY,
                processed_at TIMESTAMP DEFAULT NOW()
            );
            """
        )
        conn.commit()


def has_processed(conn, idempotency_key: str) -> bool:
    if not idempotency_key:
        return False
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {IDEMPOTENCY_TABLE} WHERE idempotency_key = %s",
            (idempotency_key,),
        )
        return cur.fetchone() is not None


def lock_idempotency(conn, idempotency_key: str) -> None:
    if not idempotency_key:
        return
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {IDEMPOTENCY_TABLE}(idempotency_key)
            VALUES (%s)
            ON CONFLICT DO NOTHING;
            """,
            (idempotency_key,),
        )


def insert_usage_log(conn, payload: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO llm_usage_logs (
                bot_id,
                user_id,
                provider,
                model_name,
                input_tokens,
                output_tokens,
                total_tokens,
                cache_read_tokens,
                cache_write_tokens,
                input_cost,
                output_cost,
                total_cost,
                request_id,
                session_id,
                created_at
            )
            VALUES (
                %(bot_id)s,
                %(user_id)s,
                %(provider)s,
                %(model_name)s,
                %(input_tokens)s,
                %(output_tokens)s,
                %(total_tokens)s,
                %(cache_read_tokens)s,
                %(cache_write_tokens)s,
                %(input_cost)s,
                %(output_cost)s,
                %(total_cost)s,
                %(request_id)s,
                %(session_id)s,
                %(timestamp)s::timestamptz
            );
            """,
            payload,
        )


def lambda_handler(event, _context):
    conn = get_connection()
    ensure_idempotency_table(conn)

    processed = 0
    failed = 0
    
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            key = body.get("idempotency_key")
            
            if not key:
                LOGGER.warning("idempotency_key가 없습니다. body: %s", body)
                failed += 1
                continue

            if has_processed(conn, key):
                LOGGER.info("이미 처리된 이벤트 건너뜀: %s", key)
                continue

            # 필수 필드 검증
            required_fields = ["bot_id", "user_id", "provider", "model_name"]
            missing_fields = [field for field in required_fields if not body.get(field)]
            if missing_fields:
                LOGGER.error(
                    "필수 필드 누락: %s. body: %s",
                    missing_fields,
                    body
                )
                failed += 1
                continue

            insert_usage_log(conn, {
                **body,
                "timestamp": body.get("timestamp") or "now()"
            })
            lock_idempotency(conn, key)
            processed += 1
            
            LOGGER.info(
                "사용량 로그 저장 완료: bot_id=%s, model=%s, tokens=%d, cost=%.6f",
                body.get("bot_id"),
                body.get("model_name"),
                body.get("total_tokens", 0),
                body.get("total_cost", 0.0)
            )
        except Exception as exc:
            LOGGER.error("메시지 처리 실패: %s", exc, exc_info=True)
            failed += 1
            conn.rollback()
            continue

    conn.commit()

    LOGGER.info("처리 완료: processed=%d, failed=%d", processed, failed)
    
    return {
        "statusCode": 200,
        "body": json.dumps({"processed": processed, "failed": failed})
    }
