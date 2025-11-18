"""drop_templates_and_template_usages_tables

Revision ID: f87ec3d41e29
Revises: 814181797c5f
Create Date: 2025-11-18 22:45:04.833424

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f87ec3d41e29'
down_revision: Union[str, None] = '814181797c5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    템플릿 시스템 완전 제거

    순서:
    1. template_usages FK 제거
    2. templates FK 제거
    3. template_usages 인덱스 제거
    4. templates 인덱스 제거
    5. 테이블 드롭
    """

    # 테이블 존재 여부 확인
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = inspector.get_table_names()

    # 1. template_usages 테이블 FK 제거 (테이블이 존재하는 경우)
    if 'template_usages' in tables:
        # FK 제약 조건 제거
        try:
            op.drop_constraint('template_usages_template_id_fkey', 'template_usages', type_='foreignkey')
        except Exception as e:
            print(f"Warning: FK template_usages_template_id_fkey not found: {e}")

        try:
            op.drop_constraint('template_usages_user_id_fkey', 'template_usages', type_='foreignkey')
        except Exception as e:
            print(f"Warning: FK template_usages_user_id_fkey not found: {e}")

        try:
            op.drop_constraint('template_usages_workflow_id_fkey', 'template_usages', type_='foreignkey')
        except Exception as e:
            print(f"Warning: FK template_usages_workflow_id_fkey not found: {e}")

        try:
            op.drop_constraint('template_usages_workflow_version_id_fkey', 'template_usages', type_='foreignkey')
        except Exception as e:
            print(f"Warning: FK template_usages_workflow_version_id_fkey not found: {e}")

    # 2. templates 테이블 FK 제거 (테이블이 존재하는 경우)
    if 'templates' in tables:
        try:
            op.drop_constraint('fk_templates_author', 'templates', type_='foreignkey')
        except Exception as e:
            print(f"Warning: FK fk_templates_author not found: {e}")

        try:
            op.drop_constraint('fk_templates_source_version', 'templates', type_='foreignkey')
        except Exception as e:
            print(f"Warning: FK fk_templates_source_version not found: {e}")

        try:
            op.drop_constraint('fk_templates_source_workflow', 'templates', type_='foreignkey')
        except Exception as e:
            print(f"Warning: FK fk_templates_source_workflow not found: {e}")

    # 3. template_usages 인덱스 제거 (PK 제외)
    if 'template_usages' in tables:
        try:
            op.drop_index('ix_template_usages_occurred_at', table_name='template_usages')
        except Exception as e:
            print(f"Warning: Index ix_template_usages_occurred_at not found: {e}")

        try:
            op.drop_index('ix_template_usages_template_id', table_name='template_usages')
        except Exception as e:
            print(f"Warning: Index ix_template_usages_template_id not found: {e}")

        try:
            op.drop_index('ix_template_usages_user_id', table_name='template_usages')
        except Exception as e:
            print(f"Warning: Index ix_template_usages_user_id not found: {e}")

        try:
            op.drop_index('ix_template_usages_workflow_id', table_name='template_usages')
        except Exception as e:
            print(f"Warning: Index ix_template_usages_workflow_id not found: {e}")

    # 4. templates 인덱스 제거 (PK 제외)
    if 'templates' in tables:
        try:
            op.drop_index('ix_templates_author_id', table_name='templates')
        except Exception as e:
            print(f"Warning: Index ix_templates_author_id not found: {e}")

        try:
            op.drop_index('ix_templates_category', table_name='templates')
        except Exception as e:
            print(f"Warning: Index ix_templates_category not found: {e}")

        try:
            op.drop_index('ix_templates_id', table_name='templates')
        except Exception as e:
            print(f"Warning: Index ix_templates_id not found: {e}")

        try:
            op.drop_index('ix_templates_source_workflow', table_name='templates')
        except Exception as e:
            print(f"Warning: Index ix_templates_source_workflow not found: {e}")

        try:
            op.drop_index('ix_templates_type', table_name='templates')
        except Exception as e:
            print(f"Warning: Index ix_templates_type not found: {e}")

        try:
            op.drop_index('ix_templates_visibility', table_name='templates')
        except Exception as e:
            print(f"Warning: Index ix_templates_visibility not found: {e}")

    # 5. 테이블 드롭 (순서: template_usages → templates)
    if 'template_usages' in tables:
        op.drop_table('template_usages')
        print("✓ template_usages 테이블 삭제 완료")

    if 'templates' in tables:
        op.drop_table('templates')
        print("✓ templates 테이블 삭제 완료")

    print("✓ Templates 시스템 완전 제거 완료")


def downgrade() -> None:
    """
    Downgrade는 복잡하므로 구현하지 않음
    필요 시 백업에서 복구
    """
    raise NotImplementedError(
        "templates/template_usages 테이블 복구는 지원하지 않습니다. "
        "백업에서 복원하세요: "
        "docker exec -i postgres_db psql -U namamu_user namamu < backup_before_template_drop_YYYYMMDD_HHMMSS.sql"
    )
