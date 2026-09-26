import unittest
import uuid
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.v1 import chat, repos
from app.models.repository import RepoStatus
from app.schemas.chat import ChatRequest
from support import FakeSession, make_repository


def _payload(repo_id, session_id=None, message="what does this do?"):
    return ChatRequest(repo_id=repo_id, session_id=session_id, message=message)


def _user():
    return SimpleNamespace(id=uuid.uuid4(), is_active=True)


class HasEmbeddingsTest(unittest.TestCase):
    def test_ready_repository_reports_embeddings(self):
        repo = make_repository(status=RepoStatus.COMPLETED, chunk_count=10, embedded_count=10)
        self.assertTrue(repo.has_embeddings)

    def test_in_progress_repository_does_not(self):
        for status in (RepoStatus.PENDING, RepoStatus.CLONING, RepoStatus.PROCESSING, RepoStatus.EMBEDDING):
            repo = make_repository(status=status, chunk_count=10, embedded_count=10)
            self.assertFalse(repo.has_embeddings, f"{status} must not be queryable")

    def test_failed_repository_does_not(self):
        repo = make_repository(status=RepoStatus.FAILED, chunk_count=10, embedded_count=10)
        self.assertFalse(repo.has_embeddings)

    def test_completed_but_unindexed_repository_does_not(self):
        repo = make_repository(status=RepoStatus.COMPLETED, chunk_count=10, embedded_count=0)
        self.assertFalse(repo.has_embeddings)

    def test_partial_index_does_not(self):
        repo = make_repository(status=RepoStatus.COMPLETED, chunk_count=10, embedded_count=4)
        self.assertFalse(repo.has_embeddings)


class ReadyRepositoryGuardTest(unittest.TestCase):
    def _call(self, repo):
        payload = _payload(uuid.uuid4())
        db = FakeSession(repo)
        return chat._get_ready_repository(payload, db, current_user=_user())

    def test_missing_repository_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            self._call(None)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_unfinished_repository_is_409(self):
        repo = make_repository(status=RepoStatus.CLONING, chunk_count=5, embedded_count=0)
        with self.assertRaises(HTTPException) as ctx:
            self._call(repo)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("cloning", ctx.exception.detail)

    def test_completed_without_index_is_409(self):
        repo = make_repository(status=RepoStatus.COMPLETED, chunk_count=5, embedded_count=0)
        with self.assertRaises(HTTPException) as ctx:
            self._call(repo)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("re-import", ctx.exception.detail)

    def test_ready_repository_is_returned(self):
        repo = make_repository(status=RepoStatus.COMPLETED, chunk_count=5, embedded_count=5)
        self.assertIs(self._call(repo), repo)


class RepositorySerializationTest(unittest.TestCase):
    def test_payload_exposes_honest_readiness(self):
        ready = make_repository(status=RepoStatus.COMPLETED, chunk_count=5, embedded_count=5)
        payload = repos._serialize_repository(ready)
        self.assertTrue(payload["has_embeddings"])
        self.assertEqual(payload["status"], RepoStatus.COMPLETED)

        half = make_repository(status=RepoStatus.COMPLETED, chunk_count=5, embedded_count=0)
        self.assertFalse(repos._serialize_repository(half)["has_embeddings"])

    def test_owned_repository_lookup_rejects_other_users(self):
        db = FakeSession(None)
        with self.assertRaises(HTTPException) as ctx:
            repos._get_owned_repository(str(uuid.uuid4()), db, current_user=_user())
        self.assertEqual(ctx.exception.status_code, 404)


class ExtractRepoInfoTest(unittest.TestCase):
    def test_parses_owner_and_name(self):
        from app.services.github_service import extract_repo_info

        self.assertEqual(
            extract_repo_info("https://github.com/tiangolo/fastapi"), ("tiangolo", "fastapi")
        )
        self.assertEqual(
            extract_repo_info("https://github.com/tiangolo/fastapi.git"), ("tiangolo", "fastapi")
        )

    def test_rejects_non_repository_urls(self):
        from app.services.github_service import extract_repo_info

        with self.assertRaises(ValueError):
            extract_repo_info("https://github.com/tiangolo")


if __name__ == "__main__":
    unittest.main()
