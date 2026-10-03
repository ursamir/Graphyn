/**
 * Models page display helpers (pure).
 *
 * `GET /models/{name}` stages gain (UX API draft §4) resolved
 * `{ artifact_path, format, size_bytes, created_at, metrics, labels,
 *    source_run_id, exists }`; older APIs only carry `{ run_id, slug }`.
 */
import { formatBytes, humanNodeLabel } from '../../lib/format'
import { formatMetric, isRatioMetric, metricLabel, pickPrimaryMetric } from '../../lib/metrics'

export type ModelStage = {
  run_id?: string
  slug?: string
  path?: string
  artifact_path?: string
  format?: string
  size_bytes?: number
  created_at?: string
  metrics?: Record<string, unknown>
  labels?: string[]
  source_run_id?: string
  exists?: boolean
  path_label?: string
  display_name?: string
  /** UX API v1 registry stage fields. */
  kind?: string
  stage?: string
  alias_path?: string
  artifact_kind?: string
  node_id?: string
  path_id?: string
  source_run_display_name?: string
  updated_at?: string
}

/** Graph instance ids used as registry names / slugs (`edge_optimizer_0`, `trainer_b66a5330`). */
export function looksLikeNodeId(name: string): boolean {
  return /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*_(?:\d+|[a-f0-9]{6,})$/i.test(name.trim())
}

/** Human title for a registry entry: backend display_name, humanized node id, else the name. */
export function modelDisplayName(row: { name: string; display_name?: string | null }): string {
  const dn = typeof row.display_name === 'string' ? row.display_name.trim() : ''
  if (dn) return dn
  return looksLikeNodeId(row.name) ? `${humanNodeLabel(row.name)} model` : row.name
}

/** Stage preference for "the" version of a model: prod → staging → latest → first. */
export function preferredStageKey(stages: Record<string, unknown> | undefined | null): string | null {
  const s = stages || {}
  for (const k of ['prod', 'staging', 'latest']) if (s[k]) return k
  return Object.keys(s)[0] ?? null
}

export type StageFact = { label: string; value: string; title?: string }

/** Facts row for a stage card. Only includes facts the API actually returned. */
export function stageFacts(stage: ModelStage | null | undefined): StageFact[] {
  if (!stage) return []
  const out: StageFact[] = []
  const pm = pickPrimaryMetric(stage.metrics)
  if (pm) {
    out.push({
      label: metricLabel(pm.name),
      value: formatMetric(pm.value, { percent: isRatioMetric(pm.name, pm.value) }),
      title: `${pm.name} = ${pm.value}`,
    })
  }
  if (stage.format) out.push({ label: 'Format', value: stage.format })
  if (typeof stage.size_bytes === 'number' && stage.size_bytes > 0) {
    out.push({ label: 'Size', value: formatBytes(stage.size_bytes) })
  }
  if (Array.isArray(stage.labels) && stage.labels.length > 0) {
    const labels = stage.labels.map(String)
    out.push({
      label: 'Classes',
      value: labels.length <= 6 ? labels.join(', ') : `${labels.slice(0, 6).join(', ')} +${labels.length - 6}`,
      title: labels.join(', '),
    })
  }
  return out
}

/** Source run id of a stage (new `source_run_id`, else legacy `run_id`). */
export function stageRunId(stage: ModelStage | null | undefined): string | null {
  if (!stage) return null
  const id = stage.source_run_id || stage.run_id
  return typeof id === 'string' && id ? id : null
}

/** "Model stage" names in plain language. */
export const MODEL_STAGE_HELP: Record<string, string> = {
  staging: 'Staging — the candidate model being evaluated. Not used by devices yet.',
  prod: 'Production — the approved model devices and integrations should use.',
  latest: 'Latest — the most recently registered model, whatever its stage.',
}

export const REQUEST_PROD_HELP =
  'Ask for this staging model to become the production model. A second person (an approver) has to confirm it before devices and integrations switch to it.'

export function modelPrimaryMetricText(stage: ModelStage | null | undefined): string | null {
  const pm = pickPrimaryMetric(stage?.metrics)
  if (!pm) return null
  return `${metricLabel(pm.name)} ${formatMetric(pm.value, { percent: isRatioMetric(pm.name, pm.value) })}`
}
