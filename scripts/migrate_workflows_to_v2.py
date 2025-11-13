"""
워크플로우 V1 → V2 마이그레이션 스크립트

기존 워크플로우를 V2 포트 기반 시스템으로 변환합니다.

사용법:
    # Dry run (시뮬레이션)
    python scripts/migrate_workflows_to_v2.py --dry-run

    # 실제 마이그레이션
    python scripts/migrate_workflows_to_v2.py

    # 특정 봇만 마이그레이션
    python scripts/migrate_workflows_to_v2.py --bot-id abc-123

    # Verbose 모드
    python scripts/migrate_workflows_to_v2.py --verbose
"""

import sys
import os
import asyncio
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal
from app.models.bot import Bot
from app.models.workflow_version import BotWorkflowVersion
from app.schemas.workflow import WorkflowVersionStatus


class WorkflowMigrationError(Exception):
    """마이그레이션 오류"""
    pass


def infer_ports_for_node_type(node_type: str) -> Dict[str, Any]:
    """
    노드 타입별 포트 스키마 추론

    Args:
        node_type: 노드 타입 (start, knowledge, llm, end)

    Returns:
        Dict: 포트 스키마 정의
    """
    port_schemas = {
        "start": {
            "inputs": [],
            "outputs": [
                {
                    "name": "query",
                    "type": "string",
                    "required": True,
                    "description": "사용자 질문 또는 메시지",
                    "display_name": "사용자 질문"
                },
                {
                    "name": "session_id",
                    "type": "string",
                    "required": False,
                    "description": "세션 식별자",
                    "display_name": "세션 ID"
                }
            ]
        },
        "knowledge": {
            "inputs": [
                {
                    "name": "query",
                    "type": "string",
                    "required": True,
                    "description": "검색할 쿼리 텍스트",
                    "display_name": "검색 쿼리"
                }
            ],
            "outputs": [
                {
                    "name": "context",
                    "type": "string",
                    "required": True,
                    "description": "검색된 문서들을 병합한 컨텍스트 텍스트",
                    "display_name": "컨텍스트"
                },
                {
                    "name": "documents",
                    "type": "array",
                    "required": False,
                    "description": "검색된 문서 목록 (메타데이터 포함)",
                    "display_name": "문서 목록"
                },
                {
                    "name": "doc_count",
                    "type": "number",
                    "required": False,
                    "description": "검색된 문서 개수",
                    "display_name": "문서 개수"
                }
            ]
        },
        "llm": {
            "inputs": [
                {
                    "name": "query",
                    "type": "string",
                    "required": True,
                    "description": "사용자 질문",
                    "display_name": "질문"
                },
                {
                    "name": "context",
                    "type": "string",
                    "required": False,
                    "description": "컨텍스트 정보 (검색 결과 등)",
                    "display_name": "컨텍스트"
                },
                {
                    "name": "system_prompt",
                    "type": "string",
                    "required": False,
                    "description": "시스템 프롬프트",
                    "display_name": "시스템 프롬프트"
                }
            ],
            "outputs": [
                {
                    "name": "response",
                    "type": "string",
                    "required": True,
                    "description": "LLM 생성 응답",
                    "display_name": "응답"
                },
                {
                    "name": "tokens",
                    "type": "number",
                    "required": False,
                    "description": "사용된 토큰 수",
                    "display_name": "토큰 수"
                },
                {
                    "name": "model",
                    "type": "string",
                    "required": False,
                    "description": "사용된 모델명",
                    "display_name": "모델"
                }
            ]
        },
        "end": {
            "inputs": [
                {
                    "name": "response",
                    "type": "string",
                    "required": True,
                    "description": "최종 응답 텍스트",
                    "display_name": "응답"
                }
            ],
            "outputs": [
                {
                    "name": "final_output",
                    "type": "object",
                    "required": True,
                    "description": "최종 결과 객체",
                    "display_name": "최종 결과"
                }
            ]
        }
    }

    return port_schemas.get(node_type, {"inputs": [], "outputs": []})


def infer_port_connections(edges: List[Dict], nodes: List[Dict]) -> List[Dict]:
    """
    엣지에서 포트 연결 정보 추론

    Args:
        edges: 기존 엣지 목록
        nodes: 노드 목록 (포트 정보 포함)

    Returns:
        List[Dict]: 포트 정보가 추가된 엣지 목록
    """
    # 노드 타입 맵 생성
    node_type_map = {node["id"]: node["type"] for node in nodes}

    v2_edges = []
    for edge in edges:
        source_node_type = node_type_map.get(edge["source"])
        target_node_type = node_type_map.get(edge["target"])

        if not source_node_type or not target_node_type:
            continue

        # 포트 이름 추론
        source_port, target_port = infer_port_names(
            source_node_type,
            target_node_type
        )

        v2_edge = {
            "id": edge["id"],
            "source": edge["source"],
            "target": edge["target"],
            "source_port": source_port,
            "target_port": target_port,
            "data_type": "string"  # 기본값
        }

        v2_edges.append(v2_edge)

    return v2_edges


def infer_port_names(source_type: str, target_type: str) -> Tuple[str, str]:
    """
    노드 타입 쌍에서 포트 이름 추론

    Args:
        source_type: 소스 노드 타입
        target_type: 타겟 노드 타입

    Returns:
        Tuple[str, str]: (source_port, target_port)
    """
    # 일반적인 연결 패턴
    port_mappings = {
        ("start", "knowledge"): ("query", "query"),
        ("start", "llm"): ("query", "query"),
        ("knowledge", "llm"): ("context", "context"),
        ("llm", "end"): ("response", "response"),
    }

    return port_mappings.get((source_type, target_type), ("output", "input"))


def create_variable_mappings(edges: List[Dict], node_id: str) -> Dict[str, Any]:
    """
    특정 노드의 입력 포트에 대한 변수 매핑 생성

    Args:
        edges: V2 엣지 목록
        node_id: 노드 ID

    Returns:
        Dict: 변수 매핑 {port_name: {variable: "source_node.source_port"}}
    """
    mappings = {}

    for edge in edges:
        if edge["target"] == node_id and edge.get("target_port"):
            mappings[edge["target_port"]] = {
                "variable": f"{edge['source']}.{edge['source_port']}",
                "value_type": edge.get("data_type", "string")
            }

    return mappings


def convert_legacy_workflow_to_v2(legacy_workflow: Dict[str, Any]) -> Dict[str, Any]:
    """
    기존 워크플로우를 V2 그래프로 변환

    Args:
        legacy_workflow: 기존 워크플로우 JSON

    Returns:
        Dict: V2 그래프

    Raises:
        WorkflowMigrationError: 변환 실패 시
    """
    if not legacy_workflow or not isinstance(legacy_workflow, dict):
        raise WorkflowMigrationError("Invalid legacy workflow format")

    nodes = legacy_workflow.get("nodes", [])
    edges = legacy_workflow.get("edges", [])

    if not nodes:
        raise WorkflowMigrationError("No nodes found in workflow")

    # Step 1: 노드에 포트 정보 추가
    v2_nodes = []
    for node in nodes:
        node_type = node.get("type")
        if not node_type:
            raise WorkflowMigrationError(f"Node {node.get('id')} has no type")

        # 포트 스키마 추가
        ports = infer_ports_for_node_type(node_type)

        v2_node = {
            "id": node["id"],
            "type": node["type"],
            "position": node.get("position", {"x": 0, "y": 0}),
            "data": node.get("data", {}),
            "ports": ports,
            "variable_mappings": {}  # 나중에 채워짐
        }

        v2_nodes.append(v2_node)

    # Step 2: 엣지에 포트 정보 추가
    v2_edges = infer_port_connections(edges, v2_nodes)

    # Step 3: 각 노드의 변수 매핑 생성
    for node in v2_nodes:
        node["variable_mappings"] = create_variable_mappings(v2_edges, node["id"])

    return {
        "nodes": v2_nodes,
        "edges": v2_edges
    }


async def migrate_bot_to_v2(
    db: Session,
    bot: Bot,
    dry_run: bool = False,
    verbose: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    개별 봇을 V2로 마이그레이션

    Args:
        db: 데이터베이스 세션
        bot: 봇 객체
        dry_run: True면 실제 변경하지 않음
        verbose: 상세 로그 출력

    Returns:
        Tuple[bool, Optional[str]]: (성공 여부, 오류 메시지)
    """
    bot_id = str(bot.bot_id)

    # 워크플로우가 없으면 스킵
    if not bot.workflow:
        if verbose:
            print(f"  ⏭️  봇 {bot_id}: 워크플로우 없음, 스킵")
        return True, None

    # 이미 V2를 사용 중이면 스킵
    if bot.use_workflow_v2:
        if verbose:
            print(f"  ⏭️  봇 {bot_id}: 이미 V2 사용 중, 스킵")
        return True, None

    try:
        # V2 그래프로 변환
        v2_graph = convert_legacy_workflow_to_v2(bot.workflow)

        if dry_run:
            if verbose:
                print(f"  ✅ 봇 {bot_id}: 변환 성공 (dry run)")
                print(f"     노드 수: {len(v2_graph['nodes'])}, 엣지 수: {len(v2_graph['edges'])}")
            return True, None

        # 기존 draft가 있는지 확인
        existing_draft = db.query(BotWorkflowVersion).filter(
            BotWorkflowVersion.bot_id == bot.bot_id,
            BotWorkflowVersion.status == WorkflowVersionStatus.DRAFT
        ).first()

        if existing_draft:
            # 기존 draft 업데이트
            existing_draft.graph = v2_graph
            existing_draft.updated_at = datetime.now()
            if verbose:
                print(f"  🔄 봇 {bot_id}: 기존 draft 업데이트")
        else:
            # 새 draft 생성
            draft = BotWorkflowVersion(
                bot_id=bot.bot_id,
                version="draft",
                status=WorkflowVersionStatus.DRAFT,
                graph=v2_graph,
                environment_variables={},
                created_by=bot.user_id if hasattr(bot, 'user_id') else None
            )
            db.add(draft)
            if verbose:
                print(f"  ➕ 봇 {bot_id}: 새 draft 생성")

        # 기존 워크플로우 백업
        if not bot.legacy_workflow:
            bot.legacy_workflow = bot.workflow
            if verbose:
                print(f"  💾 봇 {bot_id}: 기존 워크플로우 백업 완료")

        # use_workflow_v2는 수동 활성화를 위해 False 유지

        db.commit()

        print(f"  ✅ 봇 {bot_id}: 마이그레이션 완료")
        return True, None

    except Exception as e:
        error_msg = str(e)
        print(f"  ❌ 봇 {bot_id}: 마이그레이션 실패 - {error_msg}")
        db.rollback()
        return False, error_msg


async def main():
    """메인 실행 함수"""
    parser = argparse.ArgumentParser(
        description="워크플로우 V1 → V2 마이그레이션",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 변경 없이 시뮬레이션만 수행"
    )
    parser.add_argument(
        "--bot-id",
        help="특정 봇만 마이그레이션 (봇 ID 지정)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="상세한 로그 출력"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="마이그레이션할 최대 봇 수 제한"
    )

    args = parser.parse_args()

    # 데이터베이스 연결
    db = SessionLocal()

    try:
        print("=" * 60)
        print("워크플로우 V1 → V2 마이그레이션")
        print("=" * 60)

        if args.dry_run:
            print("⚠️  DRY RUN 모드: 실제 변경 없이 시뮬레이션만 수행합니다\n")

        # 마이그레이션 대상 봇 조회
        query = db.query(Bot).filter(Bot.workflow.isnot(None))

        if args.bot_id:
            query = query.filter(Bot.bot_id == args.bot_id)

        if args.limit:
            query = query.limit(args.limit)

        bots = query.all()

        if not bots:
            print("⚠️  마이그레이션할 봇이 없습니다.")
            return

        total_count = len(bots)
        print(f"📋 총 {total_count}개 봇 마이그레이션 시작...\n")

        # 마이그레이션 실행
        success_count = 0
        failed_count = 0
        skipped_count = 0

        for i, bot in enumerate(bots, 1):
            print(f"[{i}/{total_count}] 봇 처리 중...")

            success, error = await migrate_bot_to_v2(
                db=db,
                bot=bot,
                dry_run=args.dry_run,
                verbose=args.verbose
            )

            if success:
                if error is None:
                    success_count += 1
                else:
                    skipped_count += 1
            else:
                failed_count += 1

            print()

        # 결과 요약
        print("=" * 60)
        print("마이그레이션 완료")
        print("=" * 60)
        print(f"✅ 성공: {success_count}개")
        print(f"⏭️  스킵: {skipped_count}개")
        print(f"❌ 실패: {failed_count}개")
        print(f"📊 총계: {total_count}개")

        if args.dry_run:
            print("\n⚠️  DRY RUN 모드였으므로 실제 변경은 없습니다.")
            print("   실제 마이그레이션을 수행하려면 --dry-run 옵션 없이 실행하세요.")
        else:
            print("\n✅ 마이그레이션이 완료되었습니다!")
            print("   각 봇의 draft 버전을 검토한 후 발행(publish)하세요.")
            print("   발행 후 봇의 use_workflow_v2 플래그가 자동으로 활성화됩니다.")

    except Exception as e:
        print(f"\n❌ 치명적 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        db.close()

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
