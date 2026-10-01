"""
Manifest generation and persistence.

Bridges :mod:`app.ai.structure` to the database:

* :func:`generate_manifest_from_rows` backfills a manifest for a repository that
  is already indexed, reading only ``File`` / ``Chunk`` rows. No clone, no
  embedding, no LLM.
* :func:`persist_manifest` stores the payload and rendered markdown, replacing
  any previous row for that repository.

The backfill CLI lives in ``app/cli/backfill_manifests.py`` so this module stays
import-safe for the API and background tasks.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.structure import (
    RepoManifest,
    build_manifest_from_rows,
)
from app.core.config import settings
from app.models.file import File
from app.models.chunk import Chunk
from app.models.repository import Repository
from app.models.repo_manifest import RepoManifest as RepoManifestRow
from app.services.languages import PARSE_STATE_STRUCTURAL

logger = logging.getLogger(__name__)


def _symbols_for_files(db: Session, file_ids: List[str]) -> Dict[str, List[Dict]]:
    """
    Group a repository's chunks by file path.

    Returns ``{file_path: [{"name", "kind", "start_line", "end_line"}, ...]}``.
    Files are processed in batches so a repository with tens of thousands of
    chunks does not build one enormous IN clause.
    """
    symbols: Dict[str, List[Dict]] = {}
    batch_size = 500

    for start in range(0, len(file_ids), batch_size):
        batch = file_ids[start : start + batch_size]
        rows = db.execute(
            select(
                File.file_path,
                Chunk.chunk_type,
                Chunk.name,
                Chunk.start_line,
                Chunk.end_line,
            )
            .join(Chunk, Chunk.file_id == File.id)
            .where(File.id.in_(batch))
        ).all()

        for file_path, chunk_type, name, start_line, end_line in rows:
            symbols.setdefault(file_path, []).append(
                {
                    "name": name,
                    "kind": chunk_type,
                    "start_line": start_line,
                    "end_line": end_line,
                }
            )
    return symbols


def generate_manifest_from_rows(db: Session, repo: Repository) -> RepoManifest:
    """
    Build a manifest for an already-indexed repository.

    Reads existing ``File`` and ``Chunk`` rows, so it is safe to run against a
    repository that finished embedding. Rows written before ``parse_state``
    existed are treated as non-structural, matching how the API reports them.
    """
    files = (
        db.query(File)
        .filter(File.repository_id == repo.id)
        .order_by(File.file_path)
        .all()
    )
    file_ids = [str(f.id) for f in files]
    symbols = _symbols_for_files(db, file_ids)

    manifest = build_manifest_from_rows(
        repository_id=str(repo.id),
        full_name=repo.full_name,
        files=files,
        symbols_by_file=symbols,
    )

    logger.info(
        "%s: manifest built from rows: %d files, %d structural, %d symbols",
        repo.full_name,
        len(manifest.entries),
        sum(1 for e in manifest.entries if e.parse_state == PARSE_STATE_STRUCTURAL),
        sum(e.symbol_count for e in manifest.entries),
    )
    return manifest


def _manifest_dir() -> Path:
    base = Path(settings.MANIFEST_STORAGE_DIR)
    base.mkdir(parents=True, exist_ok=True)
    return base


def persist_manifest(
    db: Session,
    repo: Repository,
    manifest: RepoManifest,
    write_markdown_file: bool = True,
) -> RepoManifestRow:
    """
    Store a manifest for ``repo``, replacing any existing row.

    Also writes the rendered markdown under ``backend/.data/manifests`` so it can
    be inspected without a database client.
    """
    payload = manifest.to_payload()
    markdown = manifest.to_markdown()

    row = (
        db.query(RepoManifestRow)
        .filter(RepoManifestRow.repository_id == repo.id)
        .one_or_none()
    )
    if row is None:
        row = RepoManifestRow(repository_id=repo.id)
        db.add(row)

    row.manifest_json = payload
    row.markdown = markdown
    row.file_count = payload["totals"]["files"]
    row.symbol_count = payload["totals"]["symbols"]
    db.commit()
    db.refresh(row)

    if write_markdown_file:
        try:
            safe_name = repo.full_name.replace("/", "__")
            path = _manifest_dir() / f"{safe_name}.md"
            path.write_text(markdown, encoding="utf-8")
        except OSError as exc:
            # The database row is the source of truth; a failed convenience file
            # must not fail an import that already succeeded.
            logger.warning(
                "Could not write manifest markdown for %s: %s", repo.full_name, exc
            )

    return row


def build_and_persist_manifest(db: Session, repo: Repository) -> RepoManifestRow:
    """Generate and store a manifest for an already-indexed repository."""
    manifest = generate_manifest_from_rows(db, repo)
    return persist_manifest(db, repo, manifest)


def get_manifest(db: Session, repo_id: str) -> Optional[RepoManifestRow]:
    """Return the stored manifest for a repository, or ``None`` if not built."""
    return (
        db.query(RepoManifestRow)
        .filter(RepoManifestRow.repository_id == repo_id)
        .one_or_none()
    )