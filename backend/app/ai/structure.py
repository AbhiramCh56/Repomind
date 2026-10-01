"""
Deterministic repository manifest.

The manifest is a compact, structured summary of a repository: language mix,
directory layout, the symbol index, likely entrypoints, and an inventory of
docs/config files. It exists so architecture questions ("what is this", "how
does it work", "where is auth handled") can be answered from a few hundred KB
of curated text instead of re-reading tens of thousands of embedded chunks.

Two build paths share one core so a backfilled manifest is identical to one
produced during a live parse:

* :func:`build_manifest_from_rows` reconstructs a manifest purely from existing
  ``File`` / ``Chunk`` rows. No clone and no embedding are required.
* :func:`build_manifest_from_parse` accumulates the same data while
  ``repo_processor`` walks a fresh checkout.

Nothing here calls an LLM, so the output is reproducible for a given input.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.services.languages import PARSE_STATE_STRUCTURAL

logger = logging.getLogger(__name__)

#: Chunk types that represent real extracted code symbols. Everything else
#: (notably ``raw_text``) is documentation or config that belongs in the
#: manifest inventory rather than in the symbol index.
STRUCTURAL_CHUNK_TYPES: Tuple[str, ...] = (
    "function",
    "class",
    "module",
)

#: Filenames that commonly act as a process entrypoint, checked case-insensitively
#: against the basename of each indexed file.
ENTRYPOINT_BASENAMES: Tuple[str, ...] = (
    "main.py",
    "__main__.py",
    "app.py",
    "wsgi.py",
    "asgi.py",
    "manage.py",
    "cli.py",
    "server.py",
    "index.js",
    "index.ts",
    "main.js",
    "main.ts",
    "main.rs",
    "main.go",
    "lib.rs",
    "mod.rs",
    "cmd/main.go",
    "dockerfile",
    "docker-compose.yml",
    "makefile",
    "justfile",
)

#: Directories whose contents are usually entrypoints even when the filename is
#: generic. Keys are compared against the parent directory's basename.
ENTRYPOINT_DIR_HINTS: Tuple[str, ...] = (
    "cmd",
    "bin",
    "src",
)

#: Cap on how many symbols are rendered per language in the markdown view. The
#: JSON payload always keeps the full index; this only bounds the human-readable
#: output so a huge repository does not produce an unreadable blob.
MAX_SYMBOLS_PER_LANGUAGE_IN_MARKDOWN = 60

#: Cap on rendered entrypoints. A large monorepo can contain hundreds of
#: main.rs / src/bin targets; listing all of them buries the useful ones.
MAX_ENTRYPOINTS_IN_PAYLOAD = 40


def _is_structural_chunk(chunk_type: Optional[str]) -> bool:
    return (chunk_type or "") in STRUCTURAL_CHUNK_TYPES


def _entrypoint_score(file_path: str) -> int:
    """
    Rank a path as a possible entrypoint. Higher is a better candidate.

    The scoring is intentionally simple and name-based: it is a hint for the
    LLM narrative and the UI, not a verified call-graph entrypoint.
    """
    normalized = file_path.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    if not parts:
        return 0

    basename = parts[-1].lower()
    parent = parts[-2].lower() if len(parts) >= 2 else ""

    if basename in ("dockerfile", "docker-compose.yml", "makefile", "justfile"):
        # Useful build/run surfaces, but weaker than a code entrypoint.
        return 3

    if basename in ("main.py", "app.py", "__main__.py", "wsgi.py", "asgi.py",
                    "manage.py", "cli.py", "server.py"):
        return 10 if parent in ENTRYPOINT_DIR_HINTS else 7

    if basename == "main.rs":
        return 8

    if basename == "main.go":
        return 7

    # Cargo marks a crate's real entrypoint with [[bin]]/[[example]] targets,
    # which default to src/bin/<name>.rs; the name itself is not predictable,
    # so everything in src/bin/ is a candidate rather than a fixed list.
    if parent == "bin" and basename.endswith(".rs"):
        return 8

    # lib.rs is every Rust library crate's root, not an entrypoint. Rank it low
    # so main.rs and src/bin/*.rs win, but keep it visible because for a
    # library-only repository it is still the most useful starting point.
    if basename == "lib.rs":
        return 2

    if basename in ("index.js", "index.ts", "main.js", "main.ts"):
        return 6

    return 0


@dataclass
class ManifestEntry:
    """One indexed file as seen by the manifest builder."""

    file_path: str
    language: Optional[str]
    parse_state: Optional[str]
    size_bytes: int = 0
    symbols: List[Dict[str, Any]] = field(default_factory=list)
    doc_symbol_count: int = 0

    @property
    def is_structural(self) -> bool:
        return self.parse_state == PARSE_STATE_STRUCTURAL

    @property
    def symbol_count(self) -> int:
        return len(self.symbols)


@dataclass
class RepoManifest:
    """Structured, serializable view of an indexed repository."""

    repository_id: str
    full_name: str
    entries: List[ManifestEntry] = field(default_factory=list)

    # ---------------------------------------------------------------- builders
    @property
    def languages(self) -> Dict[str, Dict[str, int]]:
        """Per-language file counts split by whether structure was extracted."""
        out: Dict[str, Dict[str, int]] = {}
        for entry in self.entries:
            language = entry.language or "Unknown"
            bucket = out.setdefault(
                language, {"files": 0, "structural_files": 0, "raw_files": 0, "symbols": 0}
            )
            bucket["files"] += 1
            if entry.is_structural:
                bucket["structural_files"] += 1
            else:
                bucket["raw_files"] += 1
            bucket["symbols"] += entry.symbol_count
        return dict(sorted(out.items(), key=lambda kv: (-kv[1]["files"], kv[0])))

    @property
    def directories(self) -> List[Dict[str, Any]]:
        """Per-directory rollup, deepest paths included, sorted by file count."""
        rollup: Dict[str, Dict[str, Any]] = {}
        for entry in self.entries:
            normalized = entry.file_path.replace("\\", "/")
            parts = [p for p in normalized.split("/") if p]
            directory = "/".join(parts[:-1]) if len(parts) > 1 else "."
            bucket = rollup.setdefault(
                directory,
                {"path": directory, "files": 0, "structural_files": 0, "symbols": 0},
            )
            bucket["files"] += 1
            if entry.is_structural:
                bucket["structural_files"] += 1
            bucket["symbols"] += entry.symbol_count
        return sorted(rollup.values(), key=lambda d: (-d["files"], d["path"]))

    @property
    def entrypoints(self) -> List[Dict[str, Any]]:
        """Best-guess entrypoints, highest score first, de-duplicated by path."""
        seen: Dict[str, Dict[str, Any]] = {}
        for entry in self.entries:
            score = _entrypoint_score(entry.file_path)
            if score <= 0:
                continue
            seen.setdefault(
                entry.file_path,
                {
                    "path": entry.file_path,
                    "language": entry.language or "Unknown",
                    "score": score,
                },
            )
        return sorted(seen.values(), key=lambda e: (-e["score"], e["path"]))[
            :MAX_ENTRYPOINTS_IN_PAYLOAD
        ]

    @property
    def symbols_by_language(self) -> Dict[str, List[Dict[str, Any]]]:
        """Full symbol index grouped by language."""
        out: Dict[str, List[Dict[str, Any]]] = {}
        for entry in self.entries:
            if not entry.is_structural or not entry.symbols:
                continue
            language = entry.language or "Unknown"
            bucket = out.setdefault(language, [])
            for symbol in entry.symbols:
                bucket.append(
                    {
                        "name": symbol.get("name"),
                        "kind": symbol.get("kind"),
                        "file": entry.file_path,
                        "start_line": symbol.get("start_line"),
                        "end_line": symbol.get("end_line"),
                    }
                )
        for bucket in out.values():
            bucket.sort(key=lambda s: (str(s.get("file")), s.get("start_line") or 0))
        return dict(sorted(out.items(), key=lambda kv: (-len(kv[1]), kv[0])))

    @property
    def doc_files(self) -> List[Dict[str, Any]]:
        """Docs and config files, which live in the manifest instead of the index."""
        out: List[Dict[str, Any]] = []
        for entry in self.entries:
            if entry.is_structural:
                continue
            out.append(
                {
                    "path": entry.file_path,
                    "language": entry.language or "Unknown",
                    "parse_state": entry.parse_state,
                    "size_bytes": entry.size_bytes,
                    "doc_chunks": entry.doc_symbol_count,
                }
            )
        return sorted(out, key=lambda d: (-d["size_bytes"], d["path"]))

    # --------------------------------------------------------------- rendering
    def to_payload(self) -> Dict[str, Any]:
        """Full-fidelity payload stored in the database and returned by the API."""
        symbols = self.symbols_by_language
        return {
            "repository_id": self.repository_id,
            "full_name": self.full_name,
            "totals": {
                "files": len(self.entries),
                "structural_files": sum(1 for e in self.entries if e.is_structural),
                "doc_files": sum(1 for e in self.entries if not e.is_structural),
                "symbols": sum(e.symbol_count for e in self.entries),
            },
            "languages": self.languages,
            "directories": self.directories,
            "entrypoints": self.entrypoints,
            "doc_files": self.doc_files,
            "symbols": {language: items for language, items in symbols.items()},
        }

    def to_markdown(self) -> str:
        """
        Render a compact, human/LLM-readable summary.

        Symbol listings are capped per language so a repository with hundreds of
        thousands of symbols still produces a summary of a readable size.
        """
        payload = self.to_payload()
        totals = payload["totals"]
        lines: List[str] = [
            f"# Repository manifest: {self.full_name}",
            "",
            f"- Indexed files: {totals['files']}",
            f"- Structurally parsed files: {totals['structural_files']}",
            f"- Docs/config files (not embedded): {totals['doc_files']}",
            f"- Extracted symbols: {totals['symbols']}",
            "",
            "## Languages",
            "",
        ]

        if payload["languages"]:
            lines.append("| Language | Files | Structural | Raw | Symbols |")
            lines.append("| --- | ---: | ---: | ---: | ---: |")
            for language, stats in payload["languages"].items():
                lines.append(
                    f"| {language} | {stats['files']} | {stats['structural_files']} "
                    f"| {stats['raw_files']} | {stats['symbols']} |"
                )
        else:
            lines.append("_No indexed files._")

        lines += ["", "## Likely entrypoints", ""]
        if payload["entrypoints"]:
            for item in payload["entrypoints"]:
                lines.append(f"- `{item['path']}` ({item['language']})")
        else:
            lines.append("_No conventional entrypoints detected._")

        lines += ["", "## Largest directories", ""]
        for directory in payload["directories"][:40]:
            lines.append(
                f"- `{directory['path']}` - {directory['files']} files, "
                f"{directory['symbols']} symbols"
            )

        lines += ["", "## Symbols by language", ""]
        for language, items in payload["symbols"].items():
            lines.append(f"### {language} ({len(items)})")
            lines.append("")
            for symbol in items[:MAX_SYMBOLS_PER_LANGUAGE_IN_MARKDOWN]:
                location = f"{symbol['file']}:{symbol['start_line']}"
                lines.append(f"- `{symbol['kind']}` `{symbol['name']}` - {location}")
            if len(items) > MAX_SYMBOLS_PER_LANGUAGE_IN_MARKDOWN:
                lines.append(
                    f"- _{len(items) - MAX_SYMBOLS_PER_LANGUAGE_IN_MARKDOWN} more "
                    f"{language} symbols omitted; see the JSON manifest._"
                )
            lines.append("")

        lines += ["", "## Docs and config inventory", ""]
        if payload["doc_files"]:
            for item in payload["doc_files"][:200]:
                lines.append(
                    f"- `{item['path']}` ({item['language']}, "
                    f"{item['size_bytes']} bytes)"
                )
            if len(payload["doc_files"]) > 200:
                lines.append(
                    f"- _{len(payload['doc_files']) - 200} more omitted._"
                )
        else:
            lines.append("_None._")

        return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- builders
def build_manifest_from_rows(
    repository_id: str,
    full_name: str,
    files: Iterable[Any],
    symbols_by_file: Dict[str, List[Dict[str, Any]]],
) -> RepoManifest:
    """
    Build a manifest from persisted rows, for backfilling an existing import.

    ``files`` yields objects exposing ``file_path``, ``language``,
    ``parse_state`` and ``size_bytes`` (ORM ``File`` rows or lightweight
    equivalents). ``symbols_by_file`` maps a file path to that file's symbols.
    """
    manifest = RepoManifest(repository_id=repository_id, full_name=full_name)
    for row in files:
        path = getattr(row, "file_path", None) or row["file_path"]
        language = getattr(row, "language", None)
        if language is None and not isinstance(row, dict):
            language = row.language
        parse_state = getattr(row, "parse_state", None)
        size = getattr(row, "size_bytes", 0) or 0

        symbols = symbols_by_file.get(path, []) or []
        doc_chunks = sum(
            1 for symbol in symbols if not _is_structural_chunk(symbol.get("kind"))
        )
        manifest.entries.append(
            ManifestEntry(
                file_path=path,
                language=language,
                parse_state=parse_state,
                size_bytes=size,
                symbols=[s for s in symbols if _is_structural_chunk(s.get("kind"))],
                doc_symbol_count=doc_chunks,
            )
        )
    return manifest


def build_manifest_from_parse(
    repository_id: str, full_name: str, entries: Sequence[ManifestEntry]
) -> RepoManifest:
    """Build a manifest from entries accumulated during a live parse pass."""
    return RepoManifest(
        repository_id=repository_id, full_name=full_name, entries=list(entries)
    )