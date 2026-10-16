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


class BuildGraphsTest(unittest.TestCase):
    """The structured form the SVG renderer consumes."""

    def test_exposes_every_view(self):
        result = diagrams.build_graphs(_manifest())
        self.assertEqual(
            set(result), {"languages", "directories", "entrypoints"}
        )

    def test_is_deterministic(self):
        self.assertEqual(
            diagrams.build_graphs(_manifest()),
            diagrams.build_graphs(_manifest()),
        )


class DirectoryModelTest(unittest.TestCase):
    def test_ids_are_path_based_and_stable(self):
        model = diagrams.directory_model(_manifest())
        ids = [node.id for node in model.nodes]
        self.assertEqual(ids[0], "root")
        # Path based, so identity survives the tree growing or reordering.
        self.assertIn("dir:app", ids)
        self.assertIn("dir:app/services", ids)
        self.assertIn("dir:docs", ids)

    def test_counts_are_carried_on_the_node(self):
        model = diagrams.directory_model(_manifest())
        by_id = {node.id: node for node in model.nodes}
        self.assertEqual(by_id["root"].files, 10)
        self.assertEqual(by_id["dir:app"].files, 5)
        self.assertEqual(by_id["dir:app/services"].files, 2)

    def test_every_edge_targets_a_declared_node(self):
        model = diagrams.directory_model(_manifest())
        declared = {node.id for node in model.nodes}
        for edge in model.edges:
            self.assertIn(edge.source, declared)
            self.assertIn(edge.target, declared)

    def test_truncation_uses_a_dashed_more_node(self):
        model = diagrams.directory_model(_manifest(), max_nodes=1)
        more = [node for node in model.nodes if node.kind == "more"]
        self.assertEqual(len(more), 1)
        self.assertEqual(more[0].label, "+2 more directories")
        dashed = [edge for edge in model.edges if edge.style == diagrams.DASHED]
        self.assertEqual([(e.source, e.target) for e in dashed], [("root", "more")])

    def test_ids_do_not_shift_when_a_sibling_is_inserted(self):
        before = diagrams.directory_model(_manifest())
        grown = _manifest(
            directories=[
                {"path": ".", "files": 1},
                {"path": "app", "files": 3},
                {"path": "app/services", "files": 2},
                {"path": "docs", "files": 4},
                {"path": "api", "files": 9},
            ]
        )
        after = diagrams.directory_model(grown)
        # ``api`` becomes the largest subtree and is emitted first, but the ids
        # of the pre-existing nodes must not change.
        self.assertIn("dir:app/services", [node.id for node in after.nodes])
        for node in before.nodes:
            self.assertIn(node.id, [n.id for n in after.nodes])
        self.assertEqual(
            [node.id for node in after.nodes][1], "dir:api"
        )


class EntrypointModelTest(unittest.TestCase):
    def test_lists_entrypoints_with_language_sublabels(self):
        model = diagrams.entrypoint_model(_manifest())
        by_id = {node.id: node for node in model.nodes}
        self.assertIn("ep:app/main.py", by_id)
        self.assertEqual(by_id["ep:app/main.py"].sublabel, "Python")

    def test_empty_manifest_uses_a_none_node(self):
        model = diagrams.entrypoint_model({})
        self.assertEqual([node.kind for node in model.nodes], ["hub", "none"])

    def test_truncation_uses_a_dashed_more_node(self):
        model = diagrams.entrypoint_model(_manifest(), max_nodes=1)
        self.assertEqual(
            [node.label for node in model.nodes if node.kind == "more"],
            ["+1 more entrypoints"],
        )


class LanguageModelTest(unittest.TestCase):
    def test_slices_are_labelled_and_counted(self):
        model = diagrams.language_model(_manifest())
        values = {slice_.label: slice_.value for slice_ in model.slices}
        self.assertEqual(values["Python"], 6)
        self.assertEqual(values["Markdown"], 4)

    def test_empty_manifest_has_a_placeholder_slice(self):
        model = diagrams.language_model({})
        self.assertEqual(
            [(slice_.id, slice_.value) for slice_ in model.slices],
            [("none", 1)],
        )

    def test_zero_count_languages_are_skipped(self):
        model = diagrams.language_model({"languages": {"Empty": {"files": 0}}})
        self.assertEqual([slice_.id for slice_ in model.slices], ["none"])

    def test_respects_the_slice_cap(self):
        languages = {f"Lang{i}": {"files": i + 1} for i in range(30)}
        model = diagrams.language_model({"languages": languages})
        self.assertEqual(len(model.slices), diagrams.MAX_LANGUAGE_SLICES)


if __name__ == "__main__":
    unittest.main()
