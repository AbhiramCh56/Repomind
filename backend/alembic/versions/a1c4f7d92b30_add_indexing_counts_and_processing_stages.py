"""add indexing counts and processing stages to repositories

Revision ID: a1c4f7d92b30
Revises: b4699cb80239
Create Date: 2026-09-26 10:14:22.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c4f7d92b30'
down_revision: Union[str, Sequence[str], None] = 'b4699cb80239'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_enum_type(name: str) -> bool:
    return any(
        row[0] == name
        for row in op.get_bind().execute(
            sa.text("SELECT typname FROM pg_type WHERE typname = :name"),
            {"name": name},
        )
    )


def upgrade() -> None:
    """Upgrade schema."""
    # The repositories/files/chunks/users tables are still created by
    # Base.metadata.create_all on boot (see app/main.py), so guard on their
    # presence to keep `alembic upgrade head` usable on an empty database.
    if _has_table('repositories'):
        op.add_column(
            'repositories',
            sa.Column('chunk_count', sa.Integer(), nullable=False, server_default='0'),
        )
        op.add_column(
            'repositories',
            sa.Column('embedded_count', sa.Integer(), nullable=False, server_default='0'),
        )

    if _has_enum_type('repostatus'):
        op.execute("ALTER TYPE repostatus ADD VALUE IF NOT EXISTS 'PROCESSING'")
        op.execute("ALTER TYPE repostatus ADD VALUE IF NOT EXISTS 'EMBEDDING'")


def downgrade() -> None:
    """Downgrade schema."""
    if _has_table('repositories'):
        op.drop_column('repositories', 'embedded_count')
        op.drop_column('repositories', 'chunk_count')

    # The PROCESSING/EMBEDDING enum values are intentionally left in place:
    # dropping a value from a PostgreSQL enum requires recreating the type and
    # rewriting every row that uses it.
