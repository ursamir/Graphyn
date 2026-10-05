/**
 * Compare runs — view model for `GET /runs/compare/diff?ids=a,b[,…][&all=1]`
 * (app/core/runs/run_diff.py). Pure; unit-tested (compareDiff.test.ts).
 *
 * Every section row carries per-run `values` aligned with `runs` order and a
 * `differs` flag; only differing rows come back unless `all=1`.
 */
import { formatMetricValue, metricLabel } from '../../lib/metrics'
import { runStatusLabel } from '../../lib/runDisplay'
import { higherIsBetter } from '../runs/runResults'

type Rec = Record<string, unknown>

function asRec(v: unknown): Rec | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null
}

function str(v: unknown): string {
  if (typeof v === 'string') return v.trim()
  if (typeof v === 'number' && Number.isFinite(v)) return String(v)
  return ''
}

function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

function num(v: unknown): number | null {
  const n = typeof v === 'string' && v.trim() !== '' ? Number(v) : v
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

export type DiffRun = {
  runId: string
  short: string
  name: string
  startedAt: string
  status: string
  graphHash: string
  seed: unknown
  sealed: boolean
}

export type DiffSummary = {
  settingsChanged: number
  dataSame: boolean | null
  codeSame: boolean | null
  environmentSame: boolean | null
  graphSame: boolean | null
  seedSame: boolean | null
}

export type SettingRow = {
  nodeId: string
  nodeType: string
  nodeLabel: string
  pathId: string
  pathLabel: string
  key: string
  values: unknown[]
  present: boolean[]
  differs: boolean
  hasDefault: boolean
  default: unknown
}

export type DataRow = {
  nodeId: string
  key: string
  label: string
  paths: string[]
  hashes: string[]
  fileCounts: Array<number | null>
  datasetVersions: string[]
  differs: boolean
}

export type CodeRow = {
  nodeType: string
  plugins: string[]
  versions: string[]
  codeHashes: string[]
  versionDiffers: boolean
  codeDiffers: boolean
  differs: boolean
}

export type EnvRow = { key: string; values: unknown[]; differs: boolean }

export type MetricRow = {
  pathId: string
  pathLabel: string
  pathLabels: string[]
  best: boolean[]
  metric: string
  values: Array<number | null>
  differs: boolean
}

export type CompareDiff = {
  runs: DiffRun[]
  summary: DiffSummary
  settings: SettingRow[]
  data: DataRow[]
  code: CodeRow[]
  environment: EnvRow[]
  metricPaths: MetricRow[]
  headline: Array<{ metric: string; values: Array<number | null>; pathLabels: string[] }>
  primaryMetric: string
  includeAll: boolean
}

function boolOrNull(v: unknown): boolean | null {
  return typeof v === 'boolean' ? v : null
}

/** Parse the diff payload; null when it has no runs. */
export function parseCompareDiff(raw: unknown): CompareDiff | null {
  const r = asRec(raw)
  if (!r) return null
  const runs: DiffRun[] = arr(r.runs)
    .map(asRec)
    .filter((x): x is Rec => !!x && !!str(x.run_id))
    .map((x) => ({
      runId: str(x.run_id),
      short: str(x.short) || str(x.run_id).slice(0, 8),
      name: str(x.name),
      startedAt: str(x.started_at),
      status: str(x.status),
      graphHash: str(x.graph_hash),
      seed: x.seed ?? null,
      sealed: x.sealed === true,
    }))
  if (runs.length === 0) return null
  const s = asRec(r.summary) || {}
  const settings: SettingRow[] = arr(r.settings)
    .map(asRec)
    .filter((x): x is Rec => !!x)
    .map((x) => ({
      nodeId: str(x.node_id),
      nodeType: str(x.node_type),
      nodeLabel: str(x.node_label) || str(x.node_id),
      pathId: str(x.path_id),
      pathLabel: str(x.path_label),
      key: str(x.key),
      values: arr(x.values),
      present: arr(x.present).map((p) => p !== false),
      differs: x.differs === true,
      hasDefault: 'default' in x,
      default: x.default,
    }))
  const data: DataRow[] = arr(r.data)
    .map(asRec)
    .filter((x): x is Rec => !!x)
    .map((x) => ({
      nodeId: str(x.node_id),
      key: str(x.key),
      label: str(x.label) || `${str(x.node_id)} · ${str(x.key)}`,
      paths: arr(x.paths).map(str),
      hashes: arr(x.content_hashes).map(str),
      fileCounts: arr(x.file_counts).map(num),
      datasetVersions: arr(x.dataset_versions).map(str),
      differs: x.differs === true,
    }))
  const code: CodeRow[] = arr(r.code)
    .map(asRec)
    .filter((x): x is Rec => !!x)
    .map((x) => ({
      nodeType: str(x.node_type),
      plugins: arr(x.plugins).map(str),
      versions: arr(x.versions).map(str),
      codeHashes: arr(x.code_hashes).map(str),
      versionDiffers: x.version_differs === true,
      codeDiffers: x.code_differs === true,
      differs: x.differs === true,
    }))
  const environment: EnvRow[] = arr(r.environment)
    .map(asRec)
    .filter((x): x is Rec => !!x)
    .map((x) => ({ key: str(x.key), values: arr(x.values), differs: x.differs === true }))
  const m = asRec(r.metrics) || {}
  const pm = m.primary_metric
  const primaryMetric = typeof pm === 'string' ? pm.trim() : str(asRec(pm)?.name)
  const metricPaths: MetricRow[] = arr(m.paths)
    .map(asRec)
    .filter((x): x is Rec => !!x && !!str(x.metric))
    .map((x) => ({
      pathId: str(x.path_id),
      pathLabel: str(x.path_label) || str(x.path_id),
      pathLabels: arr(x.path_labels).map(str),
      best: arr(x.best).map((b) => b === true),
      metric: str(x.metric),
      values: arr(x.values).map(num),
      differs: x.differs === true,
    }))
  const headline = arr(m.headline)
    .map(asRec)
    .filter((x): x is Rec => !!x && !!str(x.metric))
    .map((x) => ({ metric: str(x.metric), values: arr(x.values).map(num), pathLabels: arr(x.path_labels).map(str) }))
  return {
    runs,
    summary: {
      settingsChanged: num(s.settings_changed) ?? settings.filter((x) => x.differs).length,
      dataSame: boolOrNull(s.data_same),
      codeSame: boolOrNull(s.code_same),
      environmentSame: boolOrNull(s.environment_same),
      graphSame: boolOrNull(s.graph_same),
      seedSame: boolOrNull(s.seed_same),
    },
    settings,
    data,
    code,
    environment,
    metricPaths,
    headline,
    primaryMetric,
    includeAll: r.include_all === true,
  }
}

/** "2 settings changed · same data · same code · different environment · same seed". */
export function diffSummarySentence(s: DiffSummary): string {
  const parts: string[] = []
  parts.push(
    s.settingsChanged === 0
      ? 'same settings'
      : `${s.settingsChanged} setting${s.settingsChanged === 1 ? '' : 's'} changed`,
  )
  const pair = (v: boolean | null, noun: string) => {
    if (v == null) return
    parts.push(`${v ? 'same' : 'different'} ${noun}`)
  }
  pair(s.dataSame, 'data')
  pair(s.codeSame, 'code')
  pair(s.environmentSame, 'environment')
  pair(s.seedSame, 'seed')
  return parts.join(' · ')
}

/** Readable cell text for a setting / environment value. */
export function formatDiffValue(v: unknown): string {
  if (v === undefined || v === null) return '—'
  if (typeof v === 'string') return v === '' ? '""' : v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    const s = JSON.stringify(v)
    return s.length > 120 ? `${s.slice(0, 117)}…` : s
  } catch {
    return String(v)
  }
}

export type SettingGroup = { key: string; title: string; pathLabel: string; nodeLabel: string; rows: SettingRow[] }

/** Settings grouped by path → step ("Path B · Trainer"), in server order. */
export function groupSettings(rows: SettingRow[]): SettingGroup[] {
  const out: SettingGroup[] = []
  const by = new Map<string, SettingGroup>()
  for (const row of rows) {
    const k = `${row.pathId}|${row.nodeId}`
    let g = by.get(k)
    if (!g) {
      g = {
        key: k,
        title: [row.pathLabel, row.nodeLabel].filter(Boolean).join(' · ') || row.nodeId,
        pathLabel: row.pathLabel,
        nodeLabel: row.nodeLabel,
        rows: [],
      }
      by.set(k, g)
      out.push(g)
    }
    g.rows.push(row)
  }
  return out
}

/** Index of the best value in a metric row (null when < 2 numbers or all equal). */
export function bestValueIndex(metric: string, values: Array<number | null>): number | null {
  const nums = values.map((v, i) => [v, i] as const).filter((p): p is readonly [number, number] => p[0] != null)
  if (nums.length < 2) return null
  if (nums.every((p) => p[0] === nums[0][0])) return null
  const high = higherIsBetter(metric)
  let best = nums[0]
  for (const p of nums) if (high ? p[0] > best[0] : p[0] < best[0]) best = p
  return best[1]
}

export type ResultGroup = {
  pathId: string
  pathLabel: string
  /** Per run: was this path that run's best path? */
  best: boolean[]
  /** Primary metric first, then the rest (server order). */
  rows: MetricRow[]
}

/**
 * Results per path: rows = paths × metrics, primary metric first within each
 * path. Single-path runs without `metrics.paths` fall back to `headline`.
 */
export function resultGroups(diff: Pick<CompareDiff, 'metricPaths' | 'headline' | 'primaryMetric' | 'runs'>): ResultGroup[] {
  const groups: ResultGroup[] = []
  const by = new Map<string, ResultGroup>()
  const source: MetricRow[] = diff.metricPaths.length
    ? diff.metricPaths
    : diff.headline.map((h) => ({
        pathId: 'run',
        pathLabel: 'Whole run',
        pathLabels: h.pathLabels,
        best: diff.runs.map(() => false),
        metric: h.metric,
        values: h.values,
        differs: new Set(h.values.map((v) => String(v))).size > 1,
      }))
  for (const row of source) {
    let g = by.get(row.pathId)
    if (!g) {
      g = { pathId: row.pathId, pathLabel: row.pathLabel, best: row.best, rows: [] }
      by.set(row.pathId, g)
      groups.push(g)
    }
    g.rows.push(row)
  }
  const pm = diff.primaryMetric
  for (const g of groups) {
    g.rows.sort((a, b) => (a.metric === pm ? -1 : 0) - (b.metric === pm ? -1 : 0))
  }
  return groups
}

/** Metric cell text: "75.6%" for ratios, "0.412" otherwise, "—" when missing. */
export function metricCell(metric: string, v: number | null): string {
  return v == null ? '—' : formatMetricValue(metric, v)
}

/** Column header pieces for a run: short id · name · start · status ("Done"). */
export function runColumnTitle(r: DiffRun): { short: string; name: string; status: string } {
  return { short: r.short, name: r.name || `Run ${r.short}`, status: runStatusLabel(r.status) }
}

/** "Test accuracy" for metric keys; environment keys get friendly names. */
export function envKeyLabel(key: string): string {
  const map: Record<string, string> = {
    python: 'Python',
    implementation: 'Python implementation',
    os: 'OS',
    machine: 'Machine',
    image: 'Container image',
    graphyn_version: 'Graphyn',
    git_commit: 'Git commit',
    backend: 'Backend',
  }
  if (map[key]) return map[key]
  if (key.startsWith('library:')) return key.slice('library:'.length)
  return metricLabel(key)
}

function csvEscape(v: unknown): string {
  const s = v == null ? '' : String(v)
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** CSV of the diff (raw values): section, item, key, one column per run. */
export function compareDiffCsv(diff: CompareDiff): string {
  const lines = [['section', 'item', 'key', ...diff.runs.map((r) => r.runId)].map(csvEscape).join(',')]
  const raw = (v: unknown) => (v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v))
  for (const s of diff.settings) {
    lines.push(['settings', [s.pathLabel, s.nodeLabel].filter(Boolean).join(' · '), s.key, ...s.values.map(raw)].map(csvEscape).join(','))
  }
  for (const m of diff.metricPaths) {
    lines.push(['results', m.pathLabel, m.metric, ...m.values.map(raw)].map(csvEscape).join(','))
  }
  for (const d of diff.data) lines.push(['data', d.label, 'content_hash', ...d.hashes].map(csvEscape).join(','))
  for (const c of diff.code) {
    lines.push(['code', c.nodeType, 'version', ...c.versions].map(csvEscape).join(','))
    lines.push(['code', c.nodeType, 'code_hash', ...c.codeHashes].map(csvEscape).join(','))
  }
  for (const e of diff.environment) lines.push(['environment', '', e.key, ...e.values.map(raw)].map(csvEscape).join(','))
  return lines.join('\n')
}
