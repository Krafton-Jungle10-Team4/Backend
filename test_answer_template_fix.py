"""
Answer 노드 템플릿 렌더링 수정 테스트

문제: {{1763380836167.response}} 같은 변수가 치환되지 않고 그대로 출력됨
원인: _compute_allowed_selectors가 template 내부 변수를 허용 목록에 추가하지 않음
수정: AnswerNodeV2에 _compute_allowed_selectors 오버라이드 추가
"""

import asyncio
import sys
import os

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.workflow.nodes_v2.answer_node_v2 import AnswerNodeV2
from app.core.workflow.base_node_v2 import NodeExecutionContext
from app.core.workflow.variable_pool import VariablePool
from app.core.workflow.service_container import ServiceContainer


async def test_answer_template_rendering():
    """Answer 노드 템플릿 렌더링 테스트"""

    print("=" * 80)
    print("Answer 노드 템플릿 렌더링 테스트")
    print("=" * 80)

    # 1. VariablePool 초기화 및 LLM 응답 저장
    variable_pool = VariablePool()

    # LLM 노드 출력 시뮬레이션 (노드 ID: 1763380836167)
    llm_node_id = "1763380836167"
    llm_response = "안녕하세요! 이것은 LLM이 생성한 실제 응답입니다."

    variable_pool.set_node_output(llm_node_id, "response", llm_response)
    variable_pool.set_node_output(llm_node_id, "tokens", 50)
    variable_pool.set_node_output(llm_node_id, "model", "claude-sonnet-4-5")

    print(f"\n✅ LLM 노드 출력 저장:")
    print(f"   노드 ID: {llm_node_id}")
    print(f"   response: {llm_response}")
    print(f"   tokens: 50")
    print(f"   model: claude-sonnet-4-5")

    # 2. Answer 노드 생성
    answer_node = AnswerNodeV2(
        node_id="answer-1",
        config={
            "template": f"{{{{{llm_node_id}.response}}}}"  # {{1763380836167.response}}
        },
        variable_mappings={}  # 중요: template 변수는 variable_mappings에 없음!
    )

    print(f"\n✅ Answer 노드 생성:")
    print(f"   노드 ID: answer-1")
    print(f"   템플릿: {{{{{llm_node_id}.response}}}}")
    print(f"   variable_mappings: {{}}")

    # 3. ServiceContainer 생성
    service_container = ServiceContainer()

    # 4. NodeExecutionContext 생성
    context = NodeExecutionContext(
        node_id="answer-1",
        variable_pool=variable_pool,
        service_container=service_container,
        metadata={"prepared_inputs": {}}
    )

    # 5. _compute_allowed_selectors 호출 확인
    print(f"\n🔍 allowed_selectors 계산:")
    allowed_selectors = answer_node._compute_allowed_selectors(context)
    print(f"   결과: {allowed_selectors}")

    expected_selector = f"{llm_node_id}.response"
    if expected_selector in allowed_selectors:
        print(f"   ✅ '{expected_selector}'가 허용 목록에 포함됨!")
    else:
        print(f"   ❌ '{expected_selector}'가 허용 목록에 없음! (수정 실패)")
        return False

    # 6. Answer 노드 실행
    print(f"\n🚀 Answer 노드 실행:")
    try:
        result = await answer_node.execute(context)

        if result.status.value == "completed":
            final_output = result.output.get("final_output", "")
            print(f"   상태: {result.status.value}")
            print(f"   출력: {final_output}")

            # 7. 결과 검증
            print(f"\n🧪 결과 검증:")
            if final_output == llm_response:
                print(f"   ✅ 성공! 템플릿이 실제 값으로 치환되었습니다!")
                print(f"   기대값: {llm_response}")
                print(f"   실제값: {final_output}")
                return True
            else:
                print(f"   ❌ 실패! 템플릿이 치환되지 않았습니다.")
                print(f"   기대값: {llm_response}")
                print(f"   실제값: {final_output}")
                return False
        else:
            print(f"   ❌ 실행 실패: {result.status.value}")
            print(f"   에러: {result.error}")
            return False

    except Exception as e:
        print(f"   ❌ 예외 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """메인 함수"""
    success = await test_answer_template_rendering()

    print("\n" + "=" * 80)
    if success:
        print("✅ 테스트 성공! Answer 노드 템플릿 렌더링이 정상 작동합니다.")
    else:
        print("❌ 테스트 실패! 추가 디버깅이 필요합니다.")
    print("=" * 80)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
