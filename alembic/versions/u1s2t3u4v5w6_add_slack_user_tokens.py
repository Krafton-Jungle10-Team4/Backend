"""add user token fields to slack_integrations

Revision ID: u1s2t3u4v5w6
Revises: d5adbd4a6a0c
Create Date: 2025-11-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'u1s2t3u4v5w6'
down_revision = 'd5adbd4a6a0c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('slack_integrations', sa.Column('user_access_token', sa.Text(), nullable=True))
    op.add_column('slack_integrations', sa.Column('authed_user_id', sa.String(), nullable=True))
    op.add_column('slack_integrations', sa.Column('authed_user_scopes', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('slack_integrations', 'authed_user_scopes')
    op.drop_column('slack_integrations', 'authed_user_id')
    op.drop_column('slack_integrations', 'user_access_token')
