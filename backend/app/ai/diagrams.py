"""
Deterministic architecture diagrams derived from a repository manifest.

Everything here is a *view* over the manifest payload already produced by
:mod:`app.ai.structure`. The manifest is the single deterministic
representation of a repository's architecture, so the diagrams inherit its
properties: no LLM, no extra parsing, no I/O, and byte-identical output for a
given manifest.

Two representations are produced from the same in-memory models:

* Mermaid source strings, kept for API compatibility and exported documents
  (:func:`build_diagrams`).
* Structured graphs (nodes + edges), consumed by the frontend's SVG renderer so
  it can diff renders and animate files joining the diagram as an import
  progresses (:func:`build_graphs`).

The structured form is the one that carries *stable* node ids (path based, e.g.
``dir:app/services``). The Mermaid serializer keeps the legacy positional ids
(``d1``, ``e0``, ...) so existing output and tests do not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

#: Caps keep a large monorepo from producing an unreadable or unusably slow
#: diagram. Truncation is always reported in the diagram itself.
MAX_DIRECTORY_NODES = 40
MAX_ENTRYPOINT_NODES = 20
MAX_LANGUAGE_SLICES = 12

SOLID = "solid"
DASHED = "dashed"


# ------------------------------------------------------------------- models
@dataclass
class GraphNode:
    """One rendered box. ``id`` is stable across renders (never positional)."""

    id: str
    label: str
    kind: str
    parent: Optional[str] = None
    files: int = 0
    sublabel: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "parent": self.parent,
            "files": self.files,
            "sublabel": self.sublabel,
        }


@dataclass
class GraphEdge:
    source: str
    target: str
    style: str = SOLID

    @property
    def id(self) -> str:
        return f"{self.source}->{self.target}"

    def to_payload(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "style": self.style,
        }


@dataclass
class TreeGraph:
    """A ranked tree (directory map, entrypoint map)."""

    direction: str
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "type": "tree",
            "direction": self.direction,
            "nodes": [node.to_payload() for node in self.nodes],
            "edges": [edge.to_payload() for edge in self.edges],
        }


@dataclass
class PieSlice:
    id: str
    label: str
    value: int

    def to_payload(self) -> Dict[str, Any]:
        return {"id": self.id, "label": self.label, "value": self.value}


@dataclass
class PieGraph:
    title: str
    slices: List[PieSlice] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "type": "pie",
            "title": self.title,
            "slices": [slice_.to_payload() for slice_ in self.slices],
        }


# ------------------------------------------------------------------ builders
def build_diagram_models(manifest: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Return the structured model for every architecture view."""
    data: Mapping[str, Any] = manifest or {}
    return {
        "languages": language_model(data),
        "directories": directory_model(data),
        "entrypoints": entrypoint_model(data),
    }


def build_graphs(manifest: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Return JSON-ready structured graphs for every architecture view."""
    return {name: model.to_payload() for name, model in build_diagram_models(manifest).items()}


def build_diagrams(manifest: Mapping[str, Any] | None) -> Dict[str, str]:
    """Return the Mermaid source for every architecture view of a manifest."""
    data: Mapping[str, Any] = manifest or {}
    return {
        "languages": language_pie(data),
        "directories": directory_map(data),
        "entrypoints": entrypoint_map(data),
    }


def language_model(
    manifest: Mapping[str, Any], max_slices: int = MAX_LANGUAGE_SLICES
) -> PieGraph:
    """File counts per language, largest first, capped at ``max_slices``."""
    languages = manifest.get("languages") or {}
    graph = PieGraph(title="Languages by files")

    for language, stats in languages.items():
        files = int((stats or {}).get("files", 0) or 0)
        if files > 0:
            label = _quote(str(language))
            graph.slices.append(PieSlice(id=label, label=label, value=files))
        if len(graph.slices) >= max_slices:
            break

    if not graph.slices:
        graph.slices.append(
            PieSlice(id="none", label="No indexed files", value=1)
        )
    return graph


def language_pie(manifest: Mapping[str, Any]) -> str:
    """File counts per language as a Mermaid pie chart."""
    model = language_model(manifest)
    lines = ["pie showData", f"    title {model.title}"]
    for slice_ in model.slices:
        lines.append(f'    "{_quote(slice_.label)}" : {slice_.value}')
    return "\n".join(lines)


def directory_model(
    manifest: Mapping[str, Any], max_nodes: int = MAX_DIRECTORY_NODES
) -> TreeGraph:
    """
    Directory tree model, sized by file count.

    Nodes are capped at ``max_nodes``; the remainder is collapsed into a single
    "+N more directories" node so truncation is never silent.
    """
    tree = _build_tree(manifest.get("directories") or [])
    total_files = int((manifest.get("totals") or {}).get("files", 0) or 0)

    graph = TreeGraph(direction="TD")
    graph.nodes.append(
        GraphNode(
            id="root",
            label=_quote(manifest.get("full_name") or "repository"),
            kind="root",
            parent=None,
            files=total_files,
        )
    )

    entries, skipped = _walk_directories(tree, max_nodes)
    for entry in entries:
        graph.nodes.append(
            GraphNode(
                id=entry["id"],
                label=entry["label"],
                kind="dir",
                parent=entry["parent"],
                files=entry["files"],
            )
        )
        graph.edges.append(GraphEdge(source=entry["parent"], target=entry["id"]))

    if skipped:
        graph.nodes.append(
            GraphNode(
                id="more",
                label=f"+{skipped} more directories",
                kind="more",
                parent="root",
            )
        )
        graph.edges.append(GraphEdge(source="root", target="more", style=DASHED))

    return graph


def directory_map(
    manifest: Mapping[str, Any], max_nodes: int = MAX_DIRECTORY_NODES
) -> str:
    """
    Directory tree as a Mermaid flowchart, sized by file count.

    Serializes :func:`directory_model`, but keeps the legacy positional ids
    (``d1``, ``d2``, ...) so existing Mermaid output is unchanged.
    """
    tree = _build_tree(manifest.get("directories") or [])
    root_label = _quote(manifest.get("full_name") or "repository")
    total_files = int((manifest.get("totals") or {}).get("files", 0) or 0)

    lines = ["flowchart TD", f'    root["{root_label}<br/>{total_files} files"]']
    entries, skipped = _walk_directories(tree, max_nodes)

    legacy = {"root": "root"}
    for index, entry in enumerate(entries, start=1):
        legacy_id = f"d{index}"
        legacy[entry["id"]] = legacy_id
        lines.append(f'    {legacy_id}["{entry["label"]}<br/>{entry["files"]} files"]')
        lines.append(f'    {legacy[entry["parent"]]} --> {legacy_id}')

    if skipped:
        lines.append(f'    more["+{skipped} more directories"]')
        lines.append("    root -.-> more")

    return "\n".join(lines)


def entrypoint_model(
    manifest: Mapping[str, Any], max_nodes: int = MAX_ENTRYPOINT_NODES
) -> TreeGraph:
    """Likely entrypoints as a flat tree branching from a single hub node."""
    entrypoints = manifest.get("entrypoints") or []

    graph = TreeGraph(direction="LR")
    graph.nodes.append(
        GraphNode(id="ep", label="Likely entrypoints", kind="hub", parent=None)
    )

    if not entrypoints:
        graph.nodes.append(
            GraphNode(
                id="none",
                label="No conventional entrypoints detected",
                kind="none",
                parent="ep",
            )
        )
        graph.edges.append(GraphEdge(source="ep", target="none"))
        return graph

    for entry in entrypoints[:max_nodes]:
        path = _quote((entry or {}).get("path") or "unknown")
        language = _quote((entry or {}).get("language") or "Unknown")
        node_id = f"ep:{path}"
        graph.nodes.append(
            GraphNode(
                id=node_id,
                label=path,
                kind="entrypoint",
                parent="ep",
                sublabel=language,
            )
        )
        graph.edges.append(GraphEdge(source="ep", target=node_id))

    hidden = len(entrypoints) - max_nodes
    if hidden > 0:
        graph.nodes.append(
            GraphNode(
                id="more",
                label=f"+{hidden} more entrypoints",
                kind="more",
                parent="ep",
            )
        )
        graph.edges.append(GraphEdge(source="ep", target="more", style=DASHED))

    return graph


def entrypoint_map(
    manifest: Mapping[str, Any], max_nodes: int = MAX_ENTRYPOINT_NODES
) -> str:
    """Likely entrypoints as a Mermaid flowchart branching from a single node."""
    entrypoints = manifest.get("entrypoints") or []
    lines = ["flowchart LR", '    ep["Likely entrypoints"]']

    if not entrypoints:
        lines.append('    none["No conventional entrypoints detected"]')
        lines.append("    ep --> none")
        return "\n".join(lines)

    for index, entry in enumerate(entrypoints[:max_nodes]):
        path = _quote((entry or {}).get("path") or "unknown")
        language = _quote((entry or {}).get("language") or "Unknown")
        lines.append(f'    e{index}["{path}<br/>{language}"]')
        lines.append(f"    ep --> e{index}")

    hidden = len(entrypoints) - max_nodes
    if hidden > 0:
        lines.append(f'    more["+{hidden} more entrypoints"]')
        lines.append("    ep -.-> more")

    return "\n".join(lines)


# ----------------------------------------------------------------- internals
def _build_tree(directories: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Nest directory rollups into a tree keyed by path segment."""
    root: Dict[str, Any] = {"files": 0, "children": {}}
    for entry in directories:
        if not entry:
            continue
        path = str(entry.get("path") or ".").strip("/")
        files = int(entry.get("files", 0) or 0)
        if path in ("", "."):
            root["files"] += files
            continue
        node = root
        for part in [p for p in path.split("/") if p]:
            node = node["children"].setdefault(part, {"files": 0, "children": {}})
        node["files"] += files
    return root


def _recursive_files(node: Mapping[str, Any]) -> int:
    return int(node.get("files", 0) or 0) + sum(
        _recursive_files(child) for child in node.get("children", {}).values()
    )


def _count_dirs(node: Mapping[str, Any]) -> int:
    return sum(
        1 + _count_dirs(child) for child in node.get("children", {}).values()
    )


def _walk_directories(
    tree: Mapping[str, Any], max_nodes: int
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Depth-first walk, largest subtree first, shared by both representations.

    Returns the emitted entries (in render order, each with a stable path id) and
    the number of pruned directories. Parents always precede their children, so
    callers can resolve a parent's identity on the way down.
    """
    entries: List[Dict[str, Any]] = []
    remaining = max(0, max_nodes)
    skipped = 0

    def visit(node: Mapping[str, Any], parent_id: str, path: str) -> None:
        nonlocal remaining, skipped
        children = sorted(
            node.get("children", {}).items(),
            key=lambda item: (-_recursive_files(item[1]), item[0]),
        )
        for name, child in children:
            if remaining <= 0:
                skipped += 1 + _count_dirs(child)
                continue
            remaining -= 1
            child_path = f"{path}/{name}" if path else name
            node_id = f"dir:{child_path}"
            entries.append(
                {
                    "id": node_id,
                    "label": _quote(name),
                    "files": _recursive_files(child),
                    "parent": parent_id,
                }
            )
            visit(child, node_id, child_path)

    visit(tree, "root", "")
    return entries, skipped


def _quote(label: str) -> str:
    """Collapse whitespace and neutralise characters Mermaid labels choke on."""
    text = " ".join(str(label).split())
    return text.replace('"', "'") or "unknown"
