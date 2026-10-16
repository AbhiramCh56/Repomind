import unittest
import uuid

from app.models.file import File
from app.models.repository import RepoStatus
from app.services import manifest_service
from app.services.manifest_service import compute_live_file_ids
from support import FakeSession, make_repository


class ComputeLiveFileIdsTest(unittest.TestCase):
    """
    Pure prefix math behind the live architecture preview.

    ``counts`` arrives in embedding order (file path order), so the first
    ``embedded_count`` chunks cover whole files except possibly one boundary
    file. Drifting from embedding order silently mislabels files as available,
    which is why these cases exist.
    """

    def test_nothing_embedded_keeps_only_manifest_only_files(self):
        counts = [("readme", 0), ("a", 3), ("b", 2)]
        self.assertEqual(compute_live_file_ids(counts, 0), {"readme"})

    def test_exact_prefix_includes_the_boundary_file(self):
        counts = [("a", 2), ("b", 3), ("c", 1)]
        self.assertEqual(compute_live_file_ids(counts, 5), {"a", "b"})

    def test_partial_boundary_excludes_it_and_everything_after(self):
        counts = [("a", 2), ("b", 3), ("c", 1)]
        self.assertEqual(compute_live_file_ids(counts, 3), {"a"})

    def test_manifest_only_file_after_the_boundary_still_joins(self):
        counts = [("a", 4), ("docs", 0), ("z", 1)]
        self.assertEqual(compute_live_file_ids(counts, 1), {"docs"})

    def test_all_embedded_joins_every_file(self):
        counts = [("a", 2), ("b", 3)]
        self.assertEqual(compute_live_file_ids(counts, 5), {"a", "b"})

    def test_an_empty_repository_has_no_live_files(self):
        self.assertEqual(compute_live_file_ids([], 10), set())

    def test_a_docs_only_repository_is_fully_live_immediately(self):
        counts = [("readme", 0), ("license", 0)]
        self.assertEqual(compute_live_file_ids(counts, 0), {"readme", "license"})


class BuildLiveManifestTest(unittest.TestCase):
    def _file(self, file_id, path):
        return File(
            id=uuid.UUID(file_id),
            file_path=path,
            language="Python",
            parse_state="structural",
            size_bytes=10,
        )

    def test_only_files_with_embedded_chunks_appear(self):
        repo = make_repository(
            status=RepoStatus.EMBEDDING, chunk_count=5, embedded_count=3
        )
        ids = {"a": str(uuid.uuid4()), "b": str(uuid.uuid4())}
        counts = [(ids["a"], "app/a.py", 2), (ids["b"], "app/b.py", 3)]
        files = [self._file(ids["a"], "app/a.py"), self._file(ids["b"], "app/b.py")]

        db = FakeSession(repo, query_results=[counts, files])
        result = manifest_service.build_live_manifest(db, repo)

        self.assertEqual([e.file_path for e in result.manifest.entries], ["app/a.py"])
        self.assertEqual(result.live_files, 1)
        self.assertEqual(result.total_files, 2)

    def test_processing_state_with_no_chunks_shows_nothing(self):
        repo = make_repository(
            status=RepoStatus.PROCESSING, chunk_count=0, embedded_count=0
        )
        ids = {"a": str(uuid.uuid4())}
        counts = [(ids["a"], "app/a.py", 4)]
        files = [self._file(ids["a"], "app/a.py")]

        db = FakeSession(repo, query_results=[counts, files])
        result = manifest_service.build_live_manifest(db, repo)

        self.assertEqual(result.manifest.entries, [])
        self.assertEqual(result.live_files, 0)
        self.assertEqual(result.total_files, 1)


if __name__ == "__main__":
    unittest.main()
