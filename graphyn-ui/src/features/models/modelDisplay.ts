/**
 * Models page display helpers (pure).
 *
 * `GET /models/{name}` stages gain (UX API draft §4) resolved
 * `{ artifact_path, format, size_bytes, created_at, metrics, labels,
 *    source_run_id, exists }`; older APIs only carry `{ run_id, slug }`.
 */
import { formatBytes, humanNodeLabel, shortRunId } from '../../lib/format'
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

type ListRow = {
  name: string
  display_name?: string | null
  stages?: Record<string, ModelStage> | null
  updated_at?: string
  created_at?: string
}

function shortDate(iso: string | undefined | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toISOString().slice(0, 10)
}

/**
 * List titles that stay distinguishable: rows whose `modelDisplayName`
 * collides (two "Edge Optimizer model") get a suffix — the source run's short
 * id and the stage date (`· run 1a2b3c4d · 2026-10-03`); the raw registry
 * name is the last resort. Unique titles are unchanged. Keyed by `name`.
 */
export function disambiguatedModelTitles(rows: ListRow[]): Map<string, string> {
  const out = new Map<string, string>()
  const groups = new Map<string, ListRow[]>()
  for (const r of rows) {
    const t = modelDisplayName(r)
    groups.set(t, [...(groups.get(t) || []), r])
  }
  for (const [title, group] of groups) {
    if (group.length === 1) {
      out.set(group[0].name, title)
      continue
    }
    const suffixed = group.map((r) => {
      const key = preferredStageKey(r.stages)
      const st = key ? r.stages?.[key] : null
      const run = stageRunId(st)
      const date = shortDate(st?.created_at || st?.updated_at || r.updated_at || r.created_at)
      const bits = [run ? `run ${shortRunId(run)}` : '', date].filter(Boolean)
      return { r, label: bits.length ? `${title} · ${bits.join(' · ')}` : title }
    })
    const counts = new Map<string, number>()
    for (const s of suffixed) counts.set(s.label, (counts.get(s.label) || 0) + 1)
    for (const s of suffixed) {
      const label = (counts.get(s.label) || 0) > 1 && s.r.name !== title ? `${s.label} · ${s.r.name}` : s.label
      out.set(s.r.name, label)
    }
  }
  return out
}

/** Registry row for a `/models/<name>` route param (exact name, else case-insensitive). */
export function findModelForRoute<T extends { name: string }>(rows: T[], routeName: string | null | undefined): T | null {
  const want = String(routeName || '').trim()
  if (!want) return null
  return rows.find((r) => r.name === want) ?? rows.find((r) => r.name.toLowerCase() === want.toLowerCase()) ?? null
}
