"""
Tests for the deterministic repository manifest (app.ai.structure).

The manifest is the architecture summary used by ``GET /{repo_id}/structure``.
These tests cover the deterministic aggregation, entrypoint ranking, doc/config
classification, and markdown rendering. No database and no LLM involved.
"""

import unittest

from app.ai.structure import (
    MAX_SYMBOLS_PER_LANGUAGE_IN_MARKDOWN,
    ManifestEntry,
    build_manifest_from_parse,
    build_manifest_from_rows,
)


class _FakeFile:
    """Minimal stand-in for an ORM ``File`` row."""

    def __init__(self, file_path, language, parse_state, size_bytes=100):
        self.file_path = file_path
        self.language = language
        self.parse_state = parse_state
        self.size_bytes = size_bytes


def _sym(name, kind, start=1, end=5):
    return {"name": name, "kind": kind, "start_line": start, "end_line": end}


class ManifestFromRowsTests(unittest.TestCase):
    def build(self, files, symbols=None):
        symbols = symbols or {}
        return build_manifest_from_rows(
            repository_id="repo-1", full_name="acme/widget", files=files, symbols_by_file=symbols
        )

    def test_language_breakdown_splits_structural_from_raw(self):
        manifest = self.build(
            [
                _FakeFile("src/a.py", "Python", "structural"),
                _FakeFile("src/b.py", "Python", "structural"),
                _FakeFile("README.md", "Markdown", "raw_unmapped"),
                _FakeFile("Cargo.toml", "TOML", "raw_unmapped"),
            ],
            {
                "src/a.py": [_sym("run", "function")],
                "src/b.py": [_sym("Config", "class")],
            },
        )

        languages = manifest.languages
        self.assertEqual(languages["Python"]["files"], 2)
        self.assertEqual(languages["Python"]["structural_files"], 2)
        self.assertEqual(languages["Python"]["raw_files"], 0)
        self.assertEqual(languages["Python"]["symbols"], 2)
        self.assertEqual(languages["Markdown"]["raw_files"], 1)

    def test_symbols_only_counted_for_structural_files(self):
        """A raw file's chunks are docs, not a symbol index."""
        manifest = self.build(
            [
                _FakeFile("src/a.py", "Python", "structural"),
                _FakeFile("NOTES.md", "Markdown", "raw_unmapped"),
            ],
            {
                "src/a.py": [_sym("run", "function")],
                "NOTES.md": [_sym("Heading", "raw_text"), _sym("Intro", "raw_text")],
            },
        )

        totals = manifest.to_payload()["totals"]
        self.assertEqual(totals["symbols"], 1)
        self.assertEqual(totals["structural_files"], 1)
        self.assertEqual(totals["doc_files"], 1)

    def test_doc_files_reports_doc_chunk_counts(self):
        manifest = self.build(
            [_FakeFile("LICENSE", None, "raw_unmapped", size_bytes=40000)],
            {"LICENSE": [_sym(f"part{i}", "raw_text") for i in range(3)]},
        )

        docs = manifest.doc_files
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["path"], "LICENSE")
        self.assertEqual(docs[0]["language"], "Unknown")
        self.assertEqual(docs[0]["doc_chunks"], 3)

    def test_null_parse_state_is_treated_as_non_structural(self):
        """Rows predating parse_state must not be claimed as structural."""
        manifest = self.build([_FakeFile("old.py", "Python", None)])

        self.assertEqual(manifest.to_payload()["totals"]["structural_files"], 0)
        self.assertEqual(manifest.to_payload()["totals"]["doc_files"], 1)

    def test_directory_rollup_counts_root_level_files_as_dot(self):
        manifest = self.build(
            [
                _FakeFile("README.md", "Markdown", "raw_unmapped"),
                _FakeFile("src/a.py", "Python", "structural"),
                _FakeFile("src/b.py", "Python", "structural"),
            ]
        )

        by_path = {d["path"]: d for d in manifest.directories}
        self.assertEqual(by_path["."]["files"], 1)
        self.assertEqual(by_path["src"]["files"], 2)
        # Sorted by file count descending.
        self.assertEqual(manifest.directories[0]["path"], "src")

    def test_building_twice_is_deterministic(self):
        files = [
            _FakeFile("src/a.py", "Python", "structural"),
            _FakeFile("README.md", "Markdown", "raw_unmapped"),
        ]
        symbols = {"src/a.py": [_sym("run", "function")]}

        first = self.build(files, symbols).to_payload()
        second = self.build(files, symbols).to_payload()
        self.assertEqual(first, second)

    def test_empty_repository_produces_valid_manifest(self):
        manifest = self.build([])
        payload = manifest.to_payload()

        self.assertEqual(payload["totals"]["files"], 0)
        self.assertEqual(payload["languages"], {})
        self.assertEqual(payload["entrypoints"], [])
        self.assertIn("# Repository manifest: acme/widget", manifest.to_markdown())


class EntrypointTests(unittest.TestCase):
    def score_via_manifest(self, path):
        manifest = build_manifest_from_rows(
            repository_id="r",
            full_name="a/b",
            files=[_FakeFile(path, "Rust", "structural")],
            symbols_by_file={},
        )
        found = manifest.entrypoints
        return found[0]["score"] if found else 0

    def test_rust_main_beats_lib(self):
        self.assertGreater(
            self.score_via_manifest("crates/x/src/main.rs"),
            self.score_via_manifest("crates/x/src/lib.rs"),
        )

    def test_src_bin_is_a_strong_candidate(self):
        self.assertGreaterEqual(
            self.score_via_manifest("crates/x/src/bin/tool.rs"), 8
        )

    def test_conventional_python_and_dockerfile(self):
        self.assertGreater(self.score_via_manifest("app.py"), 0)
        self.assertGreater(self.score_via_manifest("Dockerfile"), 0)

    def test_ordinary_source_file_is_not_an_entrypoint(self):
        self.assertEqual(self.score_via_manifest("src/internal/parser.rs"), 0)

    def test_entrypoints_are_ranked_and_capped(self):
        files = [
            _FakeFile(f"crates/c{i}/src/main.rs", "Rust", "structural") for i in range(80)
        ]
        manifest = build_manifest_from_rows(
            repository_id="r", full_name="a/b", files=files, symbols_by_file={}
        )

        payload = manifest.to_payload()
        self.assertLessEqual(len(payload["entrypoints"]), 40)
        scores = [e["score"] for e in payload["entrypoints"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_entrypoints_deduplicated_by_path(self):
        files = [_FakeFile("app.py", "Python", "structural")]
        manifest = build_manifest_from_rows(
            repository_id="r", full_name="a/b", files=files, symbols_by_file={}
        )
        self.assertEqual(len(manifest.entrypoints), 1)


class MarkdownRenderingTests(unittest.TestCase):
    def test_markdown_is_ascii_and_contains_key_sections(self):
        manifest = build_manifest_from_rows(
            repository_id="r",
            full_name="acme/widget",
            files=[
                _FakeFile("src/main.py", "Python", "structural"),
                _FakeFile("README.md", "Markdown", "raw_unmapped"),
            ],
            symbols_by_file={"src/main.py": [_sym("main", "function")]},
        )

        markdown = manifest.to_markdown()
        markdown.encode("ascii")  # raises if a non-ASCII separator crept in

        self.assertIn("# Repository manifest: acme/widget", markdown)
        self.assertIn("## Languages", markdown)
        self.assertIn("## Likely entrypoints", markdown)
        self.assertIn("## Symbols by language", markdown)
        self.assertIn("## Docs and config inventory", markdown)
        self.assertIn("`main`", markdown)
        self.assertIn("`README.md`", markdown)

    def test_symbol_listing_is_capped_but_json_is_complete(self):
        symbols = [_sym(f"fn{i}", "function", start=i) for i in range(MAX_SYMBOLS_PER_LANGUAGE_IN_MARKDOWN + 25)]
        manifest = build_manifest_from_rows(
            repository_id="r",
            full_name="a/b",
            files=[_FakeFile("src/a.py", "Python", "structural")],
            symbols_by_file={"src/a.py": symbols},
        )

        markdown = manifest.to_markdown()
        self.assertIn("more Python symbols omitted", markdown)

        payload = manifest.to_payload()
        self.assertEqual(
            len(payload["symbols"]["Python"]),
            MAX_SYMBOLS_PER_LANGUAGE_IN_MARKDOWN + 25,
        )

    def test_backslash_paths_normalize_to_posix(self):
        manifest = build_manifest_from_rows(
            repository_id="r",
            full_name="a/b",
            files=[_FakeFile("src\\nested\\a.py", "Python", "structural")],
            symbols_by_file={},
        )
        self.assertEqual(manifest.directories[0]["path"], "src/nested")


class ParsePathEquivalenceTests(unittest.TestCase):
    def test_parse_path_and_row_path_agree(self):
        """A live parse and a backfill must produce the same manifest."""
        entries = [
            ManifestEntry(
                file_path="src/a.py",
                language="Python",
                parse_state="structural",
                size_bytes=100,
                symbols=[_sym("run", "function")],
            ),
            ManifestEntry(
                file_path="README.md",
                language="Markdown",
                parse_state="raw_unmapped",
                size_bytes=100,
            ),
        ]
        from_parse = build_manifest_from_parse("r", "a/b", entries).to_payload()

        from_rows = build_manifest_from_rows(
            repository_id="r",
            full_name="a/b",
            files=[
                # Match the ManifestEntry above so the payloads are comparable.
                _FakeFile("src/a.py", "Python", "structural", size_bytes=100),
                _FakeFile("README.md", "Markdown", "raw_unmapped", size_bytes=100),
            ],
            symbols_by_file={"src/a.py": [_sym("run", "function")]},
        ).to_payload()

        self.maxDiff = None
        self.assertEqual(from_parse, from_rows)


if __name__ == "__main__":
    unittest.main()