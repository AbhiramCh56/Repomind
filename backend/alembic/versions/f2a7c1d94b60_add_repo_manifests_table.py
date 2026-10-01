"""add repo_manifests table for deterministic architecture summaries

Revision ID: f2a7c1d94b60
Revises: c5e91d3a7b02
Create Date: 2026-10-01 17:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f2a7c1d94b60'
down_revision: Union[str, Sequence[str], None] = 'c5e91d3a7b02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # repositories/files are still created by Base.metadata.create_all on boot
    # (see app/main.py), so guard on the parent table's presence to keep
    # `alembic upgrade head` usable on an empty database.
    conn = op.get_bind()
    has_repositories = sa.inspect(conn).has_table("repositories")
    if not has_repositories:
        return

    op.create_table(
        'repo_manifests',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('manifest_json', sa.JSON(), nullable=False),
        sa.Column('markdown', sa.Text(), nullable=False),
        sa.Column('file_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('symbol_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['repository_id'],
            ['repositories.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('repository_id'),
    )
    op.create_index(
        op.f('ix_repo_manifests_repository_id'),
        'repo_manifests',
        ['repository_id'],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    if not sa.inspect(conn).has_table("repo_manifests"):
        return
    op.drop_index(op.f('ix_repo_manifests_repository_id'), table_name='repo_manifests')
    op.drop_table('repo_manifests')