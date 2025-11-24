"""
워크플로우 검증기

워크플로우의 유효성을 검사하는 모듈입니다.
순환 참조, 고립 노드, 필수 노드 확인 등의 검증을 수행합니다.
"""

from typing import Dict, List, Set, Tuple, Optional, Any
from collections import defaultdict, deque
from app.core.workflow.base_node import BaseNode, NodeType
from app.core.workflow.node_registry import node_registry
from app.core.workflow.node_registry_v2 import node_registry_v2
from app.core.workflow.nodes_v2.utils.template_renderer import (
    TemplateRenderer,
    TemplateRenderError
)
from app.schemas.workflow import PortType
import logging

logger = logging.getLogger(__name__)


class WorkflowValidationError(Exception):
    """워크플로우 검증 오류"""
    pass


class WorkflowValidator:
    """
    워크플로우 검증기

    워크플로우의 구조적 무결성과 논리적 일관성을 검증합니다.
    """

    _SPECIAL_VARIABLE_PREFIXES = {
        "env": {"env", "environment"},
        "conversation": {"conv", "conversation"},
        "sys": {"sys", "system"},
    }
    _HANDLE_PLACEHOLDERS = {"source", "target", "default", "input", "output"}

    def __init__(self):
        """검증기 초기화"""
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]]
    ) -> Tuple[bool, List[str], List[str]]:
        """
        워크플로우 전체 검증

        Args:
            nodes: 노드 리스트
            edges: 엣지 리스트

        Returns:
            Tuple: (유효 여부, 오류 리스트, 경고 리스트)
        """
        self.errors = []
        self.warnings = []

        # 기본 검증
        if not nodes:
            self.errors.append("워크플로우에 노드가 없습니다")
            return False, self.errors, self.warnings

        # 노드 맵 생성
        node_map = {node["id"]: node for node in nodes}

        # 엣지 맵 생성
        adjacency_list = self._build_adjacency_list(edges, node_map)

        # 검증 수행
        self._validate_required_nodes(nodes)
        self._validate_node_configurations(nodes)
        self._validate_edges(edges, node_map)
        self._validate_connectivity(node_map, adjacency_list)
        self._validate_no_cycles(adjacency_list)
        self._validate_isolated_nodes(node_map, adjacency_list)
        self._validate_node_constraints(nodes, adjacency_list)
        self._validate_execution_order(adjacency_list)

        # V2 포트/변수 검증 (필요 시)
        if self._is_v2_workflow(nodes, edges):
            self._normalize_v2_graph(nodes, edges, node_map)
            self._validate_v2_connections(nodes, edges)
            self._validate_v2_schema(nodes, edges, node_map)
            self._validate_branch_convergence(nodes, edges, node_map)
            self._validate_template_variable_connectivity(nodes, edges, node_map)

        is_valid = len(self.errors) == 0
        return is_valid, self.errors, self.warnings

    def _build_adjacency_list(
        self,
        edges: List[Dict[str, Any]],
        node_map: Dict[str, Dict]
    ) -> Dict[str, List[str]]:
        """
        인접 리스트 생성

        Args:
            edges: 엣지 리스트
            node_map: 노드 맵

        Returns:
            인접 리스트
        """
        adjacency_list = defaultdict(list)
        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
            if source and target:
                # 특수 프리픽스(conv/env/sys)는 실제 노드가 아니므로 그래프 구조에서 제외
                # 이들은 variable_mappings로 변환되어 데이터 흐름에 사용되지만,
                # DAG 구조 계산에는 포함되지 않아야 합니다.
                if self._resolve_special_prefix(source):
                    continue
                if self._resolve_special_prefix(target):
                    continue
                adjacency_list[source].append(target)
        return dict(adjacency_list)

    def _has_branch_nodes(self, nodes: List[Dict[str, Any]]) -> bool:
        """
        워크플로우에 분기 노드가 있는지 확인

        분기 노드(question-classifier, if-else 등)가 있는 경우
        여러 End 노드를 허용하기 위해 사용합니다.

        Args:
            nodes: 노드 리스트

        Returns:
            bool: 분기 노드가 있으면 True, 없으면 False
        """
        branch_node_types = {"if-else", "question-classifier"}
        for node in nodes:
            # V1 노드 타입 확인
            node_type = node.get("type")
            if node_type in branch_node_types:
                return True

            # V2 노드 타입 확인 (data.type)
            node_data_type = node.get("data", {}).get("type")
            if node_data_type in branch_node_types:
                return True

        return False

    def _validate_required_nodes(self, nodes: List[Dict[str, Any]]):
        """필수 노드 존재 여부 검증"""
        node_types = {node.get("type") for node in nodes}

        # Start 노드 검증
        start_count = sum(1 for node in nodes if node.get("type") == NodeType.START.value)
        if start_count == 0:
            self.errors.append("Start 노드가 필요합니다")
        elif start_count > 1:
            self.errors.append("Start 노드는 하나만 있어야 합니다")

        # End 노드 검증
        end_count = sum(1 for node in nodes if node.get("type") == NodeType.END.value)
        if end_count == 0:
            self.errors.append("End 노드가 필요합니다")
        elif end_count > 1:
            # 분기 노드가 있는 경우 여러 End 노드 허용
            if not self._has_branch_nodes(nodes):
                self.errors.append("End 노드는 하나만 있어야 합니다")
            else:
                logger.info(
                    f"분기 노드가 감지되어 여러 End 노드({end_count}개)를 허용합니다. "
                    "각 분기가 독립적인 종료 지점을 가질 수 있습니다."
                )

        # Answer 노드 검증 (V2 그래프에만 적용)
        if self._is_v2_workflow(nodes=nodes, edges=[]):
            answer_nodes = [
                node for node in nodes
                if node.get("data", {}).get("type") == "answer"
            ]
            if not answer_nodes:
                self.errors.append(
                    "워크플로우에 Answer 노드가 필요합니다. "
                    "최종 응답을 생성하려면 Answer 노드를 추가하세요."
                )

    def _validate_node_configurations(self, nodes: List[Dict[str, Any]]):
        """각 노드의 설정 검증"""
        node_ids = {node.get("id") for node in nodes}

        for node in nodes:
            node_id = node.get("id")
            node_type = node.get("type")
            node_data = node.get("data", {})

            if not node_id:
                self.errors.append("노드 ID가 없는 노드가 있습니다")
                continue

            if not node_type:
                self.errors.append(f"노드 {node_id}의 타입이 없습니다")
                continue

            # Answer 노드 특별 검증
            if node_data.get("type") == "answer":
                template = node_data.get("template", "")
                if not template or template.strip() == "":
                    self.errors.append(
                        f"Answer 노드 '{node_id}'의 템플릿이 비어있습니다. "
                        "최종 응답 내용을 입력하세요."
                    )
                    continue

                try:
                    variables = TemplateRenderer.parse_template(template)
                except TemplateRenderError as exc:
                    self.errors.append(
                        f"Answer 노드 '{node_id}'의 템플릿 문법 오류: {exc}"
                    )
                    continue

                for var_ref in variables:
                    prefix = var_ref.split(".", 1)[0]
                    if prefix in {"sys", "env", "conv"}:
                        continue
                    if prefix not in node_ids:
                        self.errors.append(
                            f"Answer 노드의 변수 참조 '{var_ref}'에서 "
                            f"노드 '{prefix}'를 찾을 수 없습니다."
                        )

            # 노드 타입별 설정 검증
            # V2 노드인 경우 data.type을 우선 확인
            v2_node_type = node_data.get("type")
            if v2_node_type:
                # V2 노드는 node_registry_v2에서 확인
                v2_node_class = node_registry_v2.get(v2_node_type)
                if v2_node_class:
                    # V2 노드는 검증 통과
                    continue
                elif node.get("ports") or node.get("variable_mappings"):
                    # 포트나 변수 매핑이 있으면 V2 노드로 간주
                    continue

            # V1 노드 검증
            try:
                node_type_enum = NodeType(node_type)
                node_class = node_registry.get(node_type_enum)

                if node_class:
                    # 설정 클래스로 검증
                    config_class = node_class.get_config_class()
                    if node_data and config_class != type(None):
                        try:
                            config = config_class(**node_data)
                        except Exception as e:
                            self.errors.append(f"노드 {node_id}의 설정이 유효하지 않습니다: {str(e)}")
                else:
                    # V2 노드는 node_registry에 등록되지 않을 수 있으므로 ports가 있으면 경고 생략
                    if node.get("ports"):
                        continue
                    self.warnings.append(f"알 수 없는 노드 타입: {node_type}")

            except ValueError:
                # V2 노드는 NodeType enum에 존재하지 않을 수 있으므로 포트 정보가 있으면 통과
                if node.get("ports") or node.get("variable_mappings"):
                    continue
                self.errors.append(f"유효하지 않은 노드 타입: {node_type}")

    def _validate_edges(
        self,
        edges: List[Dict[str, Any]],
        node_map: Dict[str, Dict]
    ):
        """엣지 유효성 검증"""
        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")

            if not source or not target:
                self.errors.append("Source 또는 Target이 없는 엣지가 있습니다")
                continue

            if source not in node_map:
                if not self._resolve_special_prefix(source):
                    self.errors.append(f"존재하지 않는 Source 노드: {source}")

            if target not in node_map:
                self.errors.append(f"존재하지 않는 Target 노드: {target}")

            # 자기 자신으로의 엣지 확인
            if source == target:
                self.errors.append(f"자기 자신으로의 엣지는 허용되지 않습니다: {source}")

    def _validate_connectivity(
        self,
        node_map: Dict[str, Dict],
        adjacency_list: Dict[str, List[str]]
    ):
        """노드 연결성 검증"""
        # Start 노드가 다른 노드와 연결되어 있는지 확인
        start_nodes = [node_id for node_id, node in node_map.items()
                      if node.get("type") == NodeType.START.value]

        for start_node in start_nodes:
            if start_node not in adjacency_list or not adjacency_list[start_node]:
                self.errors.append(f"Start 노드 {start_node}가 다른 노드와 연결되어 있지 않습니다")

        # End 노드로 들어오는 연결이 있는지 확인
        end_nodes = [node_id for node_id, node in node_map.items()
                    if node.get("type") == NodeType.END.value]

        incoming = defaultdict(list)
        for source, targets in adjacency_list.items():
            for target in targets:
                incoming[target].append(source)

        for end_node in end_nodes:
            if end_node not in incoming or not incoming[end_node]:
                self.errors.append(f"End 노드 {end_node}로 들어오는 연결이 없습니다")

    def _is_v2_workflow(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]]
    ) -> bool:
        """포트/변수 기반 V2 워크플로우인지 여부"""
        for node in nodes:
            if node.get("ports") or node.get("variable_mappings"):
                return True
        for edge in edges:
            if edge.get("source_port") or edge.get("target_port"):
                return True
        return False

    def _normalize_v2_graph(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        node_map: Dict[str, Dict[str, Any]]
    ) -> None:
        """V2 그래프 포트/변수 정보를 보강"""
        port_map: Dict[str, Dict[str, Dict[str, Any]]] = {
            node.get("id"): self._resolve_port_map(node)
            for node in nodes if node.get("id")
        }

        self._normalize_edge_ports(edges, port_map)
        self._normalize_variable_mappings(nodes, edges, port_map)

        for node in nodes:
            node_id = node.get("id")
            if node_id:
                node_map[node_id] = node

    def _normalize_edge_ports(
        self,
        edges: List[Dict[str, Any]],
        port_map: Dict[str, Dict[str, Dict[str, Any]]]
    ) -> None:
        """placeholder 포트 핸들을 스키마 기반 포트명으로 대체"""
        for edge in edges:
            source_id = edge.get("source")
            target_id = edge.get("target")
            if not source_id or not target_id:
                continue

            source_ports = port_map.get(source_id, {}).get("outputs", {})
            target_ports = port_map.get(target_id, {}).get("inputs", {})

            source_port = edge.get("source_port")
            normalized_source = self._infer_port_name(
                source_port,
                source_ports,
                self._HANDLE_PLACEHOLDERS
            )
            if normalized_source:
                edge["source_port"] = normalized_source

            target_port = edge.get("target_port")
            normalized_target = self._infer_port_name(
                target_port,
                target_ports,
                self._HANDLE_PLACEHOLDERS
            )
            if normalized_target:
                edge["target_port"] = normalized_target

            if not edge.get("data_type") and normalized_source in source_ports:
                edge["data_type"] = source_ports[normalized_source].get("type")

    @staticmethod
    def _infer_port_name(
        provided: Optional[str],
        available: Dict[str, Dict[str, Any]],
        placeholders: Set[str]
    ) -> Optional[str]:
        """포트 이름을 추론"""
        if not available:
            return provided

        provided_name = provided or ""

        if provided_name and provided_name in available:
            return provided_name

        lowered = provided_name.lower() if isinstance(provided_name, str) else ""
        should_infer = (not provided_name) or (lowered in placeholders)

        if not should_infer:
            return provided

        inferred = WorkflowValidator._pick_preferred_port_name(available)
        return inferred or provided

    @staticmethod
    def _pick_preferred_port_name(ports: Dict[str, Dict[str, Any]]) -> Optional[str]:
        """필수 포트를 우선으로 기본 포트를 선택"""
        for name, meta in ports.items():
            if meta.get("required", True):
                return name
        for name in ports.keys():
            return name
        return None

    def _normalize_variable_mappings(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        port_map: Dict[str, Dict[str, Dict[str, Any]]]
    ) -> None:
        """입력 포트에 대한 variable_mappings 자동 생성 (필수 및 선택적 포트 모두)"""
        incoming_edges: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            target_id = edge.get("target")
            if target_id:
                incoming_edges[target_id].append(edge)

        for node in nodes:
            node_id = node.get("id")
            if not node_id:
                continue

            normalized_mappings = self._coerce_variable_mappings(node.get("variable_mappings"))
            node["variable_mappings"] = normalized_mappings

            input_ports = port_map.get(node_id, {}).get("inputs", {})
            for port_name, meta in input_ports.items():
                # 이미 매핑이 있는 경우 건너뛰기
                existing_selector = self._extract_selector(normalized_mappings.get(port_name))
                if existing_selector:
                    continue

                # 엣지에서 해당 포트로 연결된 것을 찾기
                candidate_edge = None
                for edge in incoming_edges.get(node_id, []):
                    source = edge.get("source")
                    source_port = edge.get("source_port")
                    if not source or not source_port:
                        continue

                    normalized_target = self._infer_port_name(
                        edge.get("target_port"),
                        input_ports,
                        self._HANDLE_PLACEHOLDERS
                    )
                    if normalized_target == port_name:
                        if normalized_target and edge.get("target_port") != normalized_target:
                            edge["target_port"] = normalized_target
                        candidate_edge = edge
                        break

                if not candidate_edge:
                    compatible_edges = []
                    for edge in incoming_edges.get(node_id, []):
                        source = edge.get("source")
                        source_port = edge.get("source_port")
                        if not source or not source_port:
                            continue

                        source_meta = port_map.get(source, {}).get("outputs", {}).get(source_port, {})
                        source_type = source_meta.get("type")
                        target_type = meta.get("type")
                        if self._is_port_type_compatible(source_type, target_type):
                            compatible_edges.append(edge)

                    if len(compatible_edges) == 1:
                        candidate_edge = compatible_edges[0]
                        if not candidate_edge.get("target_port"):
                            candidate_edge["target_port"] = port_name

                # 입력 포트가 하나만 있는 경우 target_port가 비어도 허용
                if not candidate_edge and len(input_ports) == 1:
                    candidate_edge = next(
                        (
                            edge for edge in incoming_edges.get(node_id, [])
                            if edge.get("source") and edge.get("source_port")
                        ),
                        None
                    )
                    if candidate_edge:
                        candidate_edge["target_port"] = port_name

                if candidate_edge:
                    # 특수 프리픽스(env/conv/sys) 처리
                    special_prefix = self._resolve_special_prefix(candidate_edge.get("source"))
                    if special_prefix:
                        variable_key = candidate_edge.get("source_port")
                        if variable_key:
                            normalized_mappings[port_name] = f"{special_prefix}.{variable_key}"
                        else:
                            self.errors.append(
                                f"노드 {node_id}의 입력 '{port_name}'가 "
                                f"{special_prefix} 변수를 참조하지만 source_port가 비어 있습니다"
                            )
                        continue

                    # 엣지가 있으면 자동으로 매핑 생성 (필수/선택적 모두)
                    normalized_mappings[port_name] = (
                        f"{candidate_edge['source']}.{candidate_edge['source_port']}"
                    )

    def _coerce_variable_mappings(self, mapping: Any) -> Dict[str, Any]:
        """variable_mappings를 dict[str, Any] 형태로 변환"""
        if mapping is None:
            return {}
        if isinstance(mapping, dict):
            return dict(mapping)

        normalized: Dict[str, Any] = {}
        if isinstance(mapping, list):
            for entry in mapping:
                if not isinstance(entry, dict):
                    continue
                target_port = entry.get("target_port") or entry.get("target")
                selector = self._extract_selector(entry)
                if not target_port or not selector:
                    continue
                source_value = entry.get("source")
                if source_value is not None:
                    normalized[target_port] = source_value
                else:
                    normalized[target_port] = selector
        return normalized

    def _validate_v2_connections(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]]
    ) -> None:
        """Answer → End 연결을 검증"""
        answer_ids = {
            node.get("id") for node in nodes
            if node.get("data", {}).get("type") == "answer"
        }
        end_ids = {
            node.get("id") for node in nodes
            if node.get("data", {}).get("type") == "end"
        }
        if not answer_ids or not end_ids:
            return

        connected = any(
            edge.get("source") in answer_ids and edge.get("target") in end_ids
            for edge in edges
        )
        if not connected:
            self.errors.append(
                "Answer 노드가 End 노드에 연결되지 않았습니다. "
                "워크플로우가 정상적으로 종료되도록 연결하세요."
            )

    def _validate_v2_schema(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        node_map: Dict[str, Dict]
    ) -> None:
        """포트, 엣지, 변수 매핑 등 V2 전용 스키마 검증"""
        port_map: Dict[str, Dict[str, Dict[str, Any]]] = {
            node.get("id"): self._resolve_port_map(node) for node in nodes if node.get("id")
        }

        # 엣지 포트 매핑 검증
        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
            source_port = edge.get("source_port")
            target_port = edge.get("target_port")

            if source_port:
                special_prefix = self._resolve_special_prefix(source)
                if special_prefix:
                    if not source_port:
                        self.errors.append(
                            f"{special_prefix} 변수를 참조하는 엣지 {edge.get('id')}에 source_port가 필요합니다"
                        )
                elif source not in port_map or source_port not in port_map[source]["outputs"]:
                    self.errors.append(
                        f"엣지 {edge.get('id')}에 정의된 source_port '{source_port}'가 노드 {source}에 존재하지 않습니다"
                    )
            if target_port:
                if target not in port_map or target_port not in port_map[target]["inputs"]:
                    self.errors.append(
                        f"엣지 {edge.get('id')}에 정의된 target_port '{target_port}'가 노드 {target}에 존재하지 않습니다"
                    )

        # 변수 매핑 및 필수 입력 검증
        for node in nodes:
            node_id = node.get("id")
            port_entry = port_map.get(node_id) or {"inputs": {}, "outputs": {}}
            required_inputs = {
                name: meta for name, meta in port_entry.get("inputs", {}).items()
                if meta.get("required", True)
            }
            variable_mappings: Dict[str, Any] = node.get("variable_mappings") or {}
            node_type = node.get("data", {}).get("type")
            allow_context_fallback = bool(node.get("data", {}).get("allow_conversation_context_fallback", False))

            for port_name, meta in required_inputs.items():
                # LLM 노드의 context 포트는 대화 변수 폴백을 허용할 수 있음
                if (
                    port_name == "context"
                    and node_type == "llm"
                    and allow_context_fallback
                ):
                    continue

                if port_name not in variable_mappings:
                    self.errors.append(
                        f"노드 {node_id}의 필수 입력 포트 '{port_name}'가 variable_mappings에 정의되지 않았습니다"
                    )

            for target_port, mapping in variable_mappings.items():
                if target_port not in port_map.get(node_id, {}).get("inputs", {}):
                    self.errors.append(
                        f"노드 {node_id}의 variable_mappings에 알 수 없는 입력 포트 '{target_port}'가 있습니다"
                    )
                    continue

                selector = self._extract_selector(mapping)
                if not selector:
                    self.errors.append(
                        f"노드 {node_id}의 포트 '{target_port}' 매핑에 유효한 ValueSelector가 없습니다"
                    )
                    continue

                if selector.startswith(("env.", "conv.", "sys.")):
                    continue

                parts = selector.split(".", 1)
                if len(parts) != 2:
                    self.errors.append(
                        f"노드 {node_id}의 포트 '{target_port}' 매핑 셀렉터 형식이 잘못되었습니다: {selector}"
                    )
                    continue

                source_node, source_port = parts
                if source_node not in node_map:
                    self.errors.append(
                        f"노드 {node_id}의 포트 '{target_port}'가 존재하지 않는 노드 '{source_node}'를 참조합니다"
                    )
                elif source_port not in port_map.get(source_node, {}).get("outputs", {}):
                    self.errors.append(
                        f"노드 {node_id}의 포트 '{target_port}'가 노드 {source_node}의 출력 포트 '{source_port}'를 찾을 수 없습니다"
                    )

    @staticmethod
    def _map_schema_ports(ports: List[Any]) -> Dict[str, Dict[str, Any]]:
        mapped: Dict[str, Dict[str, Any]] = {}
        for port in ports or []:
            name = getattr(port, "name", None)
            if not name and isinstance(port, dict):
                name = port.get("name")
            if not name:
                continue

            if hasattr(port, "model_dump"):
                mapped[name] = port.model_dump()
            elif isinstance(port, dict):
                mapped[name] = port
            else:
                mapped[name] = {"name": name}
        return mapped

    def _resolve_port_map(self, node: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        ports = node.get("ports") or {}
        inputs = {
            p.get("name"): p for p in ports.get("inputs", []) if p.get("name")
        }
        outputs = {
            p.get("name"): p for p in ports.get("outputs", []) if p.get("name")
        }
        if inputs or outputs:
            return {"inputs": inputs, "outputs": outputs}

        node_type = node.get("type")
        if not node_type:
            return {"inputs": {}, "outputs": {}}

        schema = node_registry_v2.get_schema(node_type)
        if not schema:
            return {"inputs": {}, "outputs": {}}

        return {
            "inputs": self._map_schema_ports(schema.inputs),
            "outputs": self._map_schema_ports(schema.outputs),
        }

    @classmethod
    def _resolve_special_prefix(cls, node_id: Optional[str]) -> Optional[str]:
        """env/conv/sys 등 특수 노드 표기를 정규화"""
        if not node_id:
            return None
        lowered = str(node_id).lower()
        for prefix, aliases in cls._SPECIAL_VARIABLE_PREFIXES.items():
            if lowered in aliases:
                return prefix
        return None

    @staticmethod
    def _extract_selector(mapping: Any) -> Optional[str]:
        """variable_mappings 항목에서 ValueSelector 문자열을 추출"""
        if isinstance(mapping, str):
            return mapping
        if isinstance(mapping, dict):
            if isinstance(mapping.get("variable"), str):
                return mapping["variable"]
            source = mapping.get("source")
            if isinstance(source, dict) and isinstance(source.get("variable"), str):
                return source["variable"]
        return None

    @staticmethod
    def _is_port_type_compatible(source_type: Optional[str], target_type: Optional[str]) -> bool:
        if not source_type or not target_type:
            return False

        source_value = str(source_type).lower()
        target_value = str(target_type).lower()

        if source_value == target_value:
            return True

        any_value = PortType.ANY.value
        return source_value == any_value or target_value == any_value

    def _validate_no_cycles(self, adjacency_list: Dict[str, List[str]]):
        """순환 참조 검증 (DFS 사용)"""
        visited = set()
        rec_stack = set()

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in adjacency_list.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for node in adjacency_list:
            if node not in visited:
                if has_cycle(node):
                    self.errors.append("워크플로우에 순환 참조가 있습니다")
                    break

    def _validate_isolated_nodes(
        self,
        node_map: Dict[str, Dict],
        adjacency_list: Dict[str, List[str]]
    ):
        """고립된 노드 검증"""
        # 모든 연결된 노드 수집
        connected_nodes = set()

        # 출발 노드들
        connected_nodes.update(adjacency_list.keys())

        # 도착 노드들
        for targets in adjacency_list.values():
            connected_nodes.update(targets)

        # Start 노드는 출발만 하므로 예외
        start_nodes = {node_id for node_id, node in node_map.items()
                      if node.get("type") == NodeType.START.value}
        connected_nodes.update(start_nodes)

        # 모든 노드 확인
        for node_id in node_map:
            if node_id not in connected_nodes:
                node_type = node_map[node_id].get("type")
                self.warnings.append(f"노드 {node_id} ({node_type})가 고립되어 있습니다")

    def _validate_node_constraints(
        self,
        nodes: List[Dict[str, Any]],
        adjacency_list: Dict[str, List[str]]
    ):
        """노드별 제약 조건 검증"""
        for node in nodes:
            node_id = node.get("id")
            node_type = node.get("type")

            # Start 노드는 입력이 없어야 함
            if node_type == NodeType.START.value:
                incoming = [source for source, targets in adjacency_list.items()
                           if node_id in targets]
                if incoming:
                    self.errors.append(f"Start 노드 {node_id}는 입력을 가질 수 없습니다")

            # End 노드는 출력이 없어야 함
            if node_type == NodeType.END.value:
                if node_id in adjacency_list and adjacency_list[node_id]:
                    self.errors.append(f"End 노드 {node_id}는 출력을 가질 수 없습니다")

            # Knowledge/LLM 노드는 입출력이 있어야 함
            if node_type in [NodeType.KNOWLEDGE_RETRIEVAL.value, NodeType.LLM.value]:
                # 입력 확인
                incoming = [source for source, targets in adjacency_list.items()
                           if node_id in targets]
                if not incoming:
                    self.errors.append(f"{node_type} 노드 {node_id}는 최소 하나의 입력이 필요합니다")

                # 출력 확인
                if node_id not in adjacency_list or not adjacency_list[node_id]:
                    self.errors.append(f"{node_type} 노드 {node_id}는 최소 하나의 출력이 필요합니다")

    def _validate_execution_order(self, adjacency_list: Dict[str, List[str]]):
        """실행 순서 검증 (토폴로지 정렬 가능 여부)"""
        in_degree = defaultdict(int)
        for targets in adjacency_list.values():
            for target in targets:
                in_degree[target] += 1

        queue = deque([node for node in adjacency_list if in_degree[node] == 0])
        sorted_count = 0

        while queue:
            node = queue.popleft()
            sorted_count += 1

            for neighbor in adjacency_list.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 모든 노드가 정렬되지 않았다면 순환 참조가 있거나 문제가 있음
        total_nodes = len(set(adjacency_list.keys()) | set(in_degree.keys()))
        if sorted_count < total_nodes:
            self.warnings.append("일부 노드의 실행 순서를 결정할 수 없습니다")

    def get_execution_order(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]]
    ) -> Optional[List[str]]:
        """
        실행 순서 계산 (토폴로지 정렬)

        Args:
            nodes: 노드 리스트
            edges: 엣지 리스트

        Returns:
            실행 순서 또는 None (순환 참조 시)
        """
        node_map = {node["id"]: node for node in nodes}
        adjacency_list = self._build_adjacency_list(edges, node_map)

        in_degree = defaultdict(int)
        for node_id in node_map:
            if node_id not in in_degree:
                in_degree[node_id] = 0

        for targets in adjacency_list.values():
            for target in targets:
                in_degree[target] += 1

        queue = deque([node for node in node_map if in_degree[node] == 0])
        execution_order = []

        while queue:
            node = queue.popleft()
            execution_order.append(node)

            for neighbor in adjacency_list.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(execution_order) != len(node_map):
            return None

        return execution_order

    def _filter_branch_nodes(
        self,
        nodes: set,
        node_map: Dict[str, Dict],
        branch_node_types: set
    ) -> set:
        """
        분기 노드를 제외한 일반 노드만 반환

        Args:
            nodes: 노드 ID 집합
            node_map: 노드 맵
            branch_node_types: 분기 노드 타입 집합

        Returns:
            분기 노드가 제외된 노드 ID 집합
        """
        filtered = set()
        for node_id in nodes:
            node = node_map.get(node_id)
            if not node:
                continue

            # 노드 타입 확인
            node_type = node.get("type") or node.get("data", {}).get("type")

            # 분기 노드가 아닌 경우만 포함
            if node_type not in branch_node_types:
                filtered.add(node_id)

        return filtered

    def _validate_branch_convergence(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        node_map: Dict[str, Dict]
    ):
        """
        분기 합류 검증 (개선된 버전)

        IF/ELSE 같은 조건부 분기 노드의 다른 분기들이 동일한 다운스트림 노드로
        합류하는 경우를 감지합니다.

        개선사항: 중간 분기 노드(question-classifier 등)의 공유는 허용하되,
        일반 노드의 잘못된 합류는 감지합니다.

        Note: ExecutorV2에 조건부 의존성 해소 로직이 있으면 경고만 표시합니다.
        """
        # 분기 노드 찾기 (IfElse, QuestionClassifier 등)
        branch_node_types = {"if-else", "question-classifier"}
        branch_nodes = [
            node for node in nodes
            if node.get("type") in branch_node_types or
               node.get("data", {}).get("type") in branch_node_types
        ]

        if not branch_nodes:
            return

        # 엣지 매핑 생성
        edges_by_source = defaultdict(list)
        for edge in edges:
            source = edge.get("source")
            if source and not self._resolve_special_prefix(source):
                edges_by_source[source].append(edge)

        # 각 분기 노드 검증
        for branch_node in branch_nodes:
            node_id = branch_node["id"]
            outgoing_edges = edges_by_source.get(node_id, [])

            if len(outgoing_edges) < 2:
                continue  # 분기가 아님

            # 각 분기별로 타겟 노드 그룹화
            branches = defaultdict(list)
            for edge in outgoing_edges:
                source_port = edge.get("source_port", "default")
                target = edge.get("target")
                if target:
                    branches[source_port].append(target)

            if len(branches) < 2:
                continue  # 단일 분기만 있음

            # 각 분기의 다운스트림 노드들 수집
            branch_streams = {}
            for branch_name, targets in branches.items():
                downstream = self._get_downstream_nodes(
                    set(targets),
                    edges_by_source,
                    node_map
                )
                # 핵심: 분기 노드를 필터링한 다운스트림만 비교
                filtered_downstream = self._filter_branch_nodes(
                    downstream,
                    node_map,
                    branch_node_types
                )
                branch_streams[branch_name] = filtered_downstream

            # 분기 간 교집합 확인 (분기 노드 제외)
            branch_names = list(branch_streams.keys())
            for i in range(len(branch_names)):
                for j in range(i + 1, len(branch_names)):
                    branch_a = branch_names[i]
                    branch_b = branch_names[j]

                    # 일반 노드만 비교
                    converging = branch_streams[branch_a] & branch_streams[branch_b]

                    if converging:
                        # ExecutorV2가 자동으로 처리하므로 경고만 표시
                        converging_list = list(converging)[:3]  # 최대 3개만 표시
                        self.warnings.append(
                            f"분기 노드 '{node_id}'의 분기 '{branch_a}'와 '{branch_b}'가 "
                            f"동일한 일반 노드로 합류합니다: {converging_list}{'...' if len(converging) > 3 else ''}. "
                            f"ExecutorV2가 자동으로 처리하지만, 각 분기가 독립적으로 "
                            f"Answer → End로 연결되는 것이 더 명확한 설계입니다."
                        )
    
    def _get_downstream_nodes(
        self,
        start_nodes: set,
        edges_by_source: Dict[str, List[Dict[str, Any]]],
        node_map: Dict[str, Dict]
    ) -> set:
        """
        시작 노드들로부터 도달 가능한 모든 다운스트림 노드 수집 (BFS)

        Args:
            start_nodes: 시작 노드 ID 집합
            edges_by_source: source별 엣지 맵
            node_map: 노드 맵

        Returns:
            다운스트림 노드 ID 집합
        """
        visited = set()
        queue = deque(start_nodes)

        while queue:
            current = queue.popleft()

            if current in visited or current not in node_map:
                continue

            visited.add(current)

            # 이 노드의 outgoing 엣지들
            for edge in edges_by_source.get(current, []):
                target = edge.get("target")
                if target and target not in visited and not self._resolve_special_prefix(target):
                    queue.append(target)

        # 시작 노드들은 제외
        return visited - start_nodes

    def _validate_template_variable_connectivity(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        node_map: Dict[str, Dict]
    ) -> None:
        """
        템플릿 변수 참조가 연결된 노드의 출력만 사용하는지 검증

        Answer, LLM, Assigner 노드의 템플릿이나 variable_mappings에서
        참조하는 변수가 실제로 엣지로 연결된 노드에서 나오는지 확인합니다.
        """
        # 노드별 incoming edges 맵 생성
        incoming_edges: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            target = edge.get("target")
            if target:
                incoming_edges[target].append(edge)

        # 템플릿을 사용하는 노드 타입
        template_node_types = {"answer", "llm"}

        for node in nodes:
            node_id = node.get("id")
            node_data = node.get("data", {})
            node_type = node_data.get("type")

            if not node_id or not node_type:
                continue

            # Answer 및 LLM 노드의 템플릿 변수 검증
            if node_type in template_node_types:
                template = node_data.get("template") or node_data.get("prompt_template")
                if not template:
                    continue

                try:
                    # 템플릿에서 변수 추출
                    variable_selectors = TemplateRenderer.parse_template(template)
                except TemplateRenderError:
                    # 템플릿 파싱 오류는 이미 다른 검증에서 처리됨
                    continue

                # variable_mappings에서 허용된 셀렉터 계산
                variable_mappings = node.get("variable_mappings") or {}
                allowed_selectors = set()

                # variable_mappings의 모든 소스 셀렉터 수집
                for port_name, mapping in variable_mappings.items():
                    selector = self._extract_selector(mapping)
                    if selector:
                        allowed_selectors.add(selector)

                # 자기 자신의 입력 포트도 허용 (self.port_name 형식)
                port_map = self._resolve_port_map(node)
                for input_port in port_map.get("inputs", {}).keys():
                    allowed_selectors.add(f"self.{input_port}")

                # 템플릿 변수가 허용된 셀렉터에 있는지 확인
                for var_selector in variable_selectors:
                    # 특수 프리픽스는 항상 허용
                    if var_selector.startswith(("env.", "conv.", "conversation.", "sys.")):
                        continue

                    # self. 프리픽스 정규화
                    if var_selector in allowed_selectors:
                        continue

                    # 노드.포트 형식 분해
                    parts = var_selector.split(".", 1)
                    if len(parts) != 2:
                        self.errors.append(
                            f"노드 '{node_id}'의 템플릿 변수 '{var_selector}' 형식이 잘못되었습니다"
                        )
                        continue

                    source_node, source_port = parts

                    # 소스 노드가 현재 노드와 연결되어 있는지 확인
                    is_connected = any(
                        edge.get("source") == source_node and edge.get("target") == node_id
                        for edge in edges
                    )

                    if not is_connected:
                        self.errors.append(
                            f"노드 '{node_id}'의 템플릿 변수 '{var_selector}'는 "
                            f"연결되지 않은 노드 '{source_node}'를 참조합니다. "
                            f"워크플로우 에디터에서 노드를 연결해주세요."
                        )
