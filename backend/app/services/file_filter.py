"""
Layered file-selection rules for repository ingestion.

A repository's own ``.gitignore`` is necessary but not sufficient. In a
polyglot repository the worst offenders for retrieval quality are usually
*committed* rather than ignored: ``package-lock.json`` is routinely multiple
megabytes and sits well under any sane per-file size cap, so a JavaScript
repository would otherwise be indexed almost entirely from its lockfile.

Every rejection carries a reason code so the import report can state what was
left out instead of the omission being invisible.
"""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath
from typing import Iterable, Optional

BINARY_EXTENSIONS = frozenset(
    {
        # images
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
        ".psd", ".ai", ".eps",
        # fonts
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        # archives
        ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war",
        ".whl", ".egg", ".deb", ".rpm", ".dmg", ".iso",
        # compiled artefacts
        ".exe", ".dll", ".so", ".dylib", ".o", ".obj", ".a", ".lib", ".class",
        ".pyd", ".wasm", ".node", ".bin", ".out",
        # documents
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt",
        ".ods", ".epub", ".mobi",
        # media
        ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac", ".ogg", ".webm",
        ".wma", ".aac", ".m4a", ".mov",
        # data stores and indexes
        ".sqlite", ".sqlite3", ".db", ".mdb", ".pack", ".idx", ".dat",
        ".dmg",
        # python bytecode
        ".pyc", ".pyo", ".pyd",
    }
)

LOCKFILE_NAMES = frozenset(
    {
        # JavaScript ecosystem
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lock",
        "bun.lockb",
        "deno.lock",
        "packages.lock.json",
        # Python ecosystem
        "poetry.lock",
        "pipfile.lock",
        "uv.lock",
        "pdm.lock",
        "conda-lock.yml",
        # other ecosystems
        "cargo.lock",
        "composer.lock",
        "gemfile.lock",
        "go.sum",
        "mix.lock",
        "pubspec.lock",
        "podfile.lock",
        "gradle.lockfile",
        "flake.lock",
        "paket.lock",
    }
)

BUILD_DIRS = frozenset(
    {
        # git internals, pruned at the directory level so the walk never descends
        ".git",
        ".hg",
        ".svn",
        # JavaScript
        "node_modules",
        "bower_components",
        "jspm_packages",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".output",
        ".vercel",
        ".netlify",
        ".turbo",
        ".parcel-cache",
        ".cache",
        # polyglot / compiled
        "dist",
        "build",
        "target",
        "out",
        "vendor",
        "third_party",
        "thirdparty",
        "external",
        "pods",
        "deriveddata",
        # Python
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".eggs",
        ".hypothesis",
        "site-packages",
        "venv",
        ".venv",
        "virtualenv",
        "htmlcov",
        "coverage",
    }
)

MINIFIED_PATTERNS = (
    "*.min.js",
    "*.min.css",
    "*.min.mjs",
    "*.min.cjs",
    "*.bundle.js",
    "*.bundle.css",
    "*.bundle.mjs",
    "*.map",
    "*-vscode.js",
    "*-es2015.js",
    "*-esm.js",
    "*.umd.js",
    "bundle.js",
    "bundle.css",
)

GENERATED_PATTERNS = (
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*_pb2.pyi",
    "*.pb.go",
    "*.pb.cc",
    "*.pb.h",
    "*.generated.*",
    "*.g.dart",
    "*.freezed.dart",
    "*.designer.cs",
    "*.g.cs",
    "*_generated.go",
    "*.d.ts.map",
    "*.snap",
)


class SkipReason:
    """Reason codes attached to a skipped path."""

    BUILD_DIR = "build_dir"
    BINARY = "binary"
    LOCKFILE = "lockfile"
    MINIFIED = "minified"
    GENERATED = "generated"
    GENERATED_BULK = "generated_bulk"
    GITIGNORE = "gitignore"
    TOO_LARGE = "too_large"


ALL_SKIP_REASONS = (
    SkipReason.BUILD_DIR,
    SkipReason.BINARY,
    SkipReason.LOCKFILE,
    SkipReason.MINIFIED,
    SkipReason.GENERATED,
    SkipReason.GENERATED_BULK,
    SkipReason.GITIGNORE,
    SkipReason.TOO_LARGE,
)

#: A bundle is recognised by shape rather than by name, because bundlers emit
#: whatever filename the project configures. Real source never has this profile:
#: megabytes of code compressed into a handful of very long lines.
GENERATED_BULK_MIN_BYTES = 100_000
GENERATED_BULK_MAX_LINES = 20


def looks_generated_bulk(
    source_code: str,
    size_bytes: int,
    min_bytes: int = GENERATED_BULK_MIN_BYTES,
    max_lines: int = GENERATED_BULK_MAX_LINES,
) -> bool:
    """Detect a minified bundle by density rather than by filename."""
    if size_bytes < min_bytes:
        return False
    line_count = source_code.count("\n") + 1 if source_code else 0
    return line_count <= max_lines


def _matches_any(name: str, patterns: Iterable[str]) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatch(lowered, pattern.lower()) for pattern in patterns)


def skip_reason(
    rel_path: str,
    size_bytes: int,
    gitignore_spec=None,
    max_file_size_bytes: Optional[int] = None,
    extra_build_dirs: Iterable[str] = (),
    extra_patterns: Iterable[str] = (),
) -> Optional[str]:
    """
    Return the reason a path must be skipped, or ``None`` if it should be indexed.

    ``rel_path`` is expected in POSIX form. The checks are ordered cheapest and
    most specific first so the common rejection costs almost nothing.
    """
    pure = PurePosixPath(rel_path)
    name = pure.name
    parts = {part.lower() for part in pure.parts[:-1]}

    build_dirs = BUILD_DIRS | {d.lower() for d in extra_build_dirs}
    if parts & build_dirs:
        return SkipReason.BUILD_DIR

    suffix = pure.suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        return SkipReason.BINARY

    if name.lower() in LOCKFILE_NAMES:
        return SkipReason.LOCKFILE

    patterns = tuple(MINIFIED_PATTERNS) + tuple(GENERATED_PATTERNS) + tuple(extra_patterns)
    if _matches_any(name, patterns):
        return SkipReason.MINIFIED if _matches_any(name, MINIFIED_PATTERNS) else SkipReason.GENERATED

    if gitignore_spec is not None and gitignore_spec.match_file(rel_path):
        return SkipReason.GITIGNORE

    if max_file_size_bytes is not None and size_bytes > max_file_size_bytes:
        return SkipReason.TOO_LARGE

    return None
