"""
Workflow 실행 로그 소비용 Lambda
---------------------------------
- SQS `snapagent-log-queue`에서 받은 로그 이벤트를 Aurora(PostgreSQL)에 저장
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

import boto3
import psycopg2
from psycopg2.extras import Json

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_SECRET_ARN = os.environ.get("DB_SECRET_ARN")
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "ragdb")

_CONNECTION = None
_SECRET_CACHE: Dict[str, Any] = {}
_SECRETS_CLIENT = boto3.client("secretsmanager") if DB_SECRET_ARN else None


def _get_conn_string() -> str:
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
    name = DB_NAME or "ragdb"
    return f"dbname={name} user={user} password={password} host={host} port={port}"


def get_connection():
    global _CONNECTION
    if _CONNECTION is None or _CONNECTION.closed:
        conn_str = _get_conn_string()
        _CONNECTION = psycopg2.connect(conn_str)
        _CONNECTION.autocommit = False
    return _CONNECTION


def _parse_datetime(value: Any) -> Any:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def upsert_execution_run(conn, run: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO workflow_execution_runs (
                id,
                bot_id,
                workflow_version_id,
                session_id,
                user_id,
                api_key_id,
                api_request_id,
                graph_snapshot,
                inputs,
                outputs,
                status,
                error_message,
                started_at,
                finished_at,
                elapsed_time,
                total_tokens,
                total_steps,
                created_at
            )
            VALUES (
                %(id)s,
                %(bot_id)s,
                %(workflow_version_id)s,
                %(session_id)s,
                %(user_id)s,
                %(api_key_id)s,
                %(api_request_id)s,
                %(graph_snapshot)s,
                %(inputs)s,
                %(outputs)s,
                %(status)s,
                %(error_message)s,
                %(started_at)s,
                %(finished_at)s,
                %(elapsed_time)s,
                %(total_tokens)s,
                %(total_steps)s,
                COALESCE(%(started_at)s, NOW())
            )
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                outputs = EXCLUDED.outputs,
                error_message = EXCLUDED.error_message,
                finished_at = EXCLUDED.finished_at,
                elapsed_time = EXCLUDED.elapsed_time,
                total_tokens = EXCLUDED.total_tokens;
            """,
            {
                "id": run.get("id"),
                "bot_id": run.get("bot_id"),
                "workflow_version_id": run.get("workflow_version_id"),
                "session_id": run.get("session_id"),
                "user_id": run.get("user_id"),
                "api_key_id": run.get("api_key_id"),
                "api_request_id": run.get("api_request_id"),
                "graph_snapshot": Json(run.get("graph_snapshot")),
                "inputs": Json(run.get("inputs") or {}),
                "outputs": Json(run.get("outputs") or {}),
                "status": run.get("status"),
                "error_message": run.get("error_message"),
                "started_at": _parse_datetime(run.get("started_at")),
                "finished_at": _parse_datetime(run.get("finished_at")),
                "elapsed_time": run.get("elapsed_time"),
                "total_tokens": run.get("total_tokens"),
                "total_steps": run.get("total_steps"),
            }
        )


def upsert_node_executions(conn, run_id: str, nodes: List[Dict[str, Any]]) -> None:
    if not nodes:
        return

    with conn.cursor() as cur:
        for node in nodes:
            cur.execute(
                """
                INSERT INTO workflow_node_executions (
                    id,
                    workflow_run_id,
                    node_id,
                    node_type,
                    execution_order,
                    inputs,
                    outputs,
                    process_data,
                    status,
                    error_message,
                    started_at,
                    finished_at,
                    elapsed_time,
                    tokens_used
                )
                VALUES (
                    %(id)s,
                    %(workflow_run_id)s,
                    %(node_id)s,
                    %(node_type)s,
                    %(execution_order)s,
                    %(inputs)s,
                    %(outputs)s,
                    %(process_data)s,
                    %(status)s,
                    %(error_message)s,
                    %(started_at)s,
                    %(finished_at)s,
                    %(elapsed_time)s,
                    %(tokens_used)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    error_message = EXCLUDED.error_message,
                    outputs = EXCLUDED.outputs,
                    finished_at = EXCLUDED.finished_at,
                    elapsed_time = EXCLUDED.elapsed_time,
                    tokens_used = EXCLUDED.tokens_used;
                """,
                {
                    "id": node.get("id"),
                    "workflow_run_id": run_id,
                    "node_id": node.get("node_id"),
                    "node_type": node.get("node_type"),
                    "execution_order": node.get("execution_order"),
                    "inputs": Json(node.get("inputs") or {}),
                    "outputs": Json(node.get("outputs") or {}),
                    "process_data": Json(node.get("process_data") or {}),
                    "status": node.get("status"),
                    "error_message": node.get("error_message"),
                    "started_at": _parse_datetime(node.get("started_at")),
                    "finished_at": _parse_datetime(node.get("finished_at")),
                    "elapsed_time": node.get("elapsed_time"),
                    "tokens_used": node.get("tokens_used"),
                }
            )


def lambda_handler(event, _context):
    conn = get_connection()
    processed = 0

    for record in event.get("Records", []):
        body = json.loads(record["body"])
        if body.get("event_type") != "workflow.log":
            continue

        run = body.get("run") or {}
        nodes = body.get("nodes") or []

        try:
            upsert_execution_run(conn, run)
            upsert_node_executions(conn, run.get("id"), nodes)
            processed += 1
        except Exception as exc:
            conn.rollback()
            LOGGER.error("워크플로우 로그 저장 실패: %s", exc)
            raise

    conn.commit()
    return {
        "statusCode": 200,
        "body": json.dumps({"processed": processed})
    }
