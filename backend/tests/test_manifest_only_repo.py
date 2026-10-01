"""
Tests for queryability of a manifest-only repository.

Docs and config files no longer produce chunks, so a repository that is entirely
documentation has zero embedded content. That is a valid state, not a failure:
its manifest is the complete representation. These tests cover the model
properties, the import path, and the chat gate that decides "ready".
"""

import unittest
from unittest import mock
from uuid import uuid4

from app.models.repository import Repository, RepoStatus
from app.models.repo_manifest import RepoManifest
from app.services import github_service, rag_service
from app.services.github_service import process_repository_background_task
from support import FakeSession, make_repository


class IsQueryableTests(unittest.TestCase):
    def _repo(self, status, chunk_count, embedded_count, manifest=False):
        repo = make_repository(status=status)
        repo.status = RepoStatus(status)
        repo.chunk_count = chunk_count
        repo.embedded_count = embedded_count
        if manifest:
            repo.manifest = RepoManifest(repository_id=repo.id, markdown="# m")
        return repo

    def test_fully_embedded_repo_is_queryable(self):
        repo = self._repo("completed", 100, 100)
        self.assertTrue(repo.has_embeddings)
        self.assertTrue(repo.is_queryable)
        self.assertFalse(repo.is_manifest_only)

    def test_partial_embedding_is_not_queryable(self):
        repo = self._repo("completed", 100, 40)
        self.assertFalse(repo.has_embeddings)
        self.assertFalse(repo.is_queryable)

    def test_failed_repo_is_never_queryable(self):
        self.assertFalse(self._repo("failed", 100, 100).is_queryable)

    def test_docs_only_repo_is_queryable_via_manifest(self):
        repo = self._repo("completed", 0, 0, manifest=True)
        self.assertFalse(repo.has_embeddings)
        self.assertTrue(repo.is_manifest_only)
        self.assertTrue(repo.is_queryable)

    def test_docs_only_without_manifest_is_not_queryable(self):
        repo = self._repo("completed", 0, 0, manifest=False)
        self.assertFalse(repo.is_manifest_only)
        self.assertFalse(repo.is_queryable)


class BackgroundTaskDocsOnlyTests(unittest.TestCase):
    """A docs-only repository completes instead of being marked FAILED."""

    def _run(self, chunks, manifest_only_files, files=3):
        file_result = mock.Mock(
            chunks=chunks, manifest_only_files=manifest_only_files, files=files, errors=[]
        )
        embedding_result = mock.Mock(
            embedded=0, total=0, complete=True, errors=[], summary="Embedded 0/0 chunks"
        )

        db = FakeSession(make_repository(status="completed"))

        with mock.patch.object(github_service, "process_repository_files",
                               return_value=file_result), \
             mock.patch.object(github_service, "embed_repository_chunks",
                               return_value=embedding_result), \
             mock.patch.object(github_service, "build_and_persist_manifest"), \
             mock.patch.object(github_service, "delete_repository_collection"), \
             mock.patch.object(github_service.git, "Repo") as clone:
            clone.clone_from.return_value.active_branch.name = "main"
            process_repository_background_task(str(db.repository.id), db)

        return db.repository

    def test_docs_only_repo_completes_and_skips_embedding(self):
        repo = self._run(chunks=0, manifest_only_files=3)

        self.assertEqual(repo.status, RepoStatus.COMPLETED)
        self.assertEqual(repo.error_message, None)

    def test_docs_only_repo_does_not_call_embedding(self):
        db = FakeSession(make_repository(status="completed"))
        file_result = mock.Mock(chunks=0, manifest_only_files=2, files=2, errors=[])
        embedding_result = mock.Mock(
            embedded=0, total=0, complete=True, errors=[], summary="Embedded 0/0 chunks"
        )

        with mock.patch.object(github_service, "process_repository_files",
                               return_value=file_result), \
             mock.patch.object(github_service, "embed_repository_chunks",
                               return_value=embedding_result) as embed, \
             mock.patch.object(github_service, "build_and_persist_manifest"), \
             mock.patch.object(github_service, "delete_repository_collection"), \
             mock.patch.object(github_service.git, "Repo") as clone:
            clone.clone_from.return_value.active_branch.name = "main"
            process_repository_background_task(str(db.repository.id), db)

        embed.assert_not_called()

    def test_repo_with_no_files_at_all_still_fails(self):
        repo = self._run(chunks=0, manifest_only_files=0, files=0)

        self.assertEqual(repo.status, RepoStatus.FAILED)
        self.assertIn("No indexable code", repo.error_message)


class ManifestOnlyRetrieverTests(unittest.TestCase):
    def test_invoke_returns_no_documents(self):
        retriever = rag_service.ManifestOnlyRetriever()
        self.assertEqual(retriever.invoke("anything"), [])
        self.assertEqual(retriever.get_relevant_documents("anything"), [])

    def test_context_assembly_still_works_with_manifest_only_retriever(self):
        """No vectors, but an architecture question still gets the manifest."""
        manifest_text = "# Repository manifest\n\n## Languages\n- Markdown"

        with mock.patch.object(
            rag_service, "load_manifest_context", return_value=manifest_text
        ):
            context = rag_service._collect_context(
                None,
                str(uuid4()),
                "give me an overview of this repo",
                rag_service.ManifestOnlyRetriever(),
            )

        self.assertIn("## Languages", context)
        self.assertIn(rag_service.MANIFEST_CONTEXT_HEADER, context)


if __name__ == "__main__":
    unittest.main()