/**
 * Editor drift — does the graph on the canvas still match the exact graph a
 * run executed (`runs/<id>/graph.json`)? Compared on a canonical, semantic
 * form: node ids / types / config / placement and edges. Layout, labels,
 * description, timestamps and config keys whose value only fills in a catalog
 * default (the Editor adds schema defaults on load) are ignored, so opening a
 * run's graph and changing nothing never reports drift. Pure — unit-tested.
 */

type Rec = Record<string, unknown>

export type DriftGraph = {
  nodes?: Array<{ id?: unknown; node_type?: unknown; config?: unknown; placement?: unknown }>
  edges?: Array<{ src_id?: unknown; src_port?: unknown; dst_id?: unknown; dst_port?: unknown; condition?: unknown }>
  metadata?: { seed?: unknown } | null
}

/** Stable JSON: object keys sorted, undefined dropped. */
export function canonicalJson(value: unknown): string {
  const norm = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(norm)
    if (v && typeof v === 'object') {
      const out: Rec = {}
      for (const k of Object.keys(v as Rec).sort()) {
        const x = (v as Rec)[k]
        if (x === undefined) continue
        out[k] = norm(x)
      }
      return out
    }
    return v
  }
  return JSON.stringify(norm(value))
}

function emptyish(v: unknown): boolean {
  return (
    v == null ||
    v === '' ||
    (Array.isArray(v) && v.length === 0) ||
    (typeof v === 'object' && !Array.isArray(v) && Object.keys(v as Rec).length === 0)
  )
}

export type DriftChange = {
  kind: 'node-added' | 'node-removed' | 'type-changed' | 'config-changed' | 'edge-added' | 'edge-removed' | 'seed-changed' | 'placement-changed'
  nodeId?: string
  key?: string
  /** Value in the run's graph. */
  before?: string
  /** Value on the canvas now. */
  after?: string
}

const WRITE_PATH_KEY = /^(output_path|output_dir|out_dir|save_path|artifacts_dir|checkpoint_dir|checkpoint_path|log_dir|export_dir)$/i

function shortVal(v: unknown): string {
  if (v === undefined) return '(unset)'
  const s = typeof v === 'string' ? v : canonicalJson(v)
  return s.length > 80 ? `${s.slice(0, 77)}…` : s
}

function edgeKey(e: NonNullable<DriftGraph['edges']>[number]): string {
  return `${String(e.src_id)}:${String(e.src_port ?? 'output')}→${String(e.dst_id)}:${String(e.dst_port ?? 'input')}${
    e.condition ? `?${String(e.condition)}` : ''
  }`
}

/**
 * Semantic diff of `run` (recorded) vs `current` (canvas).
 * `defaultsFor(nodeType)` returns the catalog defaults the Editor fills in; a
 * key missing on one side whose other-side value equals that default (or is
 * empty) is not a change.
 */
export function diffGraphs(
  run: DriftGraph | null | undefined,
  current: DriftGraph | null | undefined,
  opts: {
    defaultsFor?: (nodeType: string) => Rec | undefined
    compareSeed?: boolean
    /**
     * The run's id: write locations the backend scoped under `runs/<id>/`
     * (output_path / output_dir …) are run bookkeeping, not a pipeline change.
     */
    runId?: string
  } = {},
): DriftChange[] {
  const changes: DriftChange[] = []
  const a = new Map((run?.nodes || []).map((n) => [String(n.id), n]))
  const b = new Map((current?.nodes || []).map((n) => [String(n.id), n]))
  for (const [id, n] of a) {
    if (!b.has(id)) changes.push({ kind: 'node-removed', nodeId: id, before: String(n.node_type ?? '') })
  }
  for (const [id, n] of b) {
    const prev = a.get(id)
    if (!prev) {
      changes.push({ kind: 'node-added', nodeId: id, after: String(n.node_type ?? '') })
      continue
    }
    if (String(prev.node_type) !== String(n.node_type)) {
      changes.push({ kind: 'type-changed', nodeId: id, before: String(prev.node_type), after: String(n.node_type) })
      continue
    }
    const defaults = opts.defaultsFor?.(String(n.node_type)) || {}
    const ca = (prev.config && typeof prev.config === 'object' ? prev.config : {}) as Rec
    const cb = (n.config && typeof n.config === 'object' ? n.config : {}) as Rec
    const keys = new Set([...Object.keys(ca), ...Object.keys(cb)])
    for (const k of [...keys].sort()) {
      const inA = k in ca
      const inB = k in cb
      const va = ca[k]
      const vb = cb[k]
      if (
        opts.runId &&
        WRITE_PATH_KEY.test(k) &&
        typeof va === 'string' &&
        va.includes(`runs/${opts.runId}`)
      ) {
        continue
      }
      if (inA && inB) {
        if (canonicalJson(va) !== canonicalJson(vb)) {
          changes.push({ kind: 'config-changed', nodeId: id, key: k, before: shortVal(va), after: shortVal(vb) })
        }
        continue
      }
      const present = inA ? va : vb
      if (emptyish(present)) continue
      if (k in defaults && canonicalJson(defaults[k]) === canonicalJson(present)) continue
      changes.push({
        kind: 'config-changed',
        nodeId: id,
        key: k,
        before: inA ? shortVal(va) : '(unset)',
        after: inB ? shortVal(vb) : '(unset)',
      })
    }
    const pa = emptyish(prev.placement) ? null : prev.placement
    const pb = emptyish(n.placement) ? null : n.placement
    if (canonicalJson(pa) !== canonicalJson(pb)) {
      changes.push({ kind: 'placement-changed', nodeId: id, before: shortVal(pa), after: shortVal(pb) })
    }
  }
  const ea = new Set((run?.edges || []).map(edgeKey))
  const eb = new Set((current?.edges || []).map(edgeKey))
  for (const k of ea) if (!eb.has(k)) changes.push({ kind: 'edge-removed', key: k })
  for (const k of eb) if (!ea.has(k)) changes.push({ kind: 'edge-added', key: k })
  if (opts.compareSeed) {
    const sa = run?.metadata?.seed
    const sb = current?.metadata?.seed
    if (typeof sa === 'number' && typeof sb === 'number' && sa !== sb) {
      changes.push({ kind: 'seed-changed', before: String(sa), after: String(sb) })
    }
  }
  return changes
}

/** One line per change for the Compare list. */
export function describeDriftChange(c: DriftChange, labelFor?: (id: string) => string | undefined): string {
  const who = c.nodeId ? labelFor?.(c.nodeId) || c.nodeId : ''
  switch (c.kind) {
    case 'node-added':
      return `Added step ${who}`
    case 'node-removed':
      return `Removed step ${who}`
    case 'type-changed':
      return `${who}: type ${c.before} → ${c.after}`
    case 'config-changed':
      return `${who} · ${c.key}: ${c.before} → ${c.after}`
    case 'placement-changed':
      return `${who}: placement ${c.before} → ${c.after}`
    case 'edge-added':
      return `Added connection ${c.key}`
    case 'edge-removed':
      return `Removed connection ${c.key}`
    case 'seed-changed':
      return `Seed ${c.before} → ${c.after}`
    default:
      return 'Changed'
  }
}

/**
 * Backend `pipeline_drift` (run detail) → `{changed, currentHash, runHash}` or
 * null when the API did not send it. Accepts a boolean or an object with
 * `changed|drift|drifted` + hashes.
 */
export function parsePipelineDrift(
  raw: unknown,
): { changed: boolean; currentHash: string; runHash: string; pipeline: string; layoutOnly: boolean; missing: boolean } | null {
  if (typeof raw === 'boolean') return { changed: raw, currentHash: '', runHash: '', pipeline: '', layoutOnly: false, missing: false }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const o = raw as Rec
  const flag = o.drifted ?? o.changed ?? o.drift ?? o.differs
  const currentHash = o.current_hash != null ? String(o.current_hash) : o.current_graph_hash != null ? String(o.current_graph_hash) : ''
  const runHash = String(o.run_graph_hash ?? o.run_hash ?? o.graph_hash ?? '')
  const layoutOnly = o.layout_only === true
  // `drifted: null` = the saved pipeline no longer exists.
  const missing = 'drifted' in o && o.drifted === null
  const changed =
    !layoutOnly &&
    (typeof flag === 'boolean' ? flag : Boolean(currentHash && runHash && currentHash !== runHash))
  return { changed, currentHash, runHash, pipeline: String(o.pipeline ?? o.pipeline_name ?? o.name ?? ''), layoutOnly, missing }
}

/**
 * Undo run scoping in a recorded graph: the run's graph.json stores write
 * paths as executed (`…/<slug>/runs/<run_id>/<node_id>/<tail>`); the logical
 * graph had `…/<slug>/<tail>`. Removes `runs/<run_id>/` and, when a tail
 * follows, the per-node folder. Returns a new graph (input untouched).
 */
export function unscopeRunPaths<G extends { nodes?: Array<{ id?: unknown; config?: unknown }> }>(graph: G, runId: string): G {
  const rid = runId.trim()
  if (!rid || !Array.isArray(graph.nodes)) return graph
  const unscope = (v: string, nodeId: string): string => {
    const marker = `runs/${rid}`
    const at = v.indexOf(marker)
    if (at < 0) return v
    const head = v.slice(0, at).replace(/\/+$/, '')
    let tail = v.slice(at + marker.length).replace(/^\/+/, '')
    const segs = tail ? tail.split('/') : []
    if (segs.length > 1 && segs[0] === nodeId) segs.shift()
    tail = segs.join('/')
    return [head, tail].filter(Boolean).join('/')
  }
  const walk = (val: unknown, nodeId: string): unknown => {
    if (typeof val === 'string') return unscope(val, nodeId)
    if (Array.isArray(val)) return val.map((x) => walk(x, nodeId))
    if (val && typeof val === 'object') {
      const out: Rec = {}
      for (const [k, x] of Object.entries(val as Rec)) out[k] = walk(x, nodeId)
      return out
    }
    return val
  }
  return {
    ...graph,
    nodes: graph.nodes.map((n) => {
      const id = String(n.id ?? '')
      return n.config && typeof n.config === 'object' ? { ...n, config: walk(n.config, id) } : n
    }),
  }
}
