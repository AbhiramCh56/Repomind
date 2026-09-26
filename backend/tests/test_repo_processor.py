import os
import tempfile
import unittest
from unittest import mock

from app.services import repo_processor
from support import FakeSession, make_repository


class RepoProcessorTest(unittest.TestCase):
    def _make_repo(self, files: dict):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for rel, content in files.items():
            path = os.path.join(tmp.name, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
        repo = make_repository(local_path=tmp.name)
        return repo, FakeSession(repo)

    def test_to_posix_normalizes_windows_separators(self):
        self.assertEqual(
            repo_processor._to_posix("frontend\\components").as_posix(),
            "frontend/components",
        )
        self.assertEqual(repo_processor._to_posix("").as_posix(), ".")

    def test_nested_ignore_rules_match_posix_paths(self):
        spec = repo_processor.get_ignore_spec(".")
        self.assertTrue(spec.match_file("frontend/node_modules/pkg/index.js"))
        self.assertTrue(spec.match_file("node_modules/pkg/index.js"))
        self.assertTrue(spec.match_file("__pycache__/mod.cpython-312.pyc"))
        self.assertFalse(spec.match_file("frontend/src/App.tsx"))

    def test_nested_ignored_directories_are_not_indexed(self):
        repo, db = self._make_repo(
            {
                "main.py": "def main():\n    return 1\n",
                "frontend/node_modules/left-pad/index.js": "module.exports = 1\n",
                "frontend/src/App.tsx": "export default function App() {}\n",
                "dist/bundle.js": "console.log(1)\n",
            }
        )

        result = repo_processor.process_repository_files(str(repo.id), db)

        indexed = {f.file_path for f in db.files()}
        self.assertIn("main.py", indexed)
        self.assertIn("frontend/src/App.tsx", indexed)
        self.assertNotIn("frontend/node_modules/left-pad/index.js", indexed)
        self.assertNotIn("dist/bundle.js", indexed)
        self.assertGreater(result.chunks, 0)
        self.assertEqual(result.errors, [])

    def test_file_paths_are_stored_with_forward_slashes(self):
        repo, db = self._make_repo({"a/b/c/deep.py": "x = 1\n"})

        repo_processor.process_repository_files(str(repo.id), db)

        self.assertEqual([f.file_path for f in db.files()], ["a/b/c/deep.py"])

    def test_counts_are_written_back_to_the_repository(self):
        repo, db = self._make_repo({"main.py": "def main():\n    return 1\n"})

        result = repo_processor.process_repository_files(str(repo.id), db)

        self.assertEqual(repo.chunk_count, result.chunks)
        self.assertEqual(repo.embedded_count, 0)
        self.assertEqual(result.files, 1)

    def test_one_broken_file_does_not_discard_the_others(self):
        repo, db = self._make_repo(
            {
                "good.py": "x = 1\n",
                "broken.md": "BOOM\n",
                "also_good.py": "y = 2\n",
            }
        )

        real_chunker = repo_processor.naive_chunker

        def flaky(source_code, chunk_size=None):
            if "BOOM" in source_code:
                raise ValueError("simulated chunker failure")
            return real_chunker(source_code, chunk_size)

        with mock.patch.object(repo_processor, "naive_chunker", flaky):
            result = repo_processor.process_repository_files(str(repo.id), db)

        self.assertEqual(result.files, 2)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("broken.md", result.errors[0])
        self.assertEqual(repo.chunk_count, result.chunks)

    def test_oversized_files_are_skipped(self):
        repo, db = self._make_repo({"small.py": "x = 1\n"})
        with mock.patch.object(repo_processor.settings, "MAX_FILE_SIZE_BYTES", 1):
            result = repo_processor.process_repository_files(str(repo.id), db)

        self.assertEqual(result.files, 0)
        self.assertEqual(result.chunks, 0)

    def test_detect_language(self):
        self.assertEqual(repo_processor.detect_language("app.py"), "Python")
        self.assertEqual(repo_processor.detect_language("App.tsx"), "React (TypeScript)")
        self.assertEqual(repo_processor.detect_language("Dockerfile"), "Dockerfile")
        self.assertEqual(repo_processor.detect_language("mystery.zzz"), "Unknown")

    def test_naive_chunker_uses_configured_size(self):
        with mock.patch.object(repo_processor.settings, "CHUNK_SIZE_CHARS", 10):
            chunks = repo_processor.naive_chunker("\n".join(f"line {i}" for i in range(10)))
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(chunk["chunk_type"], "raw_text")

    def test_missing_checkout_raises(self):
        repo = make_repository(local_path=None)
        with self.assertRaises(ValueError):
            repo_processor.process_repository_files(str(repo.id), FakeSession(repo))


if __name__ == "__main__":
    unittest.main()
