"""
Tests for architecture-question routing (app.ai.manifest_routing).

Docs and config are no longer embedded, so an architecture question has to reach
the manifest. These tests pin the router's decisions and the degradation path
when no manifest exists.
"""

import unittest
from unittest import mock

from app.ai import manifest_routing
from app.ai.manifest_routing import (
    is_architecture_question,
    load_manifest_context,
)


class ArchitectureDetectionTests(unittest.TestCase):
    def test_layout_questions_route(self):
        for question in (
            "give me an overview of this repo",
            "How is this repository organized?",
            "what is the project structure",
            "where does the application start?",
            "show me the directory structure",
            "what languages does this use",
            "what are the entrypoints?",
            "describe the architecture of this codebase",
            "which modules are the largest?",
            "what's the tech stack",
            "summarize the codebase structure",
        ):
            with self.subTest(question=question):
                self.assertTrue(is_architecture_question(question))

    def test_implementation_questions_do_not_route(self):
        for question in (
            "where is the retry logic implemented",
            "what does UserService do",
            "fix the bug in handle_login",
            "how does the JWT middleware work",
            "explain this function",
            "what arguments does parse_config take",
        ):
            with self.subTest(question=question):
                self.assertFalse(is_architecture_question(question))

    def test_empty_question_does_not_route(self):
        self.assertFalse(is_architecture_question(""))
        self.assertFalse(is_architecture_question("   "))
        self.assertFalse(is_architecture_question(None))

    def test_word_boundary_avoids_false_positives(self):
        """'class' must not fire on 'classic', 'overview' must not fire mid-word."""
        self.assertFalse(is_architecture_question("what does the classic handler do"))
        self.assertFalse(is_architecture_question("is this browserview component good"))

    def test_detector_is_case_insensitive(self):
        self.assertTrue(is_architecture_question("REPOSITORY OVERVIEW"))
        self.assertTrue(is_architecture_question("Entry Points"))


class OverviewMarkdownTests(unittest.TestCase):
    MARKDOWN = """# Repository manifest: acme/widget

## Languages
- Python: 2 files

## Likely entrypoints
- `app.py` (Python)

## Largest directories
- `src` - 2 files

## Symbols by language
### Python
- `greet` (function)
- `Greeter` (class)

## Docs and config inventory
- `README.md`
"""

    def test_symbol_dump_is_dropped(self):
        overview = manifest_routing._overview_markdown(self.MARKDOWN)

        self.assertIn("# Repository manifest: acme/widget", overview)
        self.assertIn("## Likely entrypoints", overview)
        self.assertIn("## Largest directories", overview)
        self.assertNotIn("## Symbols by language", overview)
        self.assertNotIn("Greeter", overview)

    def test_manifest_without_symbol_section_is_returned_intact(self):
        markdown = "# Repository manifest: acme/widget\n\n## Languages\n- Python\n"
        self.assertEqual(
            manifest_routing._overview_markdown(markdown).strip(), markdown.strip()
        )


class LoadManifestContextTests(unittest.TestCase):
    def test_missing_manifest_returns_none(self):
        with mock.patch.object(
            manifest_routing, "get_manifest", return_value=None
        ):
            self.assertIsNone(load_manifest_context(None, "repo-1"))

    def test_blank_markdown_returns_none(self):
        row = type("Row", (), {"markdown": ""})()
        with mock.patch.object(
            manifest_routing, "get_manifest", return_value=row
        ):
            self.assertIsNone(load_manifest_context(None, "repo-1"))

    def test_lookup_error_degrades_instead_of_raising(self):
        with mock.patch.object(
            manifest_routing,
            "get_manifest",
            side_effect=RuntimeError("db down"),
        ):
            self.assertIsNone(load_manifest_context(None, "repo-1"))

    def test_markdown_is_returned_and_trimmed(self):
        markdown = (
            "# Repository manifest: acme/widget\n\n## Languages\n- Python\n\n"
            "## Symbols by language\n- `greet`\n"
        )
        row = type("Row", (), {"markdown": markdown})()
        with mock.patch.object(
            manifest_routing, "get_manifest", return_value=row
        ):
            context = load_manifest_context(None, "repo-1")

        self.assertIn("## Languages", context)
        self.assertNotIn("`greet`", context)

    def test_long_manifest_is_truncated_with_a_marker(self):
        markdown = "# Manifest\n\n" + ("x" * 500)
        row = type("Row", (), {"markdown": markdown})()
        with mock.patch.object(
            manifest_routing, "get_manifest", return_value=row
        ):
            context = load_manifest_context(None, "repo-1", max_chars=100)

        self.assertTrue(context.endswith("(manifest truncated)"))
        self.assertLess(len(context), 200)


class ContextAssemblyTests(unittest.TestCase):
    """The retriever must keep working whether or not routing fires."""

    def setUp(self):
        from app.services import rag_service

        self.rag_service = rag_service

    def _retriever(self, docs):
        class _Retriever:
            def invoke(self, question):
                return [type("D", (), {"page_content": d})() for d in docs]

        return _Retriever()

    def _collect(self, question, docs):
        # Patch rag_service's own reference: it imports load_manifest_context by
        # name, so patching the manifest_routing module would not take effect
        # here if that module was imported earlier in the session.
        return self.rag_service._collect_context(
            None, "repo-1", question, self._retriever(docs)
        )

    def test_non_architecture_question_gets_only_vector_context(self):
        with mock.patch.object(
            self.rag_service, "load_manifest_context"
        ) as loader:
            context = self._collect("where is retry implemented", ["retry code"])

        loader.assert_not_called()
        self.assertEqual(context, "retry code")

    def test_architecture_question_prepends_manifest(self):
        manifest_text = "# Repository manifest\n\n## Languages\n- Python"
        with mock.patch.object(
            self.rag_service, "load_manifest_context", return_value=manifest_text
        ) as loader:
            context = self._collect("give me an overview", ["some code"])

        loader.assert_called_once_with(None, "repo-1")
        self.assertTrue(context.startswith("Repository manifest"))
        self.assertIn("## Languages", context)
        # Vector context is still present, not replaced.
        self.assertIn("some code", context)

    def test_architecture_question_without_manifest_falls_back(self):
        """A missing manifest degrades to plain retrieval instead of failing."""
        with mock.patch.object(
            self.rag_service, "load_manifest_context", return_value=None
        ):
            context = self._collect("give me an overview", ["some code"])

        self.assertEqual(context, "some code")


if __name__ == "__main__":
    unittest.main()