"""
팀 제거 검증 스크립트

코드베이스에서 팀 관련 참조가 모두 제거되었는지 검증합니다.
"""
import os
import re
from pathlib import Path
from typing import List, Tuple, Dict

# 검증할 패턴들
TEAM_PATTERNS = [
    (r'\bteam_id\b', 'team_id 참조'),
    (r'\bteam_uuid\b', 'team_uuid 참조'),
    (r'\bTeam\b', 'Team 클래스/모델 참조'),
    (r'\bTeamMember\b', 'TeamMember 클래스 참조'),
    (r'\bget_user_team\b', 'get_user_team 함수 참조'),
    (r'\bteams\.router\b', 'teams 라우터 참조'),
]

# 제외할 파일/디렉토리
EXCLUDE_PATTERNS = [
    'verify_team_removal.py',  # 이 스크립트 자체
    'migrate_vector_collections.py',  # 마이그레이션 스크립트 (필요)
    '__pycache__',
    '.git',
    'node_modules',
    '.pytest_cache',
    'venv',
    '.env',
    '*.pyc',
]

# 제외할 확장자
EXCLUDE_EXTENSIONS = {'.pyc', '.pyo', '.pyd', '.so', '.dll'}

# 허용된 참조 (마이그레이션 관련)
ALLOWED_FILES = {
    'c1a2b3c4d5e6_add_user_uuid.py',  # User.uuid 추가 마이그레이션
    'f7e8d9c0a1b2_remove_team_add_user_ownership.py',  # 팀 제거 마이그레이션
    'migrate_vector_collections.py',  # 벡터 스토어 마이그레이션
}


def should_skip(path: Path) -> bool:
    """파일/디렉토리를 스킵해야 하는지 확인"""
    path_str = str(path)

    # 제외 패턴 확인
    for pattern in EXCLUDE_PATTERNS:
        if pattern in path_str:
            return True

    # 확장자 확인
    if path.suffix in EXCLUDE_EXTENSIONS:
        return True

    # 허용된 파일인지 확인
    if path.name in ALLOWED_FILES:
        return True

    return False


def search_file(file_path: Path) -> List[Tuple[int, str, str]]:
    """파일에서 팀 관련 패턴 검색"""
    results = []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line_num, line in enumerate(lines, 1):
            for pattern, description in TEAM_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    results.append((line_num, line.strip(), description))

    except (UnicodeDecodeError, PermissionError):
        # 바이너리 파일이나 권한 없는 파일은 스킵
        pass

    return results


def scan_directory(root_dir: Path) -> Dict[str, List[Tuple[int, str, str]]]:
    """디렉토리 재귀 스캔"""
    findings = {}

    for path in root_dir.rglob('*'):
        if path.is_file() and not should_skip(path):
            # Python 파일만 검사
            if path.suffix == '.py':
                results = search_file(path)
                if results:
                    relative_path = path.relative_to(root_dir)
                    findings[str(relative_path)] = results

    return findings


def main():
    """메인 실행 함수"""
    # Backend 디렉토리 경로
    backend_dir = Path(__file__).parent.parent

    print("=" * 80)
    print("팀 제거 검증 스크립트")
    print("=" * 80)
    print(f"\n검증 대상 디렉토리: {backend_dir}")
    print(f"검증 패턴: {len(TEAM_PATTERNS)}개")
    print(f"제외 패턴: {len(EXCLUDE_PATTERNS)}개")
    print()

    # 스캔 실행
    print("코드베이스 스캔 중...")
    findings = scan_directory(backend_dir)

    # 결과 출력
    if not findings:
        print("\n✅ 검증 성공: 팀 관련 참조가 모두 제거되었습니다!")
        return 0

    print(f"\n⚠️  발견된 팀 관련 참조: {len(findings)}개 파일")
    print("=" * 80)

    for file_path, results in sorted(findings.items()):
        print(f"\n📄 파일: {file_path}")
        print("-" * 80)

        for line_num, line, description in results:
            print(f"  Line {line_num:4d}: {description}")
            print(f"           {line}")

    print("\n" + "=" * 80)
    print(f"총 {sum(len(r) for r in findings.values())}개의 참조가 발견되었습니다.")
    print("\n💡 Tip:")
    print("  - 마이그레이션 파일의 참조는 정상입니다 (데이터 마이그레이션용)")
    print("  - 그 외 파일에서 발견된 참조는 수정이 필요합니다")
    print()

    return 1


if __name__ == "__main__":
    exit(main())
