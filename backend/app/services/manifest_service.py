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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, select
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


def compute_live_file_ids(
    counts: Iterable[Tuple[str, int]], embedded_count: int
) -> set:
    """
    Return the ids of files fully represented in the index right now.

    ``counts`` yields ``(file_id, chunk_count)`` in the exact order embedding
    walks the repository (``file_path``, ``start_line``, chunk id), so the chunks
    of one file are contiguous and the first ``embedded_count`` of them cover
    whole files except possibly one boundary file.

    Files with no chunks are docs/config files: they are deliberately never
    embedded (see the docs/config rule in ``repo_processor``), so their row is
    the whole representation and they join as soon as it exists. This is why the
    preview starts growing during processing, before embeddings appear, and why
    the scan cannot stop at the boundary: a docs file later in path order is
    still "available".
    """
    live: set = set()
    covered = 0
    past_boundary = False

    for file_id, chunk_count in counts:
        if not chunk_count:
            live.add(str(file_id))
            continue
        if past_boundary:
            # Everything after a partially embedded file is unembedded: the
            # prefixes are ordered, so no later chunk can be in the index yet.
            continue
        if covered + chunk_count <= embedded_count:
            covered += chunk_count
            live.add(str(file_id))
        else:
            past_boundary = True

    return live


def live_chunk_counts(db: Session, repo_id: str) -> List[Tuple[str, int]]:
    """Per-file chunk counts ordered exactly like ``embed_repository_chunks``."""
    rows = (
        db.query(File.id, File.file_path, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.file_id == File.id)
        .filter(File.repository_id == repo_id)
        .group_by(File.id, File.file_path)
        .order_by(File.file_path, File.id)
        .all()
    )
    return [(str(file_id), int(count or 0)) for file_id, _path, count in rows]


@dataclass
class LiveManifest:
    """A transient manifest covering only the files indexed so far."""

    manifest: RepoManifest
    live_files: int
    total_files: int


def build_live_manifest(db: Session, repo: Repository) -> LiveManifest:
    """
    Build a manifest over the subset of files already in the index.

    Used only for the live architecture preview while a repository is still
    cloning, processing, or embedding. The result is **never persisted**: the
    canonical manifest is still generated once indexing completes, and the
    ``is_complete`` gates that protect it (structure endpoints, chat readiness,
    the backfill CLI) stay exactly as they were.
    """
    counts = live_chunk_counts(db, str(repo.id))
    live_ids = compute_live_file_ids(counts, repo.embedded_count or 0)

    files = (
        db.query(File)
        .filter(File.repository_id == repo.id)
        .order_by(File.file_path)
        .all()
    )
    live_files = [f for f in files if str(f.id) in live_ids]
    symbols = _symbols_for_files(db, [str(f.id) for f in live_files])

    manifest = build_manifest_from_rows(
        repository_id=str(repo.id),
        full_name=repo.full_name,
        files=live_files,
        symbols_by_file=symbols,
    )

    logger.debug(
        "%s: live manifest has %d/%d files (%d/%d chunks embedded)",
        repo.full_name,
        len(live_files),
        len(files),
        repo.embedded_count or 0,
        repo.chunk_count or 0,
    )
    return LiveManifest(
        manifest=manifest, live_files=len(live_files), total_files=len(files)
    )


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