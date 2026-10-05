/**
 * `?step=<node_id>` on a Runs URL (`/workspaces/W/runs/<id>/lineage?step=trainer_b`):
 * opens the run's Overview focused on that step — its path group expands and its
 * inline step details open. Used by Models → "How it was made". Pure (tested).
 */

/** Step node id from a search string (`?step=…`, or `?node=…` alias); null when absent/blank. */
export function parseStepParam(search: string | null | undefined): string | null {
  if (!search) return null
  const qs = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
  const v = (qs.get('step') ?? qs.get('node') ?? '').trim()
  return v || null
}

/** The same search string without `step` / `node` ('' when nothing is left, else "?…"). */
export function searchWithoutStep(search: string | null | undefined): string {
  if (!search) return ''
  const qs = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
  qs.delete('step')
  qs.delete('node')
  const s = qs.toString()
  return s ? `?${s}` : ''
}

/** "?step=<id>" suffix for a run URL ('' for no step). */
export function stepQuery(nodeId: string | null | undefined): string {
  const v = String(nodeId ?? '').trim()
  return v ? `?step=${encodeURIComponent(v)}` : ''
}
