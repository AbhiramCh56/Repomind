import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import chromadb
from langchain_huggingface import HuggingFaceEmbeddings
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.file import File
from app.models.repository import Repository

logger = logging.getLogger(__name__)

_embedding_function = None
_chroma_client = None


def get_embedding_function() -> HuggingFaceEmbeddings:
    """Lazily build the shared embedding model (~90MB, slow to load)."""
    global _embedding_function
    if _embedding_function is None:
        logger.info("Loading embedding model %s", settings.EMBEDDING_MODEL)
        _embedding_function = HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL)
    return _embedding_function


def get_chroma_client() -> chromadb.ClientAPI:
    """Lazily build the shared persistent Chroma client."""
    global _chroma_client
    if _chroma_client is None:
        Path(settings.CHROMA_STORAGE_DIR).mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_STORAGE_DIR)
    return _chroma_client


def get_collection_name(repo_id: str) -> str:
    """Canonical Chroma collection name for a repository."""
    return f"repo_{str(repo_id).replace('-', '')}"


def warm_embedding_model_in_background() -> threading.Thread:
    """
    Start loading the embedding model on a background thread.

    Loading costs several seconds, so doing it inline in the startup handler
    would delay the server becoming ready, while doing it lazily would make the
    user's first question wait. Warming in the background overlaps the load with
    login and page load instead, and a failure here is harmless because
    get_embedding_function() simply retries on first use.
    """
    def _load() -> None:
        started = time.perf_counter()
        try:
            get_embedding_function()
            logger.info(
                "Embedding model ready in %.1fs", time.perf_counter() - started
            )
        except Exception:
            logger.exception(
                "Embedding model warm-up failed; it will be retried on first use"
            )

    thread = threading.Thread(target=_load, name="embedding-warmup", daemon=True)
    thread.start()
    return thread


def delete_repository_collection(repo_id: str) -> bool:
    """Drop a repository's vector collection. Returns True if one was removed."""
    collection_name = get_collection_name(repo_id)
    try:
        get_chroma_client().delete_collection(name=collection_name)
    except Exception:
        logger.debug("Collection %s not present; nothing to delete", collection_name)
        return False
    logger.info("Deleted Chroma collection %s", collection_name)
    return True


@dataclass
class EmbeddingResult:
    total: int
    embedded: int
    errors: list = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.embedded == self.total

    def summary(self) -> str:
        text = f"Embedded {self.embedded}/{self.total} chunks"
        if self.errors:
            text += f"; {len(self.errors)} batch(es) failed"
        return text


def embed_repository_chunks(repo_id: str, db: Session) -> EmbeddingResult:
    """
    Embeds every chunk of a repository into its own Chroma collection.

    The collection is deleted first so a reprocess never merges with (or
    duplicates) a previous index. Raises ValueError when there is nothing
    legitimate to embed; partial failures are reported in the result so the
    caller can fail the repository instead of silently marking it complete.
    """
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise ValueError(f"Repository {repo_id} not found for embedding.")

    chunks_with_files = (
        db.query(Chunk, File)
        .join(File, Chunk.file_id == File.id)
        .filter(File.repository_id == repo_id)
        .all()
    )
    total = len(chunks_with_files)
    if total == 0:
        raise ValueError(f"No chunks found for {repo.full_name}; nothing to embed.")

    delete_repository_collection(repo_id)

    collection_name = get_collection_name(repo_id)
    collection = get_chroma_client().get_or_create_collection(
        name=collection_name,
        metadata={"description": f"Embeddings for {repo.full_name}"},
    )

    embedding_function = get_embedding_function()

    documents = []
    metadatas = []
    ids = []
    for chunk, file in chunks_with_files:
        # The file path is part of the embedded text so the LLM knows where the code lives
        documents.append(f"File: {file.file_path}\nCode:\n{chunk.content}")
        ids.append(str(chunk.id))
        metadatas.append(
            {
                "file_path": file.file_path,
                "language": file.language,
                "chunk_type": chunk.chunk_type,
                "name": chunk.name or "unknown",
                "start_line": chunk.start_line or 0,
            }
        )

    batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)
    total_batches = (total + batch_size - 1) // batch_size
    embedded = 0
    errors: list = []

    for index in range(0, total, batch_size):
        batch_docs = documents[index : index + batch_size]
        batch_number = index // batch_size + 1
        for attempt in (1, 2):
            try:
                batch_embeddings = embedding_function.embed_documents(batch_docs)
                collection.add(
                    documents=batch_docs,
                    embeddings=batch_embeddings,
                    metadatas=metadatas[index : index + batch_size],
                    ids=ids[index : index + batch_size],
                )
            except Exception as exc:
                if attempt == 1:
                    logger.warning(
                        "Batch %s/%s failed, retrying: %s", batch_number, total_batches, exc
                    )
                    continue
                logger.error(
                    "Batch %s/%s failed permanently: %s", batch_number, total_batches, exc
                )
                errors.append(f"batch {batch_number}/{total_batches}: {exc}")
                break
            embedded += len(batch_docs)
            logger.info("Embedded batch %s/%s", batch_number, total_batches)
            break

    return EmbeddingResult(total=total, embedded=embedded, errors=errors)
