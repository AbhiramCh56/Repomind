import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from app.ai.structure import build_manifest_from_rows
from app.api.v1 import repos
from app.models.repository import RepoStatus
from app.services.manifest_service import LiveManifest
from support import FakeSession, make_repository


def _user():
    return SimpleNamespace(id=uuid.uuid4(), is_active=True)


def _manifest():
    files = [
        SimpleNamespace(
            file_path="app/main.py",
            language="Python",
            parse_state="structural",
            size_bytes=20,
        )
    ]
    return build_manifest_from_rows(
        repository_id="r", full_name="acme/demo", files=files, symbols_by_file={}
    )


class LiveDiagramsTest(unittest.TestCase):
    def test_in_progress_repository_returns_a_live_preview(self):
        repo = make_repository(
            status=RepoStatus.EMBEDDING, chunk_count=10, embedded_count=4
        )
        db = FakeSession(repo)
        live = LiveManifest(manifest=_manifest(), live_files=1, total_files=3)

        with mock.patch.object(repos, "build_live_manifest", return_value=live):
            response = repos.get_repository_diagrams(
                str(repo.id), db, current_user=_user()
            )

        self.assertTrue(response.partial)
        self.assertEqual(response.status, RepoStatus.EMBEDDING)
        self.assertEqual(response.progress.embedded, 4)
        self.assertEqual(response.progress.chunk_count, 10)
        self.assertEqual(response.progress.live_files, 1)
        self.assertEqual(response.progress.total_files, 3)
        self.assertIn("directories", response.diagrams)
        self.assertIn("app/main.py", response.diagrams["entrypoints"])
        # The structured form is what the SVG renderer consumes.
        self.assertEqual(response.graphs["directories"]["type"], "tree")
        self.assertIn(
            "app/main.py",
            response.graphs["entrypoints"]["edges"][0]["target"],
        )

    def test_cloning_repository_still_returns_a_preview(self):
        repo = make_repository(status=RepoStatus.CLONING)
        db = FakeSession(repo)
        live = LiveManifest(manifest=_manifest(), live_files=0, total_files=0)

        with mock.patch.object(repos, "build_live_manifest", return_value=live):
            response = repos.get_repository_diagrams(
                str(repo.id), db, current_user=_user()
            )

        self.assertTrue(response.partial)
        self.assertEqual(response.status, RepoStatus.CLONING)

    def test_failed_repository_is_409(self):
        repo = make_repository(status=RepoStatus.FAILED)
        db = FakeSession(repo)

        with self.assertRaises(HTTPException) as ctx:
            repos.get_repository_diagrams(str(repo.id), db, current_user=_user())

        self.assertEqual(ctx.exception.status_code, 409)

    def test_completed_repository_uses_the_stored_manifest(self):
        repo = make_repository(
            status=RepoStatus.COMPLETED, chunk_count=2, embedded_count=2
        )
        db = FakeSession(repo)
        row = SimpleNamespace(manifest_json=_manifest().to_payload(), file_count=1)

        with mock.patch.object(repos, "get_manifest", return_value=row):
            response = repos.get_repository_diagrams(
                str(repo.id), db, current_user=_user()
            )

        self.assertFalse(response.partial)
        self.assertEqual(response.progress.live_files, 1)
        self.assertEqual(response.progress.total_files, 1)
        # Stored manifests are serialized to both representations as well.
        self.assertEqual(response.graphs["languages"]["type"], "pie")
        self.assertEqual(response.graphs["directories"]["nodes"][0]["id"], "root")

    def test_completed_repository_without_a_manifest_builds_one(self):
        repo = make_repository(status=RepoStatus.COMPLETED)
        db = FakeSession(repo)
        row = SimpleNamespace(manifest_json=_manifest().to_payload(), file_count=1)

        with mock.patch.object(repos, "get_manifest", return_value=None), mock.patch.object(
            repos, "build_and_persist_manifest", return_value=row
        ):
            response = repos.get_repository_diagrams(
                str(repo.id), db, current_user=_user()
            )

        self.assertFalse(response.partial)

    def test_other_users_cannot_see_a_repository(self):
        db = FakeSession(None)

        with self.assertRaises(HTTPException) as ctx:
            repos.get_repository_diagrams(
                str(uuid.uuid4()), db, current_user=_user()
            )

        self.assertEqual(ctx.exception.status_code, 404)


class StructureStaysGatedTest(unittest.TestCase):
    """
    The live preview is a diagrams-only exception: the structure manifest keeps
    its is_complete gate (see the docs/config rule in AGENTS.md).
    """

    def test_structure_endpoints_refuse_an_in_progress_repository(self):
        repo = make_repository(
            status=RepoStatus.EMBEDDING, chunk_count=5, embedded_count=1
        )
        db = FakeSession(repo)

        for endpoint in (
            repos.get_repository_structure,
            repos.get_repository_structure_markdown,
        ):
            with self.assertRaises(HTTPException) as ctx:
                endpoint(str(repo.id), db, current_user=_user())
            self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
