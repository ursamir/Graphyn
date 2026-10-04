import { humanizeTemplateName, shortRunId } from './format'

/**
 * Human title for a run row / run detail. Backend (UX API draft) adds
 * `display_name` at top level and under `meta`; older APIs only have
 * `graph_name` (often the generic "pipeline") and the run id.
 */
const GENERIC_GRAPH_NAMES = new Set(['', 'pipeline', 'graph', 'untitled', 'default'])

function rec(v: unknown): Record<string, unknown> | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null
}

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

export function runDisplayName(run: unknown): string {
  const r = rec(run)
  if (!r) return 'Run'
  const meta = rec(r.meta)
  const dn = str(r.display_name) || str(meta?.display_name)
  if (dn) return dn
  const graph = str(r.graph_name) || str(meta?.graph_name) || str(r.pipeline) || str(r.name)
  const id = str(r.run_id) || str(r.id) || str(meta?.run_id)
  if (graph && !GENERIC_GRAPH_NAMES.has(graph.toLowerCase())) return humanizeTemplateName(graph)
  return id ? `Run ${shortRunId(id)}` : 'Run'
}

/**
 * Full run id for a run opened by a (possibly shortened) id. The API resolves
 * an 8-char prefix on `GET /runs/{id}` but most other routes (POST /models,
 * trace, …) need the full id. Returns the detail's `run_id` (top level or
 * `meta`) when it extends `requested`; otherwise `requested` unchanged.
 */
export function resolveFullRunId(requested: string, detail: unknown): string {
  const d = rec(detail)
  if (!d || !requested) return requested
  const full = str(d.run_id) || str(rec(d.meta)?.run_id) || str(d.id)
  if (!full || full === requested) return requested
  return full.toLowerCase().startsWith(requested.toLowerCase()) ? full : requested
}
