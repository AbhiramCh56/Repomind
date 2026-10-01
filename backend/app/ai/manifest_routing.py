"""
Routing for architecture questions.

Docs and config files no longer produce embedded chunks (see
``repo_processor``), so dense retrieval alone cannot answer questions like
"how is this repo organised?". Those questions need the deterministic manifest:
languages, entrypoints, directory rollups and the symbol index.

The router here is intentionally keyword-based and deterministic rather than an
LLM call. It runs before the chain is built, costs nothing, and is easy to test.
When a question looks architectural, the manifest markdown is prepended to the
retrieved context instead of replacing it, so a question that mixes "where is the
CLI entrypoint" with "what does it call" still gets both views.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.repo_manifest import RepoManifest as RepoManifestRow
from app.services.manifest_service import get_manifest

logger = logging.getLogger(__name__)

#: Ceiling on manifest characters injected into a prompt. The OpenShell manifest
#: renders to ~43 KB; most of that is the symbol list, which dense retrieval is
#: better at. The overview sections that routing actually needs are far smaller,
#: so the manifest is truncated to its orientation part.
MAX_MANIFEST_CONTEXT_CHARS = 12000

#: Terms that signal the question is about repository shape rather than a
#: specific implementation. Matched case-insensitively as whole words where
#: possible, so "class" does not fire on "classic".
_ARCHITECTURE_PATTERNS = [
    r"over(ar)?view\b",
    r"architecture\b",
    r"how (is|are) .* (organi[sz]ed|structured|laid out)",
    r"repo(sitory)? (structure|layout|organi[sz]ation)",
    r"code ?base (structure|layout|overview|organi[sz]ation)",
    r"project (structure|layout)",
    r"high[- ]level (structure|view|design)",
    r"what (languages|technolog(y|ies))\b",
    r"entry ?points?\b",
    r"entry ?files?\b",
    r"main (entry ?points?|modules?)\b",
    r"where does .* (start|begin)",
    r"directory (structure|layout|map|tree)",
    r"folder (structure|layout)\b",
    r"file (structure|layout)\b",
    r"what (is|are) in (this|the) repo",
    r"what (does|do) (this|the) repo(sitory)? (do|contain|include)",
    # "largest module" and "modules are the largest" are both natural phrasings,
    # so match the adjective on either side of the noun.
    r"\b(biggest|largest)\b[^?]{0,20}\b(module|director(y|ies)|package|component)",
    r"\b(module|director(y|ies)|package|component)s?\b[^?]{0,20}\b(biggest|largest)\b",
    r"tech stack\b",
    r"what are the (main|primary|core) (modules|components|packages|directories)",
    r"summari[sz]e (the|this) (repo|codebase|project|structure)",
    r"give me (an|a) (overview|tour|map) of",
    r"how many (files|modules|packages)",
    r"what (modules|packages|components) (are|exist)",
]

_ARCHITECTURE_RE = re.compile(
    r"|".join(_ARCHITECTURE_PATTERNS), re.IGNORECASE
)


def is_architecture_question(question: str) -> bool:
    """
    Return True when ``question`` is about repository shape.

    Conservative by design: a false positive only adds context, it never removes
    vector retrieval. A false negative is the real cost, since the docs/config
    text is no longer in the vector store.
    """
    if not question or not question.strip():
        return False
    return bool(_ARCHITECTURE_RE.search(question))


def _overview_markdown(markdown: str) -> str:
    """
    Return the orientation part of the rendered manifest.

    The full markdown ends with a per-language symbol dump. Symbol names are
    already retrievable through the vector store, and pasting 28,000 of them
    would crowd out the retrieved code. Keep everything from the top through the
    directory rollups, then stop.
    """
    for marker in ("\n## Symbols by language", "\n## Docs and config inventory"):
        index = markdown.find(marker)
        if index != -1:
            return markdown[:index].rstrip()
    return markdown


def load_manifest_context(
    db: Session, repo_id: str, max_chars: int = MAX_MANIFEST_CONTEXT_CHARS
) -> Optional[str]:
    """
    Return manifest context for ``repo_id``, or ``None`` if unavailable.

    Returns ``None`` rather than raising: a missing manifest degrades the answer
    to plain vector retrieval, which is what happened before manifests existed.
    """
    try:
        row: Optional[RepoManifestRow] = get_manifest(db, repo_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Manifest lookup failed for %s: %s", repo_id, exc)
        return None

    if row is None or not row.markdown:
        logger.info("No stored manifest for %s; skipping manifest routing", repo_id)
        return None

    context = _overview_markdown(row.markdown)
    if len(context) > max_chars:
        context = context[:max_chars].rstrip() + "\n\n(manifest truncated)"
    return context