"""extend templates table for export import

Revision ID: e1f2g3h4i5j6
Revises: 450d3700bc71
Create Date: 2025-01-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e1f2g3h4i5j6'
down_revision = '450d3700bc71'
branch_labels = None
depends_on = None


def upgrade():
    # templates 테이블 생성
    op.create_table('templates',
        sa.Column('id', sa.String(50), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('icon', sa.String(500), nullable=True),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('version', sa.String(50), nullable=False, server_default='1.0.0'),
        sa.Column('visibility', sa.String(20), nullable=False, server_default='private'),
        sa.Column('author_id', sa.String(36), nullable=False),
        sa.Column('author_name', sa.String(200), nullable=False),
        sa.Column('author_email', sa.String(255), nullable=True),
        sa.Column('source_workflow_id', sa.String(50), nullable=True),
        sa.Column('source_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('node_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('edge_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('estimated_tokens', sa.Integer(), nullable=True),
        sa.Column('estimated_cost', sa.Float(), nullable=True),
        sa.Column('graph', sa.JSON(), nullable=False, server_default=sa.text("'{\"nodes\": [], \"edges\": []}'::json")),
        sa.Column('input_schema', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column('output_schema', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column('thumbnail_url', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )

    # templates 인덱스 추가
    op.create_index('ix_templates_id', 'templates', ['id'])
    op.create_index('ix_templates_category', 'templates', ['category'])
    op.create_index('ix_templates_type', 'templates', ['type'])
    op.create_index('ix_templates_visibility', 'templates', ['visibility'])
    op.create_index('ix_templates_author_id', 'templates', ['author_id'])
    op.create_index('ix_templates_source_workflow', 'templates', ['source_workflow_id'])

    # templates 외래 키 추가
    op.create_foreign_key('fk_templates_author', 'templates', 'users', ['author_id'], ['uuid'])
    op.create_foreign_key('fk_templates_source_workflow', 'templates', 'bots', ['source_workflow_id'], ['bot_id'])
    op.create_foreign_key('fk_templates_source_version', 'templates', 'bot_workflow_versions', ['source_version_id'], ['id'])

    # template_usages 테이블 생성
    op.create_table('template_usages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('template_id', sa.String(50), nullable=False),
        sa.Column('workflow_id', sa.String(50), nullable=False),
        sa.Column('workflow_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('node_id', sa.String(255), nullable=False),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False, server_default='imported'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workflow_id'], ['bots.bot_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workflow_version_id'], ['bot_workflow_versions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.uuid'], ondelete='CASCADE')
    )

    # template_usages 인덱스 추가
    op.create_index('ix_template_usages_template_id', 'template_usages', ['template_id'])
    op.create_index('ix_template_usages_workflow_id', 'template_usages', ['workflow_id'])
    op.create_index('ix_template_usages_user_id', 'template_usages', ['user_id'])
    op.create_index('ix_template_usages_occurred_at', 'template_usages', ['occurred_at'])


def downgrade():
    # template_usages 테이블 삭제
    op.drop_index('ix_template_usages_occurred_at', 'template_usages')
    op.drop_index('ix_template_usages_user_id', 'template_usages')
    op.drop_index('ix_template_usages_workflow_id', 'template_usages')
    op.drop_index('ix_template_usages_template_id', 'template_usages')
    op.drop_table('template_usages')

    # templates 테이블 삭제
    op.drop_constraint('fk_templates_source_version', 'templates', type_='foreignkey')
    op.drop_constraint('fk_templates_source_workflow', 'templates', type_='foreignkey')
    op.drop_constraint('fk_templates_author', 'templates', type_='foreignkey')
    op.drop_index('ix_templates_source_workflow', 'templates')
    op.drop_index('ix_templates_author_id', 'templates')
    op.drop_index('ix_templates_visibility', 'templates')
    op.drop_index('ix_templates_type', 'templates')
    op.drop_index('ix_templates_category', 'templates')
    op.drop_index('ix_templates_id', 'templates')
    op.drop_table('templates')
