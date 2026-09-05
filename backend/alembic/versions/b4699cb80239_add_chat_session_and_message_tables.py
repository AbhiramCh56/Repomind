"""add chat session and message tables

Revision ID: b4699cb80239
Revises: 
Create Date: 2026-09-05 20:24:05.660045

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b4699cb80239'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'chat_sessions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('repo_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )

    op.create_table(
        'chat_messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('session_id', sa.Integer(),
                  sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('chat_messages')
    op.drop_table('chat_sessions')