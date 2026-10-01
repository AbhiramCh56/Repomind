"""add parse_state to files

Revision ID: c5e91d3a7b02
Revises: a1c4f7d92b30
Create Date: 2026-09-26

Records how each file was understood during ingestion so a partially parsed
file is never mistaken for a structurally understood one.
"""
from alembic import op
import sqlalchemy as sa

revision = "c5e91d3a7b02"
down_revision = "a1c4f7d92b30"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "files",
        sa.Column("parse_state", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_files_parse_state",
        "files",
        ["parse_state"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_files_parse_state", table_name="files")
    op.drop_column("files", "parse_state")
