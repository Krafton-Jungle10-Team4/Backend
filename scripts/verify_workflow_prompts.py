"""
워크플로우 프롬프트 템플릿 검증 스크립트

사용법:
    python scripts/verify_workflow_prompts.py

목적:
    - V2 워크플로우를 사용하는 모든 봇의 프롬프트 설정 검증
    - LLM 노드에 context 변수 포함 여부 확인
    - Knowledge 노드와 LLM 노드 간 매핑 확인
"""
import asyncio
import sys
from sqlalchemy import select
from app.core.database import get_async_session_context
from app.models.bot import Bot


async def verify_prompts():
    """워크플로우 프롬프트 검증 메인 함수"""
    async with get_async_session_context() as db:
        # V2 워크플로우를 사용하는 모든 봇 조회
        result = await db.execute(
            select(Bot).where(Bot.use_workflow_v2 == True)
        )
        bots = result.scalars().all()
        
        print(f"{'='*80}")
        print(f"워크플로우 프롬프트 검증 시작")
        print(f"{'='*80}\n")
        print(f"검사 대상 봇: {len(bots)}개\n")
        
        if not bots:
            print("⚠️ V2 워크플로우를 사용하는 봇이 없습니다.\n")
            return
        
        issues_found = 0
        
        for bot in bots:
            print(f"{'='*80}")
            print(f"봇 ID: {bot.bot_id}")
            print(f"봇 이름: {bot.name}")
            print(f"소유자 ID: {bot.user_id}")
            print(f"{'='*80}\n")
            
            # Published 워크플로우 로드
            try:
                from app.services.workflow_version_service import WorkflowVersionService
                service = WorkflowVersionService(db)
                version = await service.get_published_version(bot.bot_id)
                
                if not version:
                    print("  ⚠️ Published 워크플로우가 없습니다.")
                    print("  → Draft 버전 확인 중...\n")
                    
                    versions = await service.list_versions(bot.bot_id, status="draft")
                    if versions:
                        version = versions[0]
                        print(f"  ℹ️ Draft 버전 사용: version_id={version.id}\n")
                    else:
                        print("  ❌ 워크플로우 버전이 전혀 없습니다.\n")
                        issues_found += 1
                        continue
                
                graph = version.graph
                nodes = graph.get("nodes", [])
                edges = graph.get("edges", [])
                
                # 노드 타입별 분류
                llm_nodes = [n for n in nodes if n.get("type") == "llm"]
                knowledge_nodes = [n for n in nodes if n.get("type") == "knowledge"]
                start_nodes = [n for n in nodes if n.get("type") == "start"]
                end_nodes = [n for n in nodes if n.get("type") == "end"]
                
                print(f"  워크플로우 구조:")
                print(f"    - 전체 노드: {len(nodes)}개")
                print(f"    - Start 노드: {len(start_nodes)}개")
                print(f"    - Knowledge 노드: {len(knowledge_nodes)}개")
                print(f"    - LLM 노드: {len(llm_nodes)}개")
                print(f"    - End 노드: {len(end_nodes)}개")
                print(f"    - 엣지: {len(edges)}개\n")
                
                if not llm_nodes:
                    print("  ⚠️ LLM 노드가 없습니다.\n")
                    continue
                
                # 각 LLM 노드 검증
                for llm_node in llm_nodes:
                    node_id = llm_node.get("id")
                    data = llm_node.get("data", {})
                    prompt_template = data.get("prompt_template", "")
                    variable_mappings = data.get("variable_mappings", {})
                    
                    print(f"  {'─'*60}")
                    print(f"  LLM 노드: {node_id}")
                    print(f"  {'─'*60}\n")
                    
                    # 프롬프트 템플릿 분석
                    print(f"    📝 프롬프트 템플릿:")
                    if not prompt_template:
                        print(f"      ⚠️ 비어있음 (기본 템플릿 사용)")
                        print(f"      → 기본: '{{context}}\\n\\nQuestion: {{query}}\\nAnswer:'")
                    else:
                        print(f"      길이: {len(prompt_template)} chars")
                        print(f"      미리보기: {prompt_template[:200]}...")
                        
                        # context 변수 포함 여부 확인
                        has_simple_context = "{context}" in prompt_template
                        has_double_brace_context = "{{" in prompt_template and "context" in prompt_template.lower()
                        
                        if has_double_brace_context:
                            print(f"      ✅ {{ }} 형식의 context 변수 포함")
                        elif has_simple_context:
                            print(f"      ✅ {{context}} 형식의 context 변수 포함")
                        else:
                            print(f"      ❌ context 변수가 없음! 문서 기반 답변 불가능")
                            print(f"      → 프롬프트에 {{{{ knowledge_node_id.context }}}} 추가 필요")
                            issues_found += 1
                    
                    print()
                    
                    # Variable mappings 확인
                    print(f"    🔗 입력 포트 매핑:")
                    if not variable_mappings:
                        print(f"      ⚠️ 변수 매핑이 비어있음")
                    else:
                        for port_name, mapping in variable_mappings.items():
                            if mapping:
                                print(f"      - {port_name}: {mapping}")
                            else:
                                print(f"      - {port_name}: (매핑 없음)")
                        
                        context_mapping = variable_mappings.get("context")
                        if not context_mapping:
                            print(f"      ⚠️ context 입력 포트가 매핑되지 않음")
                            print(f"      → Knowledge 노드의 context 출력과 연결 필요")
                            issues_found += 1
                    
                    print()
                    
                    # 연결된 Knowledge 노드 찾기
                    print(f"    🔍 연결된 Knowledge 노드:")
                    connected_knowledge = []
                    for edge in edges:
                        if edge.get("target") == node_id:
                            source_id = edge.get("source")
                            source_node = next((n for n in nodes if n.get("id") == source_id), None)
                            if source_node and source_node.get("type") == "knowledge":
                                connected_knowledge.append(source_node)
                    
                    if connected_knowledge:
                        for kn in connected_knowledge:
                            kn_id = kn.get("id")
                            kn_data = kn.get("data", {})
                            top_k = kn_data.get("top_k", 5)
                            doc_ids = kn_data.get("document_ids", [])
                            print(f"      - {kn_id}")
                            print(f"        top_k: {top_k}")
                            print(f"        document_ids: {doc_ids if doc_ids else '전체 문서'}")
                    else:
                        print(f"      ⚠️ 연결된 Knowledge 노드가 없음")
                        print(f"      → 문서 기반 답변을 위해서는 Knowledge 노드 연결 필요")
                    
                    print()
                
            except Exception as e:
                print(f"  ❌ 오류 발생: {str(e)}")
                print(f"  → 스택 트레이스: {type(e).__name__}\n")
                issues_found += 1
            
            print()
        
        # 최종 요약
        print(f"\n{'='*80}")
        print(f"검증 완료")
        print(f"{'='*80}\n")
        
        if issues_found == 0:
            print("✅ 모든 워크플로우가 올바르게 설정되어 있습니다.\n")
        else:
            print(f"⚠️ {issues_found}개의 문제가 발견되었습니다.")
            print(f"→ 위의 권장사항을 참고하여 프론트엔드에서 워크플로우를 수정하세요.\n")


if __name__ == "__main__":
    try:
        asyncio.run(verify_prompts())
    except KeyboardInterrupt:
        print("\n\n중단되었습니다.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 예기치 않은 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

