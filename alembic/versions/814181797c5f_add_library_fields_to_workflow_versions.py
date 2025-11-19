"""add_library_fields_to_workflow_versions

Revision ID: 814181797c5f
Revises: n4o5p6q7r8s9
Create Date: 2025-11-18 20:27:45.390376

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '814181797c5f'
down_revision = 'n4o5p6q7r8s9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. bot_workflow_versions 테이블에 library 관련 컬럼 추가
    op.add_column('bot_workflow_versions',
        sa.Column('library_name', sa.String(length=255), nullable=True)
    )
    op.add_column('bot_workflow_versions',
        sa.Column('library_description', sa.Text(), nullable=True)
    )
    op.add_column('bot_workflow_versions',
        sa.Column('library_category', sa.String(length=100), nullable=True)
    )
    op.add_column('bot_workflow_versions',
        sa.Column('library_tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column('bot_workflow_versions',
        sa.Column('library_visibility', sa.String(length=20), nullable=True)
    )
    op.add_column('bot_workflow_versions',
        sa.Column('is_in_library', sa.Boolean(), server_default='false', nullable=False)
    )
    op.add_column('bot_workflow_versions',
        sa.Column('library_published_at', sa.DateTime(timezone=True), nullable=True)
    )

    # 2. 사양에 명시된 추가 컬럼 (통계 및 스키마 정보)
    op.add_column('bot_workflow_versions',
        sa.Column('input_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column('bot_workflow_versions',
        sa.Column('output_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column('bot_workflow_versions',
        sa.Column('node_count', sa.Integer(), nullable=True)
    )
    op.add_column('bot_workflow_versions',
        sa.Column('edge_count', sa.Integer(), nullable=True)
    )
    op.add_column('bot_workflow_versions',
        sa.Column('port_definitions', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )

    # 3. 인덱스 생성 (라이브러리 검색 성능 향상)
    op.create_index(
        'ix_bot_workflow_versions_is_in_library',
        'bot_workflow_versions',
        ['is_in_library']
    )
    op.create_index(
        'ix_bot_workflow_versions_library_category',
        'bot_workflow_versions',
        ['library_category']
    )
    op.create_index(
        'ix_bot_workflow_versions_library_visibility',
        'bot_workflow_versions',
        ['library_visibility']
    )
    op.create_index(
        'ix_bot_workflow_versions_library_published_at',
        'bot_workflow_versions',
        ['library_published_at']
    )

    # 4. draft 유니크 인덱스 추가 전에 중복 draft 레코드 정리
    connection = op.get_bind()
    
    # 각 bot_id당 draft 상태가 여러 개인 경우, 가장 최신 것만 남기고 나머지 삭제
    # CTE를 사용하여 각 bot_id의 가장 최신 draft만 선택
    connection.execute(sa.text("""
        WITH latest_drafts AS (
            SELECT DISTINCT ON (bot_id) id
            FROM bot_workflow_versions
            WHERE status = 'draft'
            ORDER BY bot_id, COALESCE(updated_at, created_at) DESC
        )
        DELETE FROM bot_workflow_versions
        WHERE status = 'draft'
        AND id NOT IN (SELECT id FROM latest_drafts);
    """))
    
    # 4-1. draft 유니크 인덱스 추가 (bot_id당 draft는 1개만, partial index 사용)
    op.create_index(
        'uq_bot_workflow_versions_draft',
        'bot_workflow_versions',
        ['bot_id'],
        unique=True,
        postgresql_where=sa.text("status = 'draft'")
    )

    # 5. agent_import_history 테이블 생성
    op.create_table(
        'agent_import_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('source_version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('bot_workflow_versions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_bot_id', sa.String(255),
                  sa.ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False),
        sa.Column('imported_by', sa.String(36),
                  sa.ForeignKey('users.uuid', ondelete='SET NULL'), nullable=True),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('import_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )

    op.create_index('ix_agent_import_history_source_version_id', 'agent_import_history', ['source_version_id'])
    op.create_index('ix_agent_import_history_target_bot_id', 'agent_import_history', ['target_bot_id'])
    op.create_index('ix_agent_import_history_imported_at', 'agent_import_history', ['imported_at'])

    # 6. bot_deployments 테이블에 workflow_version_id FK 추가
    op.add_column('bot_deployments',
        sa.Column('workflow_version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('bot_workflow_versions.id', ondelete='SET NULL'), nullable=True)
    )
    op.create_index('ix_bot_deployments_workflow_version_id', 'bot_deployments', ['workflow_version_id'])

    # 기존 배포를 최신 published 버전으로 매핑
    connection.execute(sa.text("""
        UPDATE bot_deployments bd
        SET workflow_version_id = (
            SELECT bwv.id
            FROM bot_workflow_versions bwv
            JOIN bots b ON bwv.bot_id = b.bot_id
            WHERE b.id = bd.bot_id
              AND bwv.status = 'published'
            ORDER BY bwv.published_at DESC
            LIMIT 1
        )
        WHERE bd.workflow_version_id IS NULL;
    """))

    # 7. templates 테이블 데이터를 bot_workflow_versions로 마이그레이션
    inspector = sa.inspect(connection)
    tables = inspector.get_table_names()

    if 'templates' in tables:
        # templates의 데이터를 bot_workflow_versions로 복사
        connection.execute(sa.text("""
            UPDATE bot_workflow_versions bwv
            SET
                library_name = t.name,
                library_description = t.description,
                library_category = t.category,
                library_tags = t.tags,
                library_visibility = t.visibility,
                is_in_library = true,
                library_published_at = t.created_at
            FROM templates t
            WHERE bwv.id = t.source_version_id
            AND t.source_version_id IS NOT NULL;
        """))

        # template_usages가 있다면 agent_import_history로 이관
        if 'template_usages' in tables:
            connection.execute(sa.text("""
                INSERT INTO agent_import_history (source_version_id, target_bot_id, imported_by, imported_at)
                SELECT
                    t.source_version_id,
                    tu.workflow_id,
                    tu.user_id,
                    tu.occurred_at
                FROM template_usages tu
                JOIN templates t ON tu.template_id = t.id
                WHERE t.source_version_id IS NOT NULL;
            """))


def downgrade() -> None:
    # 배포 테이블 변경 롤백
    op.drop_index('ix_bot_deployments_workflow_version_id', table_name='bot_deployments')
    op.drop_column('bot_deployments', 'workflow_version_id')

    # agent_import_history 테이블 삭제
    op.drop_index('ix_agent_import_history_imported_at', table_name='agent_import_history')
    op.drop_index('ix_agent_import_history_target_bot_id', table_name='agent_import_history')
    op.drop_index('ix_agent_import_history_source_version_id', table_name='agent_import_history')
    op.drop_table('agent_import_history')

    # draft 유니크 인덱스 삭제
    op.drop_index('uq_bot_workflow_versions_draft', table_name='bot_workflow_versions')

    # 인덱스 삭제
    op.drop_index('ix_bot_workflow_versions_library_published_at', table_name='bot_workflow_versions')
    op.drop_index('ix_bot_workflow_versions_library_visibility', table_name='bot_workflow_versions')
    op.drop_index('ix_bot_workflow_versions_library_category', table_name='bot_workflow_versions')
    op.drop_index('ix_bot_workflow_versions_is_in_library', table_name='bot_workflow_versions')

    # 추가 컬럼 삭제
    op.drop_column('bot_workflow_versions', 'port_definitions')
    op.drop_column('bot_workflow_versions', 'edge_count')
    op.drop_column('bot_workflow_versions', 'node_count')
    op.drop_column('bot_workflow_versions', 'output_schema')
    op.drop_column('bot_workflow_versions', 'input_schema')

    # 라이브러리 컬럼 삭제
    op.drop_column('bot_workflow_versions', 'library_published_at')
    op.drop_column('bot_workflow_versions', 'is_in_library')
    op.drop_column('bot_workflow_versions', 'library_visibility')
    op.drop_column('bot_workflow_versions', 'library_tags')
    op.drop_column('bot_workflow_versions', 'library_category')
    op.drop_column('bot_workflow_versions', 'library_description')
    op.drop_column('bot_workflow_versions', 'library_name')
