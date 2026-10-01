"""
CLI to backfill deterministic manifests for already-indexed repositories.

Reads only ``File`` / ``Chunk`` rows, so no clone and no re-embedding happens.
Safe to re-run: manifests are replaced in place.

Usage:
    python -m app.cli.backfill_manifests
    python -m app.cli.backfill_manifests --repo NVIDIA/OpenShell
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.db.session import SessionLocal
# Import every model before touching the ORM, so the string-based relationships
# on Repository (owner, files, manifest) can be resolved by name.
from app.models import chat as _chat  # noqa: F401
from app.models import chunk as _chunk  # noqa: F401
from app.models import file as _file  # noqa: F401
from app.models import repo_manifest as _repo_manifest  # noqa: F401
from app.models.repository import Repository, RepoStatus
from app.models.user import User  # noqa: F401
from app.services.manifest_service import build_and_persist_manifest

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger("manifest_backfill")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill repository manifests.")
    parser.add_argument(
        "--repo",
        action="append",
        help="Only backfill this owner/name. Repeatable. Omit for all eligible repos.",
    )
    parser.add_argument(
        "--include-incomplete",
        action="store_true",
        help="Also process repos that are not COMPLETED (off by default: a "
             "partial index produces a misleading manifest).",
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        query = db.query(Repository)
        if args.repo:
            query = query.filter(Repository.full_name.in_(args.repo))
        if not args.include_incomplete:
            query = query.filter(Repository.status == RepoStatus.COMPLETED)

        repos = query.order_by(Repository.full_name).all()
        if not repos:
            print("No repositories matched.")
            return 0

        print(f"Backfilling manifests for {len(repos)} repository(ies):\n")
        for repo in repos:
            if not repo.is_complete:
                # Only reachable with --include-incomplete; a partial index
                # produces a misleading manifest.
                print(f"  SKIP {repo.full_name}: not finished indexing")
                continue
            if not repo.has_embeddings and (repo.chunk_count or 0) == 0:
                # Completed with nothing indexed and no manifest to build from.
                print(f"  SKIP {repo.full_name}: no index rows to summarize")
                continue
            try:
                row = build_and_persist_manifest(db, repo)
                print(
                    f"  OK   {repo.full_name}: "
                    f"{row.file_count} files, {row.symbol_count} symbols"
                )
            except Exception as exc:  # keep going; one bad repo should not stop the rest
                db.rollback()
                print(f"  FAIL {repo.full_name}: {exc}")
                logger.exception("Manifest backfill failed for %s", repo.full_name)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())