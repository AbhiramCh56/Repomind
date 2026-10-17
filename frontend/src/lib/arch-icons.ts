/**
 * Small kind glyphs drawn on the architecture nodes.
 *
 * The shapes are the raw geometry of lucide-react's "box", "network", "folder",
 * "file-code-corner", "ellipsis" and "dot" icons (lucide-react is ISC licensed).
 * They are inlined as markup, rather than rendered as React components, because
 * the diagram is built imperatively through d3 — the renderer only has the DOM,
 * not a React tree, to append into.
 */
export const ARCH_ICON_MARKUP: Record<string, string> = {
  // Repository root: a package/module box.
  root: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
  // A directory that branches heavily into others.
  hub: '<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>',
  dir: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  entrypoint:
    '<path d="M4 12.15V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.706.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2h-3.35"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="m5 16-3 3 3 3"/><path d="m9 22 3-3-3-3"/>',
  // The "+N more" summary node.
  more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  none: '<circle cx="12" cy="12" r="1"/>',
}

/** Used when a node has no recognisable kind. */
export const ARCH_ICON_FALLBACK = ARCH_ICON_MARKUP.dir
