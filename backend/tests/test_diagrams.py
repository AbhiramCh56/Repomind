import unittest

from app.ai import diagrams


def _manifest(**overrides):
    data = {
        "repository_id": "d5d87f22-c430-4379-a237-72455ed735fd",
        "full_name": "acme/demo",
        "totals": {
            "files": 10,
            "structural_files": 6,
            "doc_files": 4,
            "symbols": 30,
        },
        "languages": {
            "Python": {"files": 6, "structural_files": 6, "raw_files": 0, "symbols": 20},
            "Markdown": {"files": 4, "structural_files": 0, "raw_files": 4, "symbols": 0},
        },
        "directories": [
            {"path": ".", "files": 1, "structural_files": 1, "symbols": 2},
            {"path": "app", "files": 3, "structural_files": 3, "symbols": 10},
            {"path": "app/services", "files": 2, "structural_files": 2, "symbols": 8},
            {"path": "docs", "files": 4, "structural_files": 0, "symbols": 0},
        ],
        "entrypoints": [
            {"path": "app/main.py", "language": "Python", "score": 10},
            {"path": "run_dev.ps1", "language": "PowerShell", "score": 3},
        ],
    }
    data.update(overrides)
    return data


class BuildDiagramsTest(unittest.TestCase):
    def test_exposes_every_view(self):
        result = diagrams.build_diagrams(_manifest())
        self.assertEqual(
            set(result), {"languages", "directories", "entrypoints"}
        )
        for source in result.values():
            self.assertTrue(source.strip())

    def test_is_deterministic(self):
        self.assertEqual(
            diagrams.build_diagrams(_manifest()),
            diagrams.build_diagrams(_manifest()),
        )

    def test_tolerates_none(self):
        result = diagrams.build_diagrams(None)
        self.assertEqual(set(result), {"languages", "directories", "entrypoints"})


class LanguagePieTest(unittest.TestCase):
    def test_lists_file_counts(self):
        source = diagrams.language_pie(_manifest())
        self.assertIn("pie showData", source)
        self.assertIn('"Python" : 6', source)
        self.assertIn('"Markdown" : 4', source)

    def test_empty_manifest_has_placeholder(self):
        source = diagrams.language_pie({})
        self.assertIn('"No indexed files" : 1', source)

    def test_zero_count_languages_are_skipped(self):
        source = diagrams.language_pie(
            {"languages": {"Empty": {"files": 0, "symbols": 0}}}
        )
        self.assertIn('"No indexed files" : 1', source)
        self.assertNotIn("Empty", source)

    def test_quotes_are_neutralised(self):
        source = diagrams.language_pie(
            {"languages": {'Weird "Lang"': {"files": 3}}}
        )
        self.assertIn('"Weird \'Lang\'" : 3', source)

    def test_respects_the_slice_cap(self):
        languages = {f"Lang{i}": {"files": i + 1} for i in range(30)}
        source = diagrams.language_pie({"languages": languages})
        self.assertEqual(source.count(" : "), diagrams.MAX_LANGUAGE_SLICES)


class DirectoryMapTest(unittest.TestCase):
    def test_root_carries_repository_and_total(self):
        source = diagrams.directory_map(_manifest())
        self.assertIn("flowchart TD", source)
        self.assertIn('root["acme/demo<br/>10 files"]', source)

    def test_nests_children_and_sums_files(self):
        source = diagrams.directory_map(_manifest())
        self.assertIn('"app<br/>5 files"', source)
        self.assertIn('"services<br/>2 files"', source)
        self.assertIn('"docs<br/>4 files"', source)
        # Largest subtree first, deterministically.
        self.assertLess(source.index('"app<br/>5 files"'), source.index('"docs<br/>4 files"'))

    def test_reports_truncation(self):
        source = diagrams.directory_map(_manifest(), max_nodes=1)
        self.assertIn('more["+2 more directories"]', source)

    def test_empty_manifest_still_renders_root(self):
        source = diagrams.directory_map({})
        self.assertIn('root["repository<br/>0 files"]', source)
        self.assertNotIn("more[", source)


class EntrypointMapTest(unittest.TestCase):
    def test_lists_entrypoints(self):
        source = diagrams.entrypoint_map(_manifest())
        self.assertIn("flowchart LR", source)
        self.assertIn('"app/main.py<br/>Python"', source)
        self.assertIn('"run_dev.ps1<br/>PowerShell"', source)

    def test_empty_manifest_explains_absence(self):
        source = diagrams.entrypoint_map({})
        self.assertIn('none["No conventional entrypoints detected"]', source)

    def test_reports_truncation(self):
        source = diagrams.entrypoint_map(_manifest(), max_nodes=1)
        self.assertIn('more["+1 more entrypoints"]', source)


if __name__ == "__main__":
    unittest.main()
