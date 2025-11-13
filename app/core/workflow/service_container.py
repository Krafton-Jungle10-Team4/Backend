"""
워크플로우 V2 서비스 컨테이너

의존성 주입(Dependency Injection) 패턴을 사용하여
노드 실행에 필요한 서비스들을 관리하고 제공합니다.
"""

from typing import Any, Dict, Optional, TypeVar, Generic, Type, Callable
from app.services.vector_service import VectorService
from app.services.llm_service import LLMService
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ServiceContainer:
    """
    서비스 컨테이너

    워크플로우 실행에 필요한 서비스들을 등록하고 관리합니다.
    노드는 이 컨테이너를 통해 필요한 서비스를 주입받습니다.

    Example:
        >>> container = ServiceContainer()
        >>> container.register("vector_service", vector_service_instance)
        >>> vector_service = container.get("vector_service")
    """

    def __init__(self):
        """서비스 컨테이너 초기화"""
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._singletons: Dict[str, Any] = {}

        logger.debug("ServiceContainer initialized")

    # ========== 서비스 등록 ==========

    def register(self, name: str, service: Any) -> None:
        """
        서비스 인스턴스를 등록

        Args:
            name: 서비스 이름
            service: 서비스 인스턴스

        Example:
            >>> container.register("vector_service", vector_service)
        """
        self._services[name] = service
        logger.debug(f"Registered service: {name}")

    def register_factory(
        self,
        name: str,
        factory: Callable[[], Any],
        singleton: bool = False
    ) -> None:
        """
        서비스 팩토리 함수를 등록

        Args:
            name: 서비스 이름
            factory: 서비스를 생성하는 팩토리 함수
            singleton: True면 첫 호출 시 생성 후 재사용

        Example:
            >>> container.register_factory(
            ...     "logger",
            ...     lambda: logging.getLogger(__name__),
            ...     singleton=True
            ... )
        """
        self._factories[name] = factory
        if singleton:
            self._singletons[name] = None
        logger.debug(f"Registered factory: {name} (singleton={singleton})")

    def register_type(
        self,
        name: str,
        service_type: Type[T],
        *args,
        **kwargs
    ) -> None:
        """
        서비스 타입을 등록하고 필요 시 인스턴스 생성

        Args:
            name: 서비스 이름
            service_type: 서비스 클래스 타입
            *args: 생성자 인자
            **kwargs: 생성자 키워드 인자

        Example:
            >>> container.register_type("cache", RedisCache, host="localhost")
        """
        def factory():
            return service_type(*args, **kwargs)

        self.register_factory(name, factory, singleton=True)

    # ========== 서비스 조회 ==========

    def get(self, name: str) -> Optional[Any]:
        """
        서비스 조회

        Args:
            name: 서비스 이름

        Returns:
            서비스 인스턴스 또는 None

        Example:
            >>> vector_service = container.get("vector_service")
        """
        # 1. 직접 등록된 서비스
        if name in self._services:
            return self._services[name]

        # 2. 싱글톤 팩토리
        if name in self._singletons:
            if self._singletons[name] is None:
                # 첫 호출 시 생성
                factory = self._factories[name]
                self._singletons[name] = factory()
                logger.debug(f"Created singleton service: {name}")
            return self._singletons[name]

        # 3. 일반 팩토리
        if name in self._factories:
            service = self._factories[name]()
            logger.debug(f"Created service from factory: {name}")
            return service

        logger.warning(f"Service not found: {name}")
        return None

    def get_required(self, name: str) -> Any:
        """
        필수 서비스 조회 (없으면 예외 발생)

        Args:
            name: 서비스 이름

        Returns:
            서비스 인스턴스

        Raises:
            ValueError: 서비스를 찾을 수 없을 때

        Example:
            >>> vector_service = container.get_required("vector_service")
        """
        service = self.get(name)
        if service is None:
            raise ValueError(f"Required service not found: {name}")
        return service

    def has(self, name: str) -> bool:
        """
        서비스 존재 여부 확인

        Args:
            name: 서비스 이름

        Returns:
            존재 여부
        """
        return (
            name in self._services or
            name in self._factories or
            name in self._singletons
        )

    # ========== 일반적인 서비스 편의 메서드 ==========

    def get_vector_service(self) -> Optional[VectorService]:
        """벡터 서비스 조회"""
        return self.get("vector_service")

    def get_llm_service(self) -> Optional[LLMService]:
        """LLM 서비스 조회"""
        return self.get("llm_service")

    def get_db_session(self) -> Optional[Any]:
        """데이터베이스 세션 조회"""
        return self.get("db_session")

    def get_bot_id(self) -> Optional[str]:
        """봇 ID 조회"""
        return self.get("bot_id")

    def get_session_id(self) -> Optional[str]:
        """세션 ID 조회"""
        return self.get("session_id")

    def get_stream_handler(self) -> Optional[Any]:
        """스트림 핸들러 조회"""
        return self.get("stream_handler")

    # ========== 서비스 제거 ==========

    def unregister(self, name: str) -> bool:
        """
        서비스 등록 해제

        Args:
            name: 서비스 이름

        Returns:
            성공 여부
        """
        removed = False

        if name in self._services:
            del self._services[name]
            removed = True

        if name in self._factories:
            del self._factories[name]
            removed = True

        if name in self._singletons:
            del self._singletons[name]
            removed = True

        if removed:
            logger.debug(f"Unregistered service: {name}")

        return removed

    def clear(self) -> None:
        """모든 서비스 제거"""
        self._services.clear()
        self._factories.clear()
        self._singletons.clear()
        logger.debug("Cleared all services")

    # ========== 유틸리티 ==========

    def list_services(self) -> list[str]:
        """
        등록된 모든 서비스 이름 목록

        Returns:
            서비스 이름 리스트
        """
        services = set()
        services.update(self._services.keys())
        services.update(self._factories.keys())
        services.update(self._singletons.keys())
        return sorted(services)

    def to_dict(self) -> Dict[str, Any]:
        """
        컨테이너 상태를 딕셔너리로 변환

        Returns:
            서비스 정보
        """
        return {
            "services": list(self._services.keys()),
            "factories": list(self._factories.keys()),
            "singletons": list(self._singletons.keys()),
            "total": len(self.list_services())
        }

    def __repr__(self) -> str:
        return f"ServiceContainer(services={len(self.list_services())})"

    # ========== 컨텍스트 매니저 지원 ==========

    def __enter__(self):
        """컨텍스트 매니저 진입"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """컨텍스트 매니저 종료 시 정리"""
        # 필요시 리소스 정리
        logger.debug("ServiceContainer context exited")
        return False


class ServiceLocator:
    """
    전역 서비스 로케이터 (선택적 사용)

    애플리케이션 전체에서 공유되는 서비스 컨테이너를 제공합니다.
    일반적으로는 각 워크플로우 실행마다 새 컨테이너를 생성하는 것을 권장하지만,
    전역 서비스가 필요한 경우 사용할 수 있습니다.
    """

    _instance: Optional[ServiceContainer] = None

    @classmethod
    def get_instance(cls) -> ServiceContainer:
        """
        싱글톤 인스턴스 조회

        Returns:
            ServiceContainer 인스턴스
        """
        if cls._instance is None:
            cls._instance = ServiceContainer()
            logger.debug("Created global ServiceLocator instance")
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """싱글톤 인스턴스 초기화"""
        cls._instance = None
        logger.debug("Reset global ServiceLocator")
