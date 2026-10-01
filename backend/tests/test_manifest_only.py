"""
Tests for the docs/config manifest-only rule in repo_processor.

Docs and config files are represented in the repository manifest instead of
being embedded one chunk at a time. On a doc-heavy repository that difference
was large: NVIDIA/OpenShell produced 5,330 raw_text vectors for 932 raw files,
including 555 from a single extensionless LICENSE file.

These tests exercise the real ``process_repository_files`` walk against a small
temporary repository, so they cover classification and chunking together
rather than mocking the decision.
"""

import os
import tempfile
import unittest

from app.models.chunk import Chunk
from app.models.file import File
from app.services.repo_processor import process_repository_files
from support import FakeSession, make_repository


PY_SOURCE = '''\
def greet(name):
    """Say hello."""
    return f"hello {name}"


class Greeter:
    def __init__(self, prefix):
        self.prefix = prefix

    def run(self):
        return greet(self.prefix)
'''


class ManifestOnlyDocsTests(unittest.TestCase):
    """Docs/config become manifest entries; code still becomes chunks."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        files = {
            "src/app.py": PY_SOURCE,
            "README.md": "# Title\n\nSome docs.\n",
            "config/settings.yaml": "debug: true\n",
            "package.json": '{"name": "x"}\n',
            # Extensionless license file: the 555-chunk THIRD-PARTY-NOTICES case.
            "LICENSE": "Apache License\n" * 200,
            # Filtered out for unrelated reasons; must stay out of both paths.
            "package-lock.json": '{"lockfileVersion": 3}\n',
        }
        for rel, content in files.items():
            path = os.path.join(tmp.name, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)

        self.repo = make_repository(local_path=tmp.name)
        self.db = FakeSession(self.repo)

    def file_rows(self):
        return [obj for obj in self.db.added if isinstance(obj, File)]

    def file_row(self, file_path):
        return next((f for f in self.file_rows() if f.file_path == file_path), None)

    def chunks_for(self, file_path):
        row = self.file_row(file_path)
        if row is None:
            return []
        return [
            obj
            for obj in self.db.added
            if isinstance(obj, Chunk) and obj.file_id == row.id
        ]

    def indexed_paths(self):
        return {f.file_path for f in self.file_rows()}

    def test_code_file_still_gets_structural_chunks(self):
        result = process_repository_files(str(self.repo.id), self.db)

        chunks = self.chunks_for("src/app.py")
        self.assertGreater(len(chunks), 0)
        self.assertTrue(all(c.chunk_type != "raw_text" for c in chunks))
        self.assertTrue(any(c.name == "greet" for c in chunks))
        self.assertEqual(self.file_row("src/app.py").parse_state, "structural")
        self.assertGreater(result.chunks, 0)

    def test_markdown_config_and_json_get_no_chunks(self):
        process_repository_files(str(self.repo.id), self.db)

        for path in ("README.md", "config/settings.yaml", "package.json"):
            with self.subTest(path=path):
                self.assertIsNotNone(
                    self.file_row(path), "file row should still exist in the manifest"
                )
                self.assertEqual(self.chunks_for(path), [], "docs must not be embedded")

    def test_extensionless_license_is_manifest_only(self):
        process_repository_files(str(self.repo.id), self.db)

        self.assertEqual(self.chunks_for("LICENSE"), [])
        row = self.file_row("LICENSE")
        self.assertIsNotNone(row)
        self.assertNotEqual(row.parse_state, "structural")

    def test_lockfile_is_still_filtered_out_entirely(self):
        process_repository_files(str(self.repo.id), self.db)

        self.assertNotIn("package-lock.json", self.indexed_paths())

    def test_manifest_only_files_are_counted_in_the_result(self):
        result = process_repository_files(str(self.repo.id), self.db)

        # README.md, config/settings.yaml, package.json, LICENSE
        self.assertEqual(result.manifest_only_files, 4)
        self.assertEqual(result.files, 5)

    def test_every_kept_file_still_has_a_file_row(self):
        """Nothing is dropped silently: docs lose chunks, not their File row."""
        process_repository_files(str(self.repo.id), self.db)

        paths = self.indexed_paths()
        self.assertIn("src/app.py", paths)
        self.assertIn("README.md", paths)
        self.assertIn("LICENSE", paths)

    def test_chunk_count_reflects_only_embedded_content(self):
        result = process_repository_files(str(self.repo.id), self.db)

        embedded = [obj for obj in self.db.added if isinstance(obj, Chunk)]
        self.assertEqual(result.chunks, len(embedded))
        self.assertEqual(self.repo.chunk_count, len(embedded))


if __name__ == "__main__":
    unittest.main()