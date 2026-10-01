/**
 * Pure helpers for the Editor's unsaved-change tracking and undo/redo.
 *
 * Kept free of React / JSX so they can be unit-tested in the node vitest env.
 *
 *  - `editorSnapshot` captures only the *document* part of the canvas (node
 *    type/label/config/placement/position, edges, graph name, seed). Execution
 *    status, selection, measured sizes and handler callbacks are excluded, so a
 *    run painting node statuses never marks the graph dirty or adds history.
 *  - `snapshotSignature` is a stable string (sorted keys / ids) used for both
 *    the dirty check (vs. the last loaded/saved baseline) and to decide whether
 *    a canvas change is a new history step.
 *  - `changeKey` classifies a single-field edit so rapid edits of the same
 *    field (typing in a config input) coalesce into one undo step.
 *  - `History` is a bounded past/present/future stack.
 */

export type SnapshotNode = {
  id: string
  position: { x: number; y: number }
  data: Record<string, unknown> & { nodeType: string; label?: string; config?: Record<string, unknown> }
}

export type SnapshotEdge = {
  id: string
  source: string
  target: string
  sourceHandle?: string | null
  targetHandle?: string | null
  data?: unknown
}

export type EditorSnapshot = {
  nodes: SnapshotNode[]
  edges: SnapshotEdge[]
  graphName: string
  seed: number
}

/** Node `data` keys that are runtime / view state, never part of the document. */
const VOLATILE_DATA_KEYS = new Set(['status', 'lastError', 'configIssues'])

function stripData(data: Record<string, unknown>): SnapshotNode['data'] {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(data)) {
    if (typeof v === 'function') continue
    if (VOLATILE_DATA_KEYS.has(k)) continue
    out[k] = v
  }
  return out as SnapshotNode['data']
}

/**
 * Capture the document part of the canvas. Accepts React Flow nodes/edges
 * (extra keys like `selected`, `dragging`, `width` are dropped).
 */
export function editorSnapshot(
  nodes: Array<{ id: string; position: { x: number; y: number }; data: Record<string, unknown> }>,
  edges: Array<{
    id: string
    source: string
    target: string
    sourceHandle?: string | null
    targetHandle?: string | null
    data?: unknown
  }>,
  graphName: string,
  seed: number,
): EditorSnapshot {
  return {
    nodes: nodes.map((n) => ({
      id: n.id,
      position: { x: n.position.x, y: n.position.y },
      data: stripData(n.data as Record<string, unknown>),
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle ?? null,
      targetHandle: e.targetHandle ?? null,
      data: e.data,
    })),
    graphName,
    seed,
  }
}

/** JSON.stringify with sorted object keys; `undefined` members dropped. */
export function stableStringify(value: unknown): string {
  if (value === undefined) return 'null'
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'null'
  if (Array.isArray(value)) return `[${value.map((v) => stableStringify(v)).join(',')}]`
  const obj = value as Record<string, unknown>
  const keys = Object.keys(obj)
    .filter((k) => obj[k] !== undefined && typeof obj[k] !== 'function')
    .sort()
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`).join(',')}}`
}

function nodeDocument(n: SnapshotNode, withPositions: boolean): Record<string, unknown> {
  const d = n.data
  return {
    id: n.id,
    nodeType: d.nodeType,
    label: d.label ?? '',
    config: d.config ?? {},
    placement: d.placement ?? null,
    ...(withPositions ? { x: Math.round(n.position.x), y: Math.round(n.position.y) } : {}),
  }
}

function edgeDocument(e: SnapshotEdge): Record<string, unknown> {
  const cond = e.data && typeof e.data === 'object' ? (e.data as { condition?: unknown }).condition ?? null : null
  return {
    source: e.source,
    sourceHandle: e.sourceHandle ?? null,
    target: e.target,
    targetHandle: e.targetHandle ?? null,
    condition: cond,
  }
}

/**
 * Stable signature of the saved document. Node and edge order don't matter.
 * Positions (rounded to px) are included by default — they are persisted in
 * the graph's `ui.positions`.
 */
export function snapshotSignature(s: EditorSnapshot, opts: { positions?: boolean } = {}): string {
  const withPositions = opts.positions !== false
  const nodes = s.nodes.map((n) => nodeDocument(n, withPositions)).sort((a, b) => String(a.id).localeCompare(String(b.id)))
  const edges = s.edges
    .map(edgeDocument)
    .map((e) => stableStringify(e))
    .sort()
  return stableStringify({ name: s.graphName, seed: s.seed, nodes, edges })
}

/**
 * Classify the edit between two snapshots so consecutive edits of the same
 * field coalesce into one undo step. Returns null for structural changes
 * (add/delete/connect/move) which must always be their own step.
 */
export function changeKey(prev: EditorSnapshot, next: EditorSnapshot): string | null {
  const sameNodes =
    prev.nodes.length === next.nodes.length && prev.nodes.every((n, i) => next.nodes[i]?.id === n.id)
  const sameEdges = stableStringify(prev.edges.map(edgeDocument)) === stableStringify(next.edges.map(edgeDocument))
  if (!sameNodes || !sameEdges) return null
  const keys: string[] = []
  if (prev.graphName !== next.graphName) keys.push('graph:name')
  if (prev.seed !== next.seed) keys.push('graph:seed')
  for (let i = 0; i < prev.nodes.length; i++) {
    const a = prev.nodes[i]
    const b = next.nodes[i]
    if (Math.round(a.position.x) !== Math.round(b.position.x) || Math.round(a.position.y) !== Math.round(b.position.y)) {
      return null
    }
    if ((a.data.label ?? '') !== (b.data.label ?? '')) keys.push(`label:${a.id}`)
    if (stableStringify(a.data.placement ?? null) !== stableStringify(b.data.placement ?? null)) {
      keys.push(`placement:${a.id}`)
    }
    const ca = a.data.config ?? {}
    const cb = b.data.config ?? {}
    for (const k of new Set([...Object.keys(ca), ...Object.keys(cb)])) {
      if (stableStringify(ca[k]) !== stableStringify(cb[k])) keys.push(`config:${a.id}:${k}`)
    }
  }
  return keys.length === 1 ? keys[0] : null
}

export type History<T> = { past: T[]; present: T; future: T[] }

export const HISTORY_LIMIT = 50

export function createHistory<T>(present: T): History<T> {
  return { past: [], present, future: [] }
}

/**
 * Record `next` as the new present. When `coalesce` is true the current
 * present is replaced in place (same undo step); otherwise it moves to `past`.
 * Any new edit clears the redo stack. `past` is bounded by `limit`.
 */
export function pushHistory<T>(h: History<T>, next: T, opts: { coalesce?: boolean; limit?: number } = {}): History<T> {
  const limit = opts.limit ?? HISTORY_LIMIT
  if (opts.coalesce && h.past.length > 0) return { past: h.past, present: next, future: [] }
  const past = [...h.past, h.present]
  while (past.length > limit) past.shift()
  return { past, present: next, future: [] }
}

export function undoHistory<T>(h: History<T>): History<T> {
  if (h.past.length === 0) return h
  const prev = h.past[h.past.length - 1]
  return { past: h.past.slice(0, -1), present: prev, future: [h.present, ...h.future] }
}

export function redoHistory<T>(h: History<T>): History<T> {
  if (h.future.length === 0) return h
  const [next, ...rest] = h.future
  return { past: [...h.past, h.present], present: next, future: rest }
}

/** Keyboard shortcut → history action, or null. Never fires while typing in a field. */
export function historyShortcut(e: {
  key: string
  ctrlKey: boolean
  metaKey: boolean
  shiftKey: boolean
  altKey?: boolean
  target?: unknown
}): 'undo' | 'redo' | null {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return null
  if (isTypingTarget(e.target)) return null
  const k = e.key.toLowerCase()
  if (k === 'z') return e.shiftKey ? 'redo' : 'undo'
  if (k === 'y' && !e.shiftKey) return 'redo'
  return null
}

export function isTypingTarget(target: unknown): boolean {
  if (!target || typeof target !== 'object') return false
  const el = target as { tagName?: unknown; isContentEditable?: unknown }
  const tag = typeof el.tagName === 'string' ? el.tagName.toUpperCase() : ''
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  return el.isContentEditable === true
}
