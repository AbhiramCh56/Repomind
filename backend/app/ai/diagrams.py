"""
Deterministic architecture diagrams derived from a repository manifest.

Everything here is a *view* over the manifest payload already produced by
:mod:`app.ai.structure`. The manifest is the single deterministic
representation of a repository's architecture, so the diagrams inherit its
properties: no LLM, no extra parsing, no I/O, and byte-identical output for a
given manifest.

Each function returns a Mermaid source string. Rendering happens in the
frontend; generation stays here so the logic is unit-testable and can later
grow to include import-based dependency edges without touching the API shape.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

#: Caps keep a large monorepo from producing an unreadable or unusably slow
#: diagram. Truncation is always reported in the diagram itself.
MAX_DIRECTORY_NODES = 40
MAX_ENTRYPOINT_NODES = 20
MAX_LANGUAGE_SLICES = 12


def build_diagrams(manifest: Mapping[str, Any] | None) -> Dict[str, str]:
    """Return the Mermaid source for every architecture view of a manifest."""
    data: Mapping[str, Any] = manifest or {}
    return {
        "languages": language_pie(data),
        "directories": directory_map(data),
        "entrypoints": entrypoint_map(data),
    }


def language_pie(manifest: Mapping[str, Any]) -> str:
    """File counts per language as a Mermaid pie chart."""
    languages = manifest.get("languages") or {}
    lines = ["pie showData", "    title Languages by files"]

    slices: List[Tuple[str, int]] = []
    for language, stats in languages.items():
        files = int((stats or {}).get("files", 0) or 0)
        if files > 0:
            slices.append((str(language), files))
        if len(slices) >= MAX_LANGUAGE_SLICES:
            break

    if not slices:
        lines.append('    "No indexed files" : 1')
        return "\n".join(lines)

    for language, files in slices:
        lines.append(f'    "{_quote(language)}" : {files}')
    return "\n".join(lines)


def directory_map(
    manifest: Mapping[str, Any], max_nodes: int = MAX_DIRECTORY_NODES
) -> str:
    """
    Directory tree as a Mermaid flowchart, sized by file count.

    Nodes are capped at ``max_nodes``; the remainder is collapsed into a single
    "+N more directories" node so truncation is never silent.
    """
    directories = manifest.get("directories") or []
    tree = _build_tree(directories)

    root_label = _quote(manifest.get("full_name") or "repository")
    total_files = int((manifest.get("totals") or {}).get("files", 0) or 0)

    lines = ["flowchart TD", f'    root["{root_label}<br/>{total_files} files"]']
    state = _RenderState(lines=lines, remaining=max(0, max_nodes))
    _emit_children(tree, "root", state)

    if state.skipped:
        lines.append(f'    more["+{state.skipped} more directories"]')
        lines.append("    root -.-> more")

    return "\n".join(lines)


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
class _RenderState:
    """Mutable budget + output buffer threaded through the tree walk."""

    def __init__(self, lines: List[str], remaining: int) -> None:
        self.lines = lines
        self.remaining = remaining
        self.skipped = 0
        self.next_id = 0


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


def _emit_children(node: Mapping[str, Any], parent_id: str, state: _RenderState) -> None:
    """Depth-first emit of child directories, largest subtree first."""
    children = sorted(
        node.get("children", {}).items(),
        key=lambda item: (-_recursive_files(item[1]), item[0]),
    )
    for name, child in children:
        if state.remaining <= 0:
            state.skipped += 1 + _count_dirs(child)
            continue
        state.remaining -= 1
        state.next_id += 1
        node_id = f"d{state.next_id}"
        label = f"{_quote(name)}<br/>{_recursive_files(child)} files"
        state.lines.append(f'    {node_id}["{label}"]')
        state.lines.append(f"    {parent_id} --> {node_id}")
        _emit_children(child, node_id, state)


def _quote(label: str) -> str:
    """Collapse whitespace and neutralise characters Mermaid labels choke on."""
    text = " ".join(str(label).split())
    return text.replace('"', "'") or "unknown"
