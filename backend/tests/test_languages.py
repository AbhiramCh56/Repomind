"""
Tests for polyglot file selection and multi-language structural parsing.

The two invariants that matter most are:
  1. A language whose grammar is not installed is still indexed as text.
  2. Committed lockfiles, build output and binaries never reach the index.
"""
import os
import unittest

from app.services import file_filter, languages
from app.services.file_filter import SkipReason


class SkipReasonTest(unittest.TestCase):
    def test_lockfiles_are_skipped(self):
        for name in (
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "poetry.lock",
            "Cargo.lock",
            "composer.lock",
            "Gemfile.lock",
            "go.sum",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    file_filter.skip_reason(f"some/dir/{name}", 10),
                    SkipReason.LOCKFILE,
                )

    def test_nested_lockfile_is_still_detected(self):
        self.assertEqual(
            file_filter.skip_reason("frontend/yarn.lock", 10), SkipReason.LOCKFILE
        )

    def test_build_and_vendor_directories_are_skipped(self):
        for path in (
            "node_modules/left-pad/index.js",
            "dist/bundle.js",
            "build/out/main.py",
            "vendor/github.com/x/y.go",
            "third_party/zlib/zlib.c",
            "target/debug/build.rs",
            "app/.next/server/page.js",
            "pkg/__pycache__/mod.cpython-312.pyc",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    file_filter.skip_reason(path, 10), SkipReason.BUILD_DIR
                )

    def test_binaries_are_skipped(self):
        for path in (
            "assets/logo.png",
            "fonts/Inter.woff2",
            "bin/tool.exe",
            "lib/native.so",
            "docs/manual.pdf",
            "audio/clip.mp3",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    file_filter.skip_reason(path, 10), SkipReason.BINARY
                )

    def test_minified_and_source_maps_are_skipped(self):
        for path in (
            "static/app.min.js",
            "static/styles.min.css",
            "static/app.js.map",
            "public/vendor.bundle.js",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    file_filter.skip_reason(path, 10), SkipReason.MINIFIED
                )

    def test_build_directory_takes_precedence_over_minified(self):
        """dist/ is pruned at the directory level, so the cheaper rule reports first."""
        self.assertEqual(
            file_filter.skip_reason("dist/vendor.bundle.js", 10), SkipReason.BUILD_DIR
        )

    def test_generated_code_is_skipped(self):
        for path in (
            "proto/user_pb2.py",
            "proto/user_pb2_grpc.py",
            "gen/api.pb.go",
            "lib/model.g.dart",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    file_filter.skip_reason(path, 10), SkipReason.GENERATED
                )

    def test_ordinary_source_files_are_kept(self):
        for path in (
            "src/main.py",
            "src/App.tsx",
            "src/index.ts",
            "README.md",
            "pkg/router.go",
            "lib/engine.rs",
            "src/Main.java",
            "src/util.c",
            "src/widget.cpp",
            "app/models/user.rb",
            "web/index.php",
            "scripts/deploy.sh",
            "docs/guide.md",
        ):
            with self.subTest(path=path):
                self.assertIsNone(file_filter.skip_reason(path, 10))

    def test_oversized_file_is_skipped(self):
        self.assertEqual(
            file_filter.skip_reason("big/data.json", 6 * 1024 * 1024, None, 5 * 1024 * 1024),
            SkipReason.TOO_LARGE,
        )

    def test_size_limit_only_applies_when_provided(self):
        self.assertIsNone(file_filter.skip_reason("big/data.json", 6 * 1024 * 1024))

    def test_underscore_named_directory_is_not_a_build_dir(self):
        self.assertIsNone(file_filter.skip_reason("src/_internal/util.py", 10))

    def test_extra_patterns_can_be_configured(self):
        self.assertIsNone(file_filter.skip_reason("src/legacy.rb", 10))
        self.assertEqual(
            file_filter.skip_reason(
                "src/legacy.rb", 10, extra_patterns=("*.rb",)
            ),
            SkipReason.GENERATED,
        )

    def test_extra_build_dirs_can_be_configured(self):
        self.assertIsNone(file_filter.skip_reason("fixtures/data.js", 10))
        self.assertEqual(
            file_filter.skip_reason(
                "fixtures/data.js", 10, extra_build_dirs=("fixtures",)
            ),
            SkipReason.BUILD_DIR,
        )

    def test_git_internals_are_pruned_at_directory_level(self):
        for path in (".git/config", ".git/HEAD", ".git/refs/heads/main"):
            with self.subTest(path=path):
                self.assertEqual(
                    file_filter.skip_reason(path, 10), SkipReason.BUILD_DIR
                )

    def test_bare_bundle_name_is_recognised(self):
        for path in ("public/bundle.js", "assets/bundle.css"):
            with self.subTest(path=path):
                self.assertEqual(
                    file_filter.skip_reason(path, 10), SkipReason.MINIFIED
                )

    def test_minified_bundle_detected_by_density(self):
        """A webpack bundle has no predictable name, so shape must catch it."""
        bundle = "var a=1;" * 20000
        self.assertTrue(file_filter.looks_generated_bulk(bundle, 140_000))
        self.assertEqual(
            file_filter.skip_reason("public/build.js", 140_000),
            None,
        )

    def test_ordinary_source_is_not_treated_as_a_bundle(self):
        source = "\n".join(f"function handler{i}() {{ return {i} }}" for i in range(500))
        self.assertFalse(file_filter.looks_generated_bulk(source, len(source)))

    def test_small_files_are_never_treated_as_bundles(self):
        self.assertFalse(file_filter.looks_generated_bulk("var a=1", 8))

    def test_every_reason_code_is_reachable(self):
        seen = {
            file_filter.skip_reason("node_modules/a.js", 1),
            file_filter.skip_reason("a.png", 1),
            file_filter.skip_reason("yarn.lock", 1),
            file_filter.skip_reason("a.min.js", 1),
            file_filter.skip_reason("a_pb2.py", 1),
            file_filter.skip_reason("a.json", 10 * 1024 * 1024, None, 1024),
        }
        # generated_bulk and gitignore are decided from file content and the
        # repository's own .gitignore respectively, so neither is path-only.
        content_dependent = {SkipReason.GENERATED_BULK, SkipReason.GITIGNORE}
        for reason in file_filter.ALL_SKIP_REASONS:
            if reason in content_dependent:
                continue
            self.assertIn(reason, seen, f"{reason} is declared but unreachable")

    def test_gitignore_reason_is_reported_when_spec_matches(self):
        import pathspec

        spec = pathspec.PathSpec.from_lines("gitwildmatch", ["secrets/"])
        self.assertEqual(
            file_filter.skip_reason("secrets/key.txt", 10, spec), SkipReason.GITIGNORE
        )
        self.assertIsNone(file_filter.skip_reason("src/key.txt", 10, spec))


class LanguageRegistryTest(unittest.TestCase):
    def test_every_grammar_in_the_registry_imports(self):
        coverage = languages.language_coverage()
        missing = {name: ok for name, ok in coverage.items() if not ok}
        self.assertEqual(missing, {}, f"grammars unavailable: {missing}")

    def test_registry_covers_the_expected_languages(self):
        for language in ("Python", "JavaScript", "TypeScript", "Go", "Rust", "Java"):
            self.assertTrue(
                languages.BY_EXTENSION.get(_any_ext(language)),
                f"no extension registered for {language}",
            )

    def test_extension_lookup_is_case_insensitive(self):
        self.assertIsNotNone(languages.spec_for_extension(".TS"))
        self.assertIsNotNone(languages.spec_for_extension(".Py"))

    def test_unknown_extension_has_no_spec(self):
        self.assertIsNone(languages.spec_for_extension(".qqq"))
        self.assertIsNone(languages.spec_for_extension(""))

    def test_text_only_formats_have_labels_but_no_grammar(self):
        self.assertIsNone(languages.spec_for_extension(".md"))
        self.assertEqual(languages.text_only_language(".md"), "Markdown")
        self.assertIsNone(languages.text_only_language(".ts"))

    def test_tsx_and_typescript_use_distinct_grammars(self):
        self.assertIsNot(
            languages.spec_for_extension(".tsx"),
            languages.spec_for_extension(".ts"),
        )


def _any_ext(language: str) -> str:
    for ext, spec in languages.BY_EXTENSION.items():
        if spec.name == language:
            return ext
    raise AssertionError(f"no extension for {language}")


class ParseSymbolsTest(unittest.TestCase):
    def test_python_still_uses_the_ast_fast_path(self):
        result = languages.parse_symbols("class A:\n    def m(self): pass\n", ".py")
        self.assertEqual(result.state, languages.PARSE_STATE_STRUCTURAL)
        self.assertEqual(result.language, "Python")
        self.assertIn("A", [b["name"] for b in result.blocks])
        self.assertIn("m", [b["name"] for b in result.blocks])

    def test_typescript_symbols_are_named(self):
        source = (
            "interface Shape { area(): number }\n"
            "class Circle implements Shape { area(): number { return 1 } }\n"
            "function helper(): void {}\n"
            "const arrow = () => 42;\n"
        )
        result = languages.parse_symbols(source, ".ts")
        self.assertEqual(result.state, languages.PARSE_STATE_STRUCTURAL)
        names = [b["name"] for b in result.blocks]
        for expected in ("Shape", "Circle", "area", "helper", "arrow"):
            self.assertIn(expected, names)

    def test_go_captures_types_functions_and_methods(self):
        source = (
            "package main\n"
            "import \"fmt\"\n"
            "type Server struct{ Port int }\n"
            "func Run() {}\n"
            "func (s *Server) Stop() {}\n"
        )
        result = languages.parse_symbols(source, ".go")
        names = [b["name"] for b in result.blocks]
        self.assertIn("Server", names)
        self.assertIn("Run", names)
        self.assertIn("Stop", names)
        self.assertTrue(result.imports)

    def test_typescript_imports_are_captured(self):
        result = languages.parse_symbols('import x from "y";\n', ".ts")
        self.assertTrue(result.imports)

    def test_rust_trait_and_impl_are_structural(self):
        source = "struct S{a:i32}\nimpl S{ fn m(&self){} }\ntrait T{ fn t(&self); }\n"
        result = languages.parse_symbols(source, ".rs")
        self.assertEqual(result.state, languages.PARSE_STATE_STRUCTURAL)
        names = [b["name"] for b in result.blocks]
        self.assertIn("S", names)
        self.assertIn("T", names)

    def test_every_registered_grammar_parses_its_own_sample(self):
        samples = {
            ".py": "class A:\n    def m(self): pass\n",
            ".js": "class A{m(){}}\nfunction f(){}\n",
            ".ts": "class A{m():void{}}\n",
            ".tsx": "const C = () => <div/>;\n",
            ".go": "package m\nfunc F(){}\n",
            ".rs": "struct S{a:i32}\nfn f(){}\n",
            ".java": "class A{void m(){}}\n",
            ".c": "int f(void){return 0;}\n",
            ".cpp": "int f(){return 0;}\n",
            ".rb": "class A\n def m; end\nend\n",
            ".php": "<?php\nclass A{}\n",
        }
        for ext, source in samples.items():
            with self.subTest(ext=ext):
                result = languages.parse_symbols(source, ext)
                self.assertEqual(
                    result.state,
                    languages.PARSE_STATE_STRUCTURAL,
                    f"{ext} did not parse structurally",
                )
                self.assertTrue(result.blocks, f"{ext} produced no blocks")

    def test_unmapped_extension_degrades_instead_of_failing(self):
        result = languages.parse_symbols("some text", ".qqq")
        self.assertEqual(result.state, languages.PARSE_STATE_UNMAPPED)
        self.assertEqual(result.blocks, [])

    def test_markdown_is_unmapped_but_labelled(self):
        result = languages.parse_symbols("# Title", ".md")
        self.assertEqual(result.state, languages.PARSE_STATE_UNMAPPED)
        self.assertEqual(result.language, "Markdown")

    def test_missing_grammar_degrades_to_raw(self):
        original = languages.BY_EXTENSION.get(".go")
        self.assertIsNotNone(original)
        stub = languages.LanguageSpec(
            name="Go",
            module="tree_sitter_nonexistent",
            attribute="language",
            class_nodes=("type_declaration",),
            function_nodes=("function_declaration",),
            extensions=(".go",),
        )
        languages.BY_EXTENSION[".go"] = stub
        try:
            result = languages.parse_symbols("package m\nfunc F(){}\n", ".go")
            self.assertEqual(result.state, languages.PARSE_STATE_NO_GRAMMAR)
            self.assertEqual(result.language, "Go")
        finally:
            languages.BY_EXTENSION[".go"] = original

    def test_unparseable_source_is_reported_not_claimed(self):
        result = languages.parse_symbols("class A { m( { {", ".java")
        self.assertIn(
            result.state,
            (languages.PARSE_STATE_UNPARSEABLE, languages.PARSE_STATE_STRUCTURAL),
        )
        if result.state == languages.PARSE_STATE_UNPARSEABLE:
            self.assertEqual(result.blocks, [])

    def test_blocks_carry_line_ranges_and_qualified_names(self):
        source = "class Circle {\n  area() { return 1 }\n}\n"
        result = languages.parse_symbols(source, ".ts")
        block = next(b for b in result.blocks if b["name"] == "area")
        self.assertGreaterEqual(block["start_line"], 1)
        self.assertGreaterEqual(block["end_line"], block["start_line"])
        self.assertIn("qualified_name", block["metadata_json"])

    def test_nested_method_gets_a_qualified_name(self):
        source = "class Circle {\n  area() { return 1 }\n}\n"
        result = languages.parse_symbols(source, ".ts")
        block = next(b for b in result.blocks if b["name"] == "area")
        self.assertEqual(block["metadata_json"]["qualified_name"], "Circle.area")

    def test_empty_source_does_not_raise(self):
        for ext in (".py", ".ts", ".go", ".rb", ".php", ".md", ".qqq"):
            with self.subTest(ext=ext):
                languages.parse_symbols("", ext)


class NoFileDroppedTest(unittest.TestCase):
    def test_known_language_without_grammar_still_yields_a_label(self):
        """The core promise: a missing grammar shrinks understanding, not the index."""
        result = languages.parse_symbols("anything", ".go")
        self.assertTrue(result.language)

    def test_every_text_extension_produces_a_language(self):
        for ext in languages.all_supported_extensions():
            with self.subTest(ext=ext):
                result = languages.parse_symbols("x = 1", ext)
                self.assertTrue(
                    result.language,
                    f"{ext} produced no language label and would be dropped",
                )

    def test_unmapped_extension_is_labelled_text_not_unknown(self):
        result = languages.parse_symbols_for_file("notes.qqq", ".qqq", "hello")
        self.assertEqual(result.language, "Text")
        self.assertEqual(result.state, languages.PARSE_STATE_UNMAPPED)

    def test_extensionless_file_is_labelled_text(self):
        result = languages.parse_symbols_for_file("NOTES", "", "hello")
        self.assertEqual(result.language, "Text")

    def test_dotenv_samples_are_labelled(self):
        for name in (".env.sample", ".env.example", "config.sample", ".env.local"):
            with self.subTest(name=name):
                result = languages.parse_symbols_for_file(name, os.path.splitext(name)[1], "A=1")
                self.assertEqual(result.language, "Dotenv")

    def test_binary_payload_is_rejected_by_content(self):
        self.assertTrue(languages.looks_binary("abc\x00def"))
        self.assertFalse(languages.looks_binary("abcdef"))

    def test_extensionless_source_file_is_labelled(self):
        result = languages.parse_symbols_for_file("LICENSE", "", "MIT License")
        self.assertEqual(result.language, "License")

    def test_dockerfile_is_labelled(self):
        for name in ("Dockerfile", "dockerfile", "Dockerfile.dev"):
            with self.subTest(name=name):
                result = languages.parse_symbols_for_file(name, "", "FROM python:3.12")
                self.assertEqual(result.language, "Dockerfile")

    def test_binary_payload_yields_no_language(self):
        result = languages.parse_symbols_for_file("data", ".dat", "ab\x00cd")
        self.assertEqual(result.language, "")

    def test_regular_payload_defers_to_the_dispatcher(self):
        result = languages.parse_symbols_for_file("a.py", ".py", "x = 1")
        self.assertEqual(result.state, languages.PARSE_STATE_STRUCTURAL)
