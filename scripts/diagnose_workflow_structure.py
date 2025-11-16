#!/usr/bin/env python3
"""
워크플로우 구조 진단 스크립트

실행 순서 문제를 진단하고 잘못된 엣지를 찾아냅니다.
"""

import sys
import os
from collections import defaultdict, deque
from typing import Dict, List, Set

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.data.workflow_v2_feedback_graph import FEEDBACK_WORKFLOW_GRAPH


def analyze_workflow_structure(workflow_data: Dict) -> None:
    """워크플로우 구조 분석"""
    nodes = workflow_data.get("nodes", [])
    edges = workflow_data.get("edges", [])
    
    # 노드 ID → 노드 타입 맵
    node_types = {node["id"]: node["type"] for node in nodes}
    
    # 엣지를 source → targets로 그룹화
    outgoing_edges = defaultdict(list)
    incoming_edges = defaultdict(list)
    
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        source_port = edge.get("source_port", "default")
        target_port = edge.get("target_port", "")
        
        outgoing_edges[source].append({
            "target": target,
            "source_port": source_port,
            "target_port": target_port,
            "edge_id": edge["id"]
        })
        
        incoming_edges[target].append({
            "source": source,
            "source_port": source_port,
            "target_port": target_port,
            "edge_id": edge["id"]
        })
    
    print("=" * 80)
    print("워크플로우 구조 진단 리포트")
    print("=" * 80)
    print()
    
    # 1. Start 노드 분석
    print("📍 Start 노드 분석")
    print("-" * 80)
    start_nodes = [n["id"] for n in nodes if n["type"] == "start"]
    if start_nodes:
        start_id = start_nodes[0]
        print(f"Start 노드: {start_id}")
        print(f"직접 연결된 노드 수: {len(outgoing_edges[start_id])}")
        print()
        print("직접 연결된 노드들:")
        for edge in outgoing_edges[start_id]:
            target = edge["target"]
            target_type = node_types.get(target, "unknown")
            print(f"  - {target} ({target_type})")
            print(f"    source_port: {edge['source_port']}")
            print(f"    target_port: {edge['target_port']}")
            print(f"    edge_id: {edge['edge_id']}")
            print()
    print()
    
    # 2. 분기 노드 분석
    print("🔀 분기 노드 분석 (IF-ELSE, Question Classifier)")
    print("-" * 80)
    branch_nodes = [n for n in nodes if n["type"] in ["if-else", "question-classifier"]]
    for node in branch_nodes:
        node_id = node["id"]
        node_type = node["type"]
        print(f"\n노드: {node_id} ({node_type})")
        print(f"입력 엣지 수: {len(incoming_edges[node_id])}")
        print(f"출력 엣지 수: {len(outgoing_edges[node_id])}")
        
        print("\n입력 엣지:")
        for edge in incoming_edges[node_id]:
            source = edge["source"]
            source_type = node_types.get(source, "unknown")
            print(f"  ← {source} ({source_type}) via port '{edge['source_port']}'")
        
        print("\n출력 엣지 (분기별):")
        branches = defaultdict(list)
        for edge in outgoing_edges[node_id]:
            branches[edge['source_port']].append(edge)
        
        for branch_name, branch_edges in branches.items():
            print(f"  분기 '{branch_name}':")
            for edge in branch_edges:
                target = edge["target"]
                target_type = node_types.get(target, "unknown")
                print(f"    → {target} ({target_type})")
    print()
    
    # 3. 의존성 문제 진단
    print("⚠️  잠재적 문제 진단")
    print("-" * 80)
    
    problems = []
    
    # 문제 1: Start 노드가 너무 많은 노드에 직접 연결
    if start_nodes:
        start_id = start_nodes[0]
        direct_connections = len(outgoing_edges[start_id])
        if direct_connections > 1:
            problems.append({
                "severity": "HIGH",
                "type": "start_fanout",
                "message": f"Start 노드가 {direct_connections}개의 노드에 직접 연결되어 있습니다.",
                "details": f"Start 노드는 일반적으로 하나의 entry point에만 연결되어야 합니다.",
                "affected_nodes": [e["target"] for e in outgoing_edges[start_id]]
            })
    
    # 문제 2: 변수 매핑이 없는 노드에 대한 데이터 엣지
    for node in nodes:
        node_id = node["id"]
        if node["type"] == "start":
            continue
        
        var_mappings = node.get("variable_mappings", {})
        incoming = incoming_edges[node_id]
        
        # 입력 엣지가 있지만 variable_mappings이 비어있는 경우
        if incoming and not var_mappings and node["type"] not in ["end", "answer"]:
            problems.append({
                "severity": "MEDIUM",
                "type": "missing_mappings",
                "message": f"노드 {node_id} ({node['type']})에 입력 엣지가 있지만 variable_mappings이 비어있습니다.",
                "details": "데이터가 전달되지 않을 수 있습니다.",
                "affected_nodes": [node_id]
            })
    
    # 문제 3: 순환 참조 감지
    def has_cycle() -> bool:
        visited = set()
        rec_stack = set()
        
        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            
            for edge in outgoing_edges[node_id]:
                target = edge["target"]
                if target not in visited:
                    if dfs(target):
                        return True
                elif target in rec_stack:
                    return True
            
            rec_stack.remove(node_id)
            return False
        
        for node in nodes:
            node_id = node["id"]
            if node_id not in visited:
                if dfs(node_id):
                    return True
        return False
    
    if has_cycle():
        problems.append({
            "severity": "CRITICAL",
            "type": "cycle",
            "message": "워크플로우에 순환 참조가 있습니다.",
            "details": "순환 참조는 무한 루프를 발생시킬 수 있습니다.",
            "affected_nodes": []
        })
    
    # 문제 출력
    if problems:
        for i, problem in enumerate(problems, 1):
            severity_emoji = {
                "CRITICAL": "🔴",
                "HIGH": "🟠",
                "MEDIUM": "🟡",
                "LOW": "🔵"
            }
            emoji = severity_emoji.get(problem["severity"], "⚪")
            
            print(f"\n{emoji} 문제 {i}: [{problem['severity']}] {problem['type']}")
            print(f"   {problem['message']}")
            print(f"   {problem['details']}")
            if problem['affected_nodes']:
                print(f"   영향받는 노드: {', '.join(problem['affected_nodes'])}")
    else:
        print("✅ 잠재적인 구조 문제가 발견되지 않았습니다.")
    
    print()
    print()
    
    # 4. 권장 수정사항
    print("💡 권장 수정사항")
    print("-" * 80)
    
    if start_nodes:
        start_id = start_nodes[0]
        direct_connections = outgoing_edges[start_id]
        
        if len(direct_connections) > 1:
            print("\n1. Start 노드의 직접 연결 제거")
            print("   현재 Start 노드가 다음 노드들에 직접 연결되어 있습니다:")
            
            router_connections = []
            other_connections = []
            
            for edge in direct_connections:
                target = edge["target"]
                target_type = node_types.get(target, "unknown")
                if target_type in ["if-else", "question-classifier"]:
                    router_connections.append(edge)
                else:
                    other_connections.append(edge)
            
            if router_connections and other_connections:
                print("\n   ✅ 유지해야 할 엣지 (라우터/분기 노드):")
                for edge in router_connections:
                    target = edge["target"]
                    target_type = node_types.get(target, "unknown")
                    print(f"      - start-1 → {target} ({target_type})")
                
                print("\n   ❌ 제거해야 할 엣지 (직접 연결):")
                for edge in other_connections:
                    target = edge["target"]
                    target_type = node_types.get(target, "unknown")
                    print(f"      - edge_id: {edge['edge_id']}")
                    print(f"        start-1 → {target} ({target_type})")
                    print(f"        이유: 이 노드는 라우터를 통해 간접적으로 연결되어야 합니다.")
                
                print("\n   수정 방법:")
                print("   1) 잘못된 엣지를 edges 리스트에서 제거")
                print("   2) 각 노드는 proper 순서대로 연결되도록 수정")
                print("   3) 변수 전달은 variable_mappings를 통해 처리")


def main():
    print("\n워크플로우 구조 진단 시작...\n")
    analyze_workflow_structure(FEEDBACK_WORKFLOW_GRAPH)
    print("\n진단 완료.\n")


if __name__ == "__main__":
    main()

