/**
 * Run audit trail — chronological story of what happened in this run:
 * each step’s status/duration, what it wrote, and what fed it / what it fed.
 * File downloads live in Run outputs.
 */
import React from 'react'
import { ArrowRight, RefreshCw } from 'lucide-react'
import { apiJson } from '../../api/client'
import { CopyableMono, EmptyState, ErrorBanner, LoadingBlock } from '../../components/ui'
import { ReproPackButton } from '../../components/ReproPackButton'
import { displayNodeLabel, focusMatchesNode, humanizeTemplateName, shortRunId } from '../../lib/format'
import { fetchRunGraph } from '../../lib/runGraph'
import {
  computePipelineShape,
  isMultiTrackShape,
  laneLabel,
  type PipelineShape,
} from './runNodes'
import { formatMetricValue, isRatioMetric, metricLabel, pickPrimaryMetric } from '../../lib/metrics'
import { pathDisplayName, scalarMetrics, type PathResult } from './runResults'
import { EvaluatorResult, PathMetricChip } from './RunResults'
import type { EvaluatorOutputs } from './useRunResults'
import { failureView, linkableRunId, type FailureView } from './runRecord'
import { FailureDetails } from './FailureDetails'
import { humanizeErrorText } from '../../lib/errorText'

function shortStatusLabel(status?: string | null): string {
  const s = String(status || '').toLowerCase()
  if (s === 'succeeded' || s === 'success' || s === 'completed' || s === 'done') return 'Done'
  if (s === 'failed' || s === 'error') return 'Failed'
  if (s === 'cancelled' || s === 'canceled') return 'Cancelled'
  if (s === 'running') return 'Running'
  if (s === 'queued') return 'Queued'
  if (s === 'paused') return 'Paused'
  if (s === 'skipped') return 'Skipped'
  return status ? String(status) : 'Unknown'
}

type TraceChainStep = {
  step: string
  label: string
  id?: string
  status?: string
  node_type?: string
  present?: boolean
}

type TraceNode = {
  id?: string
  node_type?: string
  status?: string
  duration_ms?: number | null
  cache_hit?: boolean | null
  error?: string | null
}

type TracePayload = {
  run?: {
    run_id?: string
    status?: string
    graph_name?: string
    created_at?: string
  } | null
  graph?: { name?: string; hash?: string; node_count?: number | null } | null
  lineage?: {
    inputs?: Array<Record<string, unknown>>
    nodes?: TraceNode[]
    artifacts?: Array<Record<string, unknown>>
    artifact_count?: number
    provenance_count?: number
  }
  chain?: TraceChainStep[]
  warnings?: string[]
}

type OutputFileHint = {
  name?: string
  path?: string
  kind?: string
  node_id?: string | null
}

type GraphEdge = { src_id?: unknown; dst_id?: unknown }

type StepStory = {
  id: string
  label: string
  nodeType?: string
  status: string
  durationMs: number | null
  cacheHit: boolean
  error: string | null
  wrote: string
  fileCount: number
  from: string[]
  to: string[]
  /** Edges came from graph IR (true) vs sequential fallback (false). */
  wired: boolean
}

function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m ${s}s`
}

function statusTone(status: string): string {
  const s = status.toLowerCase()
  if (s === 'failed' || s === 'error') return 'bg-rose-100 text-rose-900'
  if (s === 'skipped' || s === 'cancelled' || s === 'canceled') return 'bg-ink-100 text-ink-600'
  if (s === 'running' || s === 'queued' || s === 'paused') return 'bg-amber-100 text-amber-950'
  if (s === 'completed' || s === 'succeeded' || s === 'success' || s === 'done')
    return 'bg-emerald-100 text-emerald-900'
  return 'bg-ink-100 text-ink-700'
}

function summarizeWrote(
  files: OutputFileHint[],
  opts?: { inventoryTotal?: number | null },
): { text: string; count: number } {
  const inventoryTotal = opts?.inventoryTotal
  // Match Run outputs empty copy — “nothing listed” sounded like a bug.
  if (!files.length && !(inventoryTotal && inventoryTotal > 0)) {
    return { text: 'no files (data stayed in memory)', count: 0 }
  }
  const names = files.map((f) => String(f.name || f.path?.split('/').pop() || '').trim()).filter(Boolean)
  const audioish = names.filter((n) => /\.(wav|flac|mp3|ogg)$/i.test(n)).length
  const total =
    typeof inventoryTotal === 'number' && inventoryTotal > names.length
      ? inventoryTotal
      : names.length
  // Prefer inventory total — UI listing caps audio dumps at ~32 samples.
  if (total >= 6 && (audioish >= names.length * 0.6 || (names.length === 0 && total >= 6))) {
    return { text: `${total.toLocaleString()} audio clips`, count: total }
  }
  if (!names.length) {
    return { text: `${total.toLocaleString()} files`, count: total }
  }
  const models = names.filter((n) => /\.(keras|h5|tflite|onnx|pb|pt|pth)$/i.test(n) || /model/i.test(n))
  const metrics = names.filter((n) => /metrics|confusion|roc|label/i.test(n) || /\.json$/i.test(n))
  const pick = [...new Set([...models, ...metrics, ...names])].filter(Boolean)
  const shown = pick.slice(0, 3)
  const listedExtra = pick.length - shown.length
  const hidden = Math.max(0, total - names.length)
  const more = listedExtra + hidden
  return {
    text: shown.join(', ') + (more > 0 ? ` +${more.toLocaleString()} more` : ''),
    count: total,
  }
}

function normalizeEdges(raw: GraphEdge[]): GraphEdge[] {
  const out: GraphEdge[] = []
  for (const e of raw) {
    const src = String(e.src_id || '').trim()
    const dst = String(e.dst_id || '').trim()
    if (src && dst) out.push({ src_id: src, dst_id: dst })
  }
  return out
}

function buildStories(input: {
  chain: TraceChainStep[]
  nodes: TraceNode[]
  files: OutputFileHint[]
  edges: GraphEdge[]
  /** Prefer Pipeline stack order so Overview matches the left rail. */
  orderedNodeIds?: string[]
  labelFor?: (id: string) => string | undefined
  /** Extra duration/status from debug.node_stats (node_id keyed). */
  nodeStatsExtra?: Array<Record<string, unknown>>
  /** Inventory totals from outputs `truncated_by_node` (real count when UI list is capped). */
  fileTotalsByNode?: Record<string, number>
}): StepStory[] {
  const nodeById = new Map<string, TraceNode>()
  for (const n of input.nodes) {
    const id = String(n.id || '').trim()
    if (id) nodeById.set(id, n)
  }
  const statsExtra = new Map<string, Record<string, unknown>>()
  for (const n of input.nodeStatsExtra || []) {
    const id = String(n.node_id || n.id || '').trim()
    if (id) statsExtra.set(id, n)
  }
  const filesByNode = new Map<string, OutputFileHint[]>()
  for (const f of input.files) {
    const nid = String(f.node_id || '').trim()
    if (!nid) continue
    const arr = filesByNode.get(nid) || []
    arr.push(f)
    filesByNode.set(nid, arr)
  }

  const realEdges = normalizeEdges(input.edges)
  const wired = realEdges.length > 0
  const fromMap = new Map<string, string[]>()
  const toMap = new Map<string, string[]>()
  for (const e of realEdges) {
    const src = String(e.src_id)
    const dst = String(e.dst_id)
    toMap.set(src, [...(toMap.get(src) || []), dst])
    fromMap.set(dst, [...(fromMap.get(dst) || []), src])
  }

  const nodeSteps = input.chain.filter((s) => s.step === 'node' && s.id)
  const orderedIds: string[] = []
  const pushId = (id: string) => {
    const t = id.trim()
    if (t && !orderedIds.includes(t)) orderedIds.push(t)
  }
  for (const id of input.orderedNodeIds || []) pushId(String(id))
  for (const s of nodeSteps) pushId(String(s.id))
  for (const n of input.nodes) pushId(String(n.id || ''))
  for (const id of statsExtra.keys()) pushId(id)

  // When the graph IR has no edges, still tell a readable story using list order.
  if (!wired && orderedIds.length > 1) {
    for (let i = 0; i < orderedIds.length - 1; i++) {
      const src = orderedIds[i]
      const dst = orderedIds[i + 1]
      toMap.set(src, [...(toMap.get(src) || []), dst])
      fromMap.set(dst, [...(fromMap.get(dst) || []), src])
    }
  }

  return orderedIds.map((id) => {
    const chain = nodeSteps.find((s) => s.id === id)
    const stats = nodeById.get(id)
    const extra = statsExtra.get(id)
    const files = filesByNode.get(id) || []
    const loose =
      files.length > 0
        ? files
        : input.files.filter((f) => focusMatchesNode(id, String(f.node_id || '')))
    const inventoryTotal = (() => {
      const totals = input.fileTotalsByNode || {}
      if (typeof totals[id] === 'number') return totals[id]
      for (const [nid, n] of Object.entries(totals)) {
        if (focusMatchesNode(id, nid) || focusMatchesNode(nid, id)) return n
      }
      return null
    })()
    const wrote = summarizeWrote(loose, { inventoryTotal })
    const rawStatus = String(
      stats?.status || extra?.status || extra?.state || chain?.status || 'unknown',
    )
    const durationRaw = stats?.duration_ms ?? extra?.duration_ms
    const durationMs =
      typeof durationRaw === 'number' && Number.isFinite(durationRaw) ? durationRaw : null
    return {
      id,
      label:
        input.labelFor?.(id) ||
        displayNodeLabel(id, {
          label: chain?.label,
          nodeType: String(stats?.node_type || chain?.node_type || extra?.node_type || '') || undefined,
          withCue: true,
        }),
      nodeType: String(stats?.node_type || chain?.node_type || extra?.node_type || ''),
      status: rawStatus,
      durationMs,
      cacheHit: stats?.cache_hit === true || extra?.cache_hit === true,
      error: stats?.error
        ? String(stats.error)
        : extra?.error
          ? String(extra.error)
          : null,
      wrote: wrote.text,
      fileCount: wrote.count,
      from: [...new Set(fromMap.get(id) || [])],
      to: [...new Set(toMap.get(id) || [])],
      wired,
    }
  })
}

function laneToneClass(lane: string): string {
  if (lane === 'shared') return 'bg-ink-100 text-ink-600'
  if (lane === 'A') return 'bg-sky-50 text-sky-800'
  if (lane === 'B') return 'bg-teal-50 text-teal-800'
  return 'bg-amber-50 text-amber-900'
}

function shortPillLabel(full: string): string {
  // Inside a Path track the "· Path B" suffix is redundant.
  const t = full.trim().replace(/\s·\sPath [A-Z]$/, '')
  if (t.length <= 22) return t
  // Keep trailing #cue when present.
  const cue = t.match(/\s+(#\S+)$/)
  const base = cue ? t.slice(0, t.length - cue[0].length) : t
  const clipped = base.length > 16 ? `${base.slice(0, 14)}…` : base
  return cue ? `${clipped} ${cue[1]}` : `${t.slice(0, 20)}…`
}

function storyById(stories: StepStory[]): Map<string, StepStory> {
  return new Map(stories.map((s) => [s.id, s]))
}

function trackDurationMs(ids: string[], byId: Map<string, StepStory>): number {
  return ids.reduce((acc, id) => acc + (byId.get(id)?.durationMs || 0), 0)
}

/** Tip wrote string for a track (last file-producing step). */
function trackTipWrote(ids: string[], byId: Map<string, StepStory>): string | null {
  for (let i = ids.length - 1; i >= 0; i--) {
    const s = byId.get(ids[i])
    if (s && s.fileCount > 0) return s.wrote
  }
  return null
}

/** Domain-agnostic primary outcome for a linear run. */
function linearOutcome(stories: StepStory[]): string | null {
  const withFiles = stories.filter((s) => s.fileCount > 0)
  if (!withFiles.length) return null
  const scored = [...withFiles].sort((a, b) => {
    const score = (s: StepStory) => {
      let n = 0
      if (/model|optim|train|export|edge|packag|caption|transcript/i.test(s.label + s.wrote)) n += 3
      if (/metric|eval|test|confus/i.test(s.label + s.wrote)) n += 2
      if (/\.(keras|h5|tflite|onnx|json|csv|txt)/i.test(s.wrote)) n += 2
      n += Math.min(s.fileCount, 5)
      return n
    }
    return score(b) - score(a)
  })
  const top = scored[0]
  return top ? top.wrote : null
}

function pillStatusClass(status: string): string {
  const s = status.toLowerCase()
  if (s === 'failed' || s === 'error') return 'border-rose-300 bg-rose-50 text-rose-900'
  if (s === 'skipped' || s === 'cancelled' || s === 'canceled')
    return 'border-dashed border-ink-300 bg-ink-50/50 text-ink-400'
  if (s === 'running' || s === 'queued' || s === 'paused')
    return 'border-amber-300 bg-amber-50 text-amber-950'
  if (s === 'completed' || s === 'succeeded' || s === 'success' || s === 'done')
    return 'border-emerald-200 bg-emerald-50/80 text-ink-900'
  return 'border-ink-200 bg-white text-ink-800'
}

function StepPill({
  story,
  active,
  onFocus,
}: {
  story: StepStory
  active: boolean
  onFocus?: (id: string) => void
}) {
  const label = shortPillLabel(story.label)
  return (
    <button
      type="button"
      title={`${story.label} · ${shortStatusLabel(story.status)} · ${formatDuration(story.durationMs)}`}
      onClick={() => onFocus?.(story.id)}
      className={`flex min-w-[4.5rem] max-w-[9rem] shrink-0 flex-col items-stretch rounded-lg border px-2 py-1.5 text-left transition ${pillStatusClass(
        story.status,
      )} ${active ? 'ring-2 ring-accent-400 ring-offset-1' : 'hover:border-ink-300'}`}
    >
      <span className="truncate text-[11px] font-semibold leading-tight">{label}</span>
      <span className="mt-0.5 tabular-nums text-[10px] text-ink-500">
        {formatDuration(story.durationMs)}
      </span>
    </button>
  )
}

function PillSpine({
  ids,
  byId,
  focusNodeId,
  onFocusStep,
}: {
  ids: string[]
  byId: Map<string, StepStory>
  focusNodeId?: string | null
  onFocusStep?: (nodeId: string | null) => void
}) {
  const stories = ids.map((id) => byId.get(id)).filter(Boolean) as StepStory[]
  if (!stories.length) return null
  return (
    <div className="flex min-w-0 items-stretch gap-1 overflow-x-auto pb-0.5 [scrollbar-gutter:stable]">
      {stories.map((s, i) => (
        <React.Fragment key={s.id}>
          {i > 0 ? (
            <span className="mt-3 shrink-0 text-[10px] text-ink-300" aria-hidden>
              →
            </span>
          ) : null}
          <StepPill
            story={s}
            active={Boolean(focusNodeId && focusMatchesNode(focusNodeId, s.id))}
            onFocus={onFocusStep ? (id) => onFocusStep(id) : undefined}
          />
        </React.Fragment>
      ))}
    </div>
  )
}

function ForkConnector({ trackCount }: { trackCount: number }) {
  // Simple Y-split affordance between shared spine and path tracks.
  const label = trackCount === 2 ? 'fork' : `${trackCount} paths`
  return (
    <div className="flex items-center gap-2 py-1" aria-hidden>
      <div className="h-px flex-1 bg-ink-200" />
      <span className="text-[10px] font-medium uppercase tracking-wide text-ink-400">{label}</span>
      <div className="h-px flex-1 bg-ink-200" />
    </div>
  )
}

function DurationBar({ ms, maxMs, tone }: { ms: number; maxMs: number; tone: string }) {
  const pct = maxMs > 0 ? Math.max(4, Math.round((ms / maxMs) * 100)) : 0
  const bar =
    tone === 'A' ? 'bg-sky-400' : tone === 'B' ? 'bg-teal-400' : 'bg-amber-400'
  return (
    <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-ink-100">
      <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function PathTrack({
  lane,
  ids,
  byId,
  maxTrackMs,
  focusNodeId,
  onFocusStep,
  path,
  best,
}: {
  lane: string
  ids: string[]
  byId: Map<string, StepStory>
  maxTrackMs: number
  focusNodeId?: string | null
  onFocusStep?: (nodeId: string | null) => void
  /** Results for this path (description + metrics) when known. */
  path?: PathResult | null
  best?: boolean
}) {
  const total = trackDurationMs(ids, byId)
  const tip = trackTipWrote(ids, byId)
  const letter = path?.letter || lane
  return (
    <div
      className={`min-w-0 rounded-lg border px-2.5 py-2 ${
        best ? 'border-emerald-200 bg-emerald-50/40' : 'border-ink-100 bg-ink-50/40'
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <span className="flex min-w-0 flex-wrap items-center gap-1.5">
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${laneToneClass(letter)}`}
          >
            {laneLabel(letter)}
          </span>
          {path?.description ? (
            <span className="truncate text-[11px] font-medium text-ink-700">{path.description}</span>
          ) : null}
        </span>
        <span className="flex items-center gap-1.5">
          {path ? <PathMetricChip path={path} best={best} /> : null}
          <span className="tabular-nums text-[11px] text-ink-500">{formatDuration(total)}</span>
        </span>
      </div>
      {maxTrackMs > 0 ? <DurationBar ms={total} maxMs={maxTrackMs} tone={letter} /> : null}
      <div className="mt-2">
        <PillSpine ids={ids} byId={byId} focusNodeId={focusNodeId} onFocusStep={onFocusStep} />
      </div>
      {tip ? (
        <p className="mt-1.5 truncate text-[11px] text-ink-600" title={tip}>
          <span className="text-ink-400">Got </span>
          {tip}
        </p>
      ) : (
        <p className="mt-1.5 text-[11px] text-ink-400">No files on this path</p>
      )}
    </div>
  )
}

/**
 * Adaptive run story map: linear duration spine (default), or fork / parallel
 * tracks when the graph has multiple sinks.
 */
function RunStoryMap({
  shape,
  stories,
  focusNodeId,
  onFocusStep,
  savedFiles,
  provenance,
  lanePaths,
  bestPathId,
}: {
  shape: PipelineShape
  stories: StepStory[]
  focusNodeId?: string | null
  onFocusStep?: (nodeId: string | null) => void
  savedFiles?: number | null
  provenance?: number | null
  lanePaths?: Map<string, PathResult> | null
  bestPathId?: string | null
}) {
  const byId = storyById(stories)
  const multi = isMultiTrackShape(shape)

  const trackTotals = shape.branches.map((b) => trackDurationMs(b, byId))
  const maxTrackMs = Math.max(0, ...trackTotals)

  let outcomeBlock: React.ReactNode = null
  if (!multi) {
    const got = linearOutcome(stories)
    // Linear = Got + spine only (no Path metric chip on the story line — headline lives in Overview banner / Metrics).
    outcomeBlock = got ? (
      <p className="text-[12px] leading-relaxed text-ink-700">
        <span className="text-ink-400">Got </span>
        {got}
      </p>
    ) : (
      <p className="text-[12px] text-ink-400">Got no downloadable files (data stayed in memory)</p>
    )
  }

  return (
    <div className="mt-2 space-y-2">
      {outcomeBlock}
      {!multi ? (
        <PillSpine
          ids={shape.sharedIds}
          byId={byId}
          focusNodeId={focusNodeId}
          onFocusStep={onFocusStep}
        />
      ) : (
        <>
          {shape.kind === 'fork' && shape.sharedIds.length > 0 ? (
            <div>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                Shared
              </div>
              <PillSpine
                ids={shape.sharedIds}
                byId={byId}
                focusNodeId={focusNodeId}
                onFocusStep={onFocusStep}
              />
              <ForkConnector trackCount={shape.branches.length} />
            </div>
          ) : null}
          <div
            className={`grid gap-2 ${
              shape.branches.length === 2 ? 'sm:grid-cols-2' : 'sm:grid-cols-2 lg:grid-cols-3'
            }`}
          >
            {shape.branches.map((branch, i) => {
              const lane = String.fromCharCode(65 + i)
              const path = lanePaths?.get(lane) ?? null
              return (
                <PathTrack
                  key={lane}
                  lane={lane}
                  ids={branch}
                  byId={byId}
                  maxTrackMs={maxTrackMs}
                  focusNodeId={focusNodeId}
                  onFocusStep={onFocusStep}
                  path={path}
                  best={Boolean(path && bestPathId && path.pathId === bestPathId && shape.branches.length > 1)}
                />
              )
            })}
          </div>
        </>
      )}
      {typeof savedFiles === 'number' || (typeof provenance === 'number' && provenance > 0) ? (
        <p className="text-[11px] text-ink-400">
          {typeof savedFiles === 'number' ? (
            <>
              <span className="font-medium text-ink-600">{savedFiles}</span> saved files
            </>
          ) : null}
          {typeof savedFiles === 'number' && typeof provenance === 'number' && provenance > 0
            ? ' · '
            : null}
          {typeof provenance === 'number' && provenance > 0 ? (
            <>
              <span className="font-medium text-ink-600">{provenance}</span> provenance
            </>
          ) : null}
        </p>
      ) : null}
    </div>
  )
}

type TimelineRow = { story: StepStory; execIndex: number }

/** Chronological list, or Shared → Path A → Path B when multi-track. */
function timelineSections(
  stories: StepStory[],
  shape: PipelineShape,
  lanePaths?: Map<string, PathResult> | null,
): Array<{ key: string; label: string | null; rows: TimelineRow[] }> {
  const indexed = stories.map((story, i) => ({ story, execIndex: i + 1 }))
  if (!isMultiTrackShape(shape)) {
    return [{ key: 'all', label: null, rows: indexed }]
  }
  const laneOrder: string[] = []
  if (shape.kind === 'fork') laneOrder.push('shared')
  shape.branches.forEach((_, i) => laneOrder.push(String.fromCharCode(65 + i)))
  const sections: Array<{ key: string; label: string | null; rows: TimelineRow[] }> = []
  for (const lane of laneOrder) {
    const rows = indexed.filter((r) => (shape.laneOf.get(r.story.id) || 'shared') === lane)
    if (!rows.length) continue
    const path = lane === 'shared' ? null : lanePaths?.get(lane)
    sections.push({
      key: lane,
      label: path ? pathDisplayName(path) : laneLabel(lane),
      rows,
    })
  }
  // Any leftover ids (should be rare)
  const seen = new Set(sections.flatMap((s) => s.rows.map((r) => r.story.id)))
  const rest = indexed.filter((r) => !seen.has(r.story.id))
  if (rest.length) sections.push({ key: 'rest', label: null, rows: rest })
  return sections
}

export type OverviewExtras = {
  artifactCount?: number
  provenanceCount?: number
  checkpointCount?: number
  errorCount?: number
  metrics?: Record<string, unknown> | null
  /** "Path C (DS-CNN · 30 epochs)" when `metrics` are the best path's (multi-path runs). */
  metricsPathLabel?: string | null
  /** Other paths' headline metric, shown under the box for context. */
  otherPathMetrics?: Array<{ label: string; primary: { name: string; value: number } }>
  recentErrors?: Array<Record<string, unknown>>
  showRegisterCta?: boolean
  registerLabel?: string
  onRegister?: () => void
  onJumpLogs?: () => void
  /** Raw node_stats rows for duration enrichment + hot spots. */
  nodeStats?: Array<Record<string, unknown>>
}

/** Run Overview — verdict, metrics, and audit trail (Pipeline-stack order). */
export function RunLineagePanel({
  runId,
  runMeta,
  focusNodeId = null,
  onBrowseOutputs,
  onFocusStep,
  outputFiles,
  fileTotalsByNode,
  graphEdges,
  labelFor,
  orderedNodeIds,
  overview,
  lanePaths,
  nodePaths,
  bestPathId,
  evaluator,
  cacheSources,
  stepFailures,
  runLabelFor,
  onOpenRun,
}: {
  /** node id → run whose cached outputs this step reused (`cache_source_run_id`). */
  cacheSources?: Map<string, string> | null
  /** node id → real failure (error_type: message + traceback) from node_error events. */
  stepFailures?: Map<string, FailureView> | null
  /** Display name of another run (cache source) when it is in the loaded list. */
  runLabelFor?: (runId: string) => string | undefined
  onOpenRun?: (runId: string) => void
  runId: string
  runMeta?: Record<string, unknown> | null
  focusNodeId?: string | null
  onBrowseOutputs?: (nodeId?: string | null) => void
  /** Select a step in the pipeline stack (keeps Overview open). */
  onFocusStep?: (nodeId: string | null) => void
  outputFiles?: OutputFileHint[]
  /** Real inventory totals when the UI listing is sample-capped (e.g. Dataset Ingest). */
  fileTotalsByNode?: Record<string, number>
  graphEdges?: GraphEdge[] | null
  labelFor?: (nodeId: string) => string | undefined
  /** Same order as the left Pipeline stack. */
  orderedNodeIds?: string[]
  overview?: OverviewExtras | null
  /** Shape lane → path results (description + metrics) for fork/parallel maps. */
  lanePaths?: Map<string, PathResult> | null
  /** Node id → its path (for evaluator step stories). */
  nodePaths?: Map<string, PathResult> | null
  bestPathId?: string | null
  /** Parsed evaluator metrics.json per node (+ confusion matrix image paths). */
  evaluator?: EvaluatorOutputs | null
}) {
  const [trace, setTrace] = React.useState<TracePayload | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [fetchedEdges, setFetchedEdges] = React.useState<GraphEdge[] | null>(null)

  const parentEdgeKey = Array.isArray(graphEdges)
    ? normalizeEdges(graphEdges)
        .map((e) => `${e.src_id}>${e.dst_id}`)
        .join('|')
    : ''
  const parentEdges = React.useMemo(
    () => (Array.isArray(graphEdges) ? normalizeEdges(graphEdges) : []),
    // parentEdgeKey captures content; graphEdges identity alone would thrash fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [parentEdgeKey],
  )

  const load = React.useCallback(async () => {
    const rid = runId.trim()
    if (!rid) return
    setLoading(true)
    setError(null)
    try {
      const data = await apiJson<TracePayload>('/trace', { query: { run_id: rid } })
      setTrace(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setTrace(null)
    } finally {
      setLoading(false)
    }
  }, [runId])

  React.useEffect(() => {
    void load()
  }, [load])

  // Self-heal when parent didn't pass edges (embedded graph often has edges: []).
  React.useEffect(() => {
    const rid = runId.trim()
    if (!rid || parentEdges.length > 0) {
      setFetchedEdges(null)
      return
    }
    let cancelled = false
    void (async () => {
      const g = await fetchRunGraph(
        rid,
        trace?.run?.graph_name || trace?.graph?.name || null,
      ).catch(() => null)
      if (cancelled) return
      const edges = g && Array.isArray(g.edges) ? normalizeEdges(g.edges as GraphEdge[]) : []
      setFetchedEdges(edges.length ? edges : null)
    })()
    return () => {
      cancelled = true
    }
  }, [runId, parentEdges.length, trace?.run?.graph_name, trace?.graph?.name])

  const effectiveEdges = parentEdges.length > 0 ? parentEdges : fetchedEdges || []

  const stories = React.useMemo(() => {
    if (!trace && !(orderedNodeIds && orderedNodeIds.length)) return [] as StepStory[]
    return buildStories({
      chain: Array.isArray(trace?.chain) ? trace!.chain! : [],
      nodes: Array.isArray(trace?.lineage?.nodes) ? (trace!.lineage!.nodes as TraceNode[]) : [],
      files: outputFiles || [],
      edges: effectiveEdges,
      orderedNodeIds,
      labelFor,
      nodeStatsExtra: overview?.nodeStats,
      fileTotalsByNode,
    })
  }, [
    trace,
    outputFiles,
    effectiveEdges,
    labelFor,
    orderedNodeIds,
    overview?.nodeStats,
    fileTotalsByNode,
  ])

  const labelById = React.useMemo(() => {
    const m = new Map<string, string>()
    for (const s of stories) m.set(s.id, s.label)
    return m
  }, [stories])

  const focused = focusNodeId
    ? stories.find((s) => focusMatchesNode(focusNodeId, s.id)) || null
    : null

  const meta = runMeta && typeof runMeta === 'object' ? runMeta : {}
  const runStatus = String(trace?.run?.status || meta.status || 'unknown')
  const graphName = String(
    trace?.graph?.name || trace?.run?.graph_name || meta.graph_name || '',
  ).trim()
  const totalMs = stories.reduce((acc, s) => acc + (s.durationMs || 0), 0)
  const failed = stories.filter((s) => /fail|error/i.test(s.status))
  const cached = stories.filter((s) => s.cacheHit).length
  const shape = React.useMemo(
    () =>
      computePipelineShape(
        stories.map((s) => s.id),
        stories.some((s) => s.wired) ? effectiveEdges : null,
      ),
    [stories, effectiveEdges],
  )
  const edgesWired = stories.some((s) => s.wired)
  const multiTrack = isMultiTrackShape(shape)
  const sections = timelineSections(stories, shape, lanePaths)
  const hotSpots = [...stories]
    .filter((s) => s.durationMs != null && s.durationMs > 0)
    .sort((a, b) => (b.durationMs || 0) - (a.durationMs || 0))
    .slice(0, focusNodeId ? 3 : 5)
  const ov = overview || null
  const metrics = ov?.metrics && typeof ov.metrics === 'object' ? ov.metrics : null

  if (loading && !trace && stories.length === 0) {
    return <LoadingBlock label="Loading overview…" />
  }
  if (error && stories.length === 0) {
    return <ErrorBanner message={error} onRetry={() => void load()} />
  }
  if (stories.length === 0) {
    return (
      <EmptyState
        title="No steps recorded"
        description="This run has no node execution stats yet — check Logs if it failed early."
      />
    )
  }

  return (
    <div className="space-y-3">
      {/* Verdict + plain-language story */}
      <div className="rounded-xl border border-ink-200 bg-white px-3 py-2.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${statusTone(runStatus)}`}
              >
                {shortStatusLabel(runStatus)}
              </span>
              <span className="text-[13px] font-semibold text-ink-900">
                {stories.length} step{stories.length === 1 ? '' : 's'}
              </span>
              {totalMs > 0 ? (
                <span className="text-[12px] text-ink-500">· {formatDuration(totalMs)}</span>
              ) : null}
              {failed.length > 0 ? (
                <span className="text-[12px] font-medium text-rose-700">
                  · {failed.length} failed
                </span>
              ) : null}
              {cached > 0 ? (
                <span className="text-[12px] text-ink-400">· {cached} cached</span>
              ) : null}
            </div>
            {graphName ? (
              <p className="mt-1 text-[12px] font-medium text-ink-800">
                {humanizeTemplateName(graphName)}
              </p>
            ) : null}
            <RunStoryMap
              shape={shape}
              stories={stories}
              focusNodeId={focusNodeId}
              onFocusStep={onFocusStep}
              lanePaths={lanePaths}
              bestPathId={bestPathId}
              savedFiles={
                typeof (ov?.artifactCount ?? trace?.lineage?.artifact_count) === 'number'
                  ? Number(ov?.artifactCount ?? trace?.lineage?.artifact_count)
                  : null
              }
              provenance={
                typeof (ov?.provenanceCount ?? trace?.lineage?.provenance_count) === 'number'
                  ? Number(ov?.provenanceCount ?? trace?.lineage?.provenance_count)
                  : null
              }
            />
            {!edgesWired ? (
              <p className="mt-1 text-[11px] text-ink-400">
                Graph edges unavailable — showing pipeline order as the connection story.
              </p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {/* Files live on the Run outputs tab — no duplicate Browse here. */}
            <ReproPackButton runId={runId} />
            <button type="button" className="btn-quiet" aria-label="Refresh overview" onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Extra counts that are not folded into the map footer */}
      {ov && (Number(ov.checkpointCount || 0) > 0 || Number(ov.errorCount || 0) > 0) ? (
        <div className="flex flex-wrap gap-x-4 gap-y-1 rounded-xl border border-ink-100 bg-white px-3 py-2 text-[12px]">
          {(
            [
              ...(Number(ov.checkpointCount || 0) > 0
                ? ([['Checkpoints', ov.checkpointCount]] as Array<[string, unknown]>)
                : []),
              ...(Number(ov.errorCount || 0) > 0
                ? ([['Errors', ov.errorCount]] as Array<[string, unknown]>)
                : []),
            ] as Array<[string, unknown]>
          ).map(([label, val]) => (
            <div key={label} className="flex items-baseline gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                {label}
              </span>
              <span
                className={`tabular-nums font-semibold ${
                  label === 'Errors' ? 'text-rose-700' : 'text-ink-900'
                }`}
              >
                {String(val ?? 0)}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {metrics && Object.keys(scalarMetrics(metrics)).length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-ink-200">
          <div className="flex flex-wrap items-baseline gap-x-2 border-b border-ink-100 bg-ink-50 px-3 py-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Metrics</span>
            {ov?.metricsPathLabel ? (
              <span className="text-[11px] text-ink-600">
                · best path: <span className="font-semibold text-ink-800">{ov.metricsPathLabel}</span>
              </span>
            ) : null}
          </div>
          <ul className="divide-y divide-ink-100">
            {Object.entries(scalarMetrics(metrics))
              .slice(0, 12)
              .map(([k, v]) => (
                <li
                  key={k}
                  className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
                >
                  <span className="min-w-0 truncate font-medium text-ink-900" title={k}>
                    {metricLabel(k)}
                  </span>
                  <span className="shrink-0 tabular-nums text-[12px] font-semibold text-ink-800">
                    {Number.isInteger(v) && !isRatioMetric(k, v) ? v.toLocaleString() : formatMetricValue(k, v)}
                  </span>
                </li>
              ))}
          </ul>
          {ov?.otherPathMetrics && ov.otherPathMetrics.length > 0 ? (
            <div className="border-t border-ink-100 bg-ink-50/50 px-3 py-1.5 text-[11px] text-ink-500">
              Other paths:{' '}
              {ov.otherPathMetrics
                .map((o) => `${o.label} ${metricLabel(o.primary.name)} ${formatMetricValue(o.primary.name, o.primary.value)}`)
                .join(' · ')}
            </div>
          ) : null}
        </div>
      ) : null}

      {ov?.showRegisterCta && ov.onRegister ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-accent-200/70 bg-accent-50/40 px-3 py-2.5">
          <div className="min-w-0 text-[12px] text-ink-700">
            <span className="font-medium text-ink-900">Next: register a model</span>
            <span className="text-ink-500"> — name it in the registry so Models / Ship can use it.</span>
          </div>
          <button
            type="button"
            className="btn-secondary shrink-0 !px-2 !py-1 text-[11px]"
            onClick={ov.onRegister}
          >
            {ov.registerLabel || 'Register model'}
          </button>
        </div>
      ) : null}

      {Number(ov?.errorCount || 0) > 0 && ov?.onJumpLogs ? (
        <button type="button" className="btn-primary" onClick={ov.onJumpLogs}>
          Jump to errors
        </button>
      ) : null}

      {Array.isArray(ov?.recentErrors) && ov!.recentErrors!.length > 0 ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-rose-700">
            Recent errors
          </div>
          <ul className="mt-1 space-y-1 font-mono text-[11px] text-rose-900">
            {ov!.recentErrors!.slice(-5).map((e, i) => (
              <li key={i}>{humanizeErrorText(String(e.message || JSON.stringify(e)))}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {hotSpots.length > 0 ? (
        <details className="overflow-hidden rounded-xl border border-ink-200 bg-white">
          <summary className="cursor-pointer select-none border-b border-ink-100 bg-ink-50 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-500">
            Hot spots{' '}
            <span className="font-normal normal-case text-ink-400">
              — slowest steps (not pipeline order)
            </span>
          </summary>
          <ul className="divide-y divide-ink-100">
            {hotSpots.map((s) => (
              <li
                key={s.id}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <button
                  type="button"
                  className="min-w-0 truncate text-left font-medium text-ink-900 hover:text-accent-800"
                  onClick={() => onFocusStep?.(s.id)}
                >
                  {s.label}
                </button>
                <span className="shrink-0 tabular-nums text-[11px] text-ink-500">
                  {formatDuration(s.durationMs)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {Array.isArray(trace?.warnings) && trace!.warnings!.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {trace!.warnings!.map((w) => humanizeErrorText(String(w))).join(' · ')}
        </div>
      )}

      {focused ? (
        <StepDetailCard
          story={focused}
          evaluatorMetrics={evaluator?.metricsByNode[focused.id]}
          confusionImagePath={evaluator?.confusionImageByNode[focused.id]}
          path={nodePaths?.get(focused.id) ?? null}
          labelById={labelById}
          onBrowseOutputs={onBrowseOutputs}
          onClearFocus={onFocusStep ? () => onFocusStep(null) : undefined}
          cacheSourceRunId={cacheSources?.get(focused.id) ?? null}
          failure={stepFailures?.get(focused.id) ?? null}
          runLabelFor={runLabelFor}
          onOpenRun={onOpenRun}
        />
      ) : null}

      <div className="overflow-hidden rounded-xl border border-ink-200 bg-white">
        <div className="flex items-center justify-between gap-2 border-b border-ink-100 bg-ink-50/60 px-3 py-1.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">
            {focused
              ? 'Full timeline'
              : multiTrack
                ? 'What happened'
                : 'What happened (in order)'}
          </div>
          <span className="text-[11px] text-ink-400">Click a step for the full produce/consume story</span>
        </div>
        <div className="divide-y divide-ink-100">
          {sections.map((section) => (
            <div key={section.key}>
              {section.label ? (
                <div
                  className={`px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide ${laneToneClass(
                    section.key === 'rest' ? 'shared' : section.key,
                  )}`}
                >
                  {section.label}
                </div>
              ) : null}
              <ol className="divide-y divide-ink-50">
                {section.rows.map(({ story: s, execIndex }) => {
                  const active = focused ? focusMatchesNode(focused.id, s.id) : false
                  const fromLabels = s.from.map(
                    (id) => labelById.get(id) || displayNodeLabel(id, { withCue: true }),
                  )
                  const toLabels = s.to.map(
                    (id) => labelById.get(id) || displayNodeLabel(id, { withCue: true }),
                  )
                  return (
                    <li key={s.id}>
                      <button
                        type="button"
                        className={`flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors ${
                          active ? 'bg-accent-50/70' : 'hover:bg-ink-50/80'
                        }`}
                        onClick={() => onFocusStep?.(s.id)}
                      >
                        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink-100 text-[11px] font-semibold tabular-nums text-ink-700">
                          {execIndex}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-1.5">
                            <span className="text-[13px] font-medium text-ink-900">{s.label}</span>
                            <span
                              className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${statusTone(s.status)}`}
                            >
                              {shortStatusLabel(s.status)}
                            </span>
                            {s.cacheHit ? (
                              <span
                                className="rounded-full bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-800"
                                title={(() => {
                                  const src = cacheSources?.get(s.id)
                                  if (!src) return 'Reused cached outputs — source run not recorded'
                                  return `Reused outputs of run ${runLabelFor?.(src) || src} (${src})`
                                })()}
                              >
                                {cacheSources?.get(s.id) ? `cached · ${shortRunId(cacheSources.get(s.id)!)}` : 'cached'}
                              </span>
                            ) : null}
                            {(() => {
                              const pm = pickPrimaryMetric(evaluator?.metricsByNode[s.id])
                              return pm ? (
                                <span className="rounded-md bg-white px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-ink-800 ring-1 ring-ink-200">
                                  {metricLabel(pm.name)} {formatMetricValue(pm.name, pm.value)}
                                </span>
                              ) : null
                            })()}
                            <span className="ml-auto shrink-0 tabular-nums text-[11px] text-ink-500">
                              {formatDuration(s.durationMs)}
                            </span>
                          </span>
                          <span className="mt-0.5 block text-[12px] text-ink-700">
                            <span className="text-ink-400">Wrote </span>
                            {s.wrote}
                          </span>
                          <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-ink-500">
                            {fromLabels.length > 0 ? (
                              <span>
                                <span className="text-ink-400">Fed by </span>
                                {fromLabels.join(', ')}
                              </span>
                            ) : (
                              <span className="text-ink-400">Start</span>
                            )}
                            {toLabels.length > 0 ? (
                              <>
                                <ArrowRight className="inline h-3 w-3 shrink-0 text-ink-300" aria-hidden />
                                <span>
                                  <span className="text-ink-400">feeds </span>
                                  {toLabels.join(', ')}
                                </span>
                              </>
                            ) : (
                              <>
                                <ArrowRight className="inline h-3 w-3 shrink-0 text-ink-300" aria-hidden />
                                <span className="text-ink-400">End</span>
                              </>
                            )}
                          </span>
                          {s.error || stepFailures?.get(s.id) ? (
                            <span className="mt-1 block truncate font-mono text-[11px] text-rose-700" title={stepFailures?.get(s.id)?.headline || s.error || undefined}>
                              {stepFailures?.get(s.id)?.headline || failureView({ error: s.error })?.headline || s.error}
                            </span>
                          ) : null}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ol>
            </div>
          ))}
        </div>
      </div>

      {(trace?.lineage?.artifacts || []).length > 0 ? (
        <details className="rounded-lg border border-ink-100 bg-ink-50/40">
          <summary className="cursor-pointer select-none px-3 py-1.5 text-[11px] font-medium text-ink-500">
            Advanced — registry IDs (support)
          </summary>
          <ul className="max-h-36 space-y-1 overflow-y-auto border-t border-ink-100 px-3 py-2">
            {(trace?.lineage?.artifacts || []).slice(0, 16).map((a, i) => (
              <li key={String(a.artifact_id || i)} className="text-[11px] text-ink-600">
                <span className="font-medium text-ink-800" title={a.node_id ? String(a.node_id) : undefined}>
                  {a.node_id
                    ? labelById.get(String(a.node_id)) ||
                      labelFor?.(String(a.node_id)) ||
                      displayNodeLabel(String(a.node_id), { withCue: true })
                    : 'Output'}
                </span>
                {a.artifact_id ? (
                  <span className="ml-2 inline-block align-middle">
                    <CopyableMono value={String(a.artifact_id)} />
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  )
}

function StepDetailCard({
  story,
  labelById,
  onBrowseOutputs,
  onClearFocus,
  evaluatorMetrics,
  confusionImagePath,
  path,
  cacheSourceRunId,
  failure,
  runLabelFor,
  onOpenRun,
}: {
  cacheSourceRunId?: string | null
  failure?: FailureView | null
  runLabelFor?: (runId: string) => string | undefined
  onOpenRun?: (runId: string) => void
  evaluatorMetrics?: unknown
  confusionImagePath?: string
  path?: PathResult | null
  story: StepStory
  labelById: Map<string, string>
  onBrowseOutputs?: (nodeId?: string | null) => void
  onClearFocus?: () => void
}) {
  const name = (id: string) => labelById.get(id) || displayNodeLabel(id, { withCue: true })
  return (
    <div className="rounded-xl border border-accent-200/80 bg-accent-50/30 px-3 py-2.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">
            Step story
          </div>
          <div className="mt-0.5 text-[15px] font-semibold text-ink-900">{story.label}</div>
        </div>
        {onClearFocus ? (
          <button type="button" className="btn-quiet !px-1.5 !py-0.5 text-[11px]" onClick={onClearFocus}>
            Show all steps
          </button>
        ) : null}
      </div>
      <dl className="mt-2 grid gap-1.5 text-[12px] sm:grid-cols-2">
        <div>
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">Status</dt>
          <dd className="mt-0.5">
            <span className={`rounded-full px-1.5 py-0.5 text-[11px] font-semibold ${statusTone(story.status)}`}>
              {shortStatusLabel(story.status)}
            </span>
            {story.cacheHit ? <span className="ml-1.5 text-ink-500">· used cache</span> : null}
            <span className="ml-1.5 text-ink-500">· {formatDuration(story.durationMs)}</span>
            {story.cacheHit ? (
              <span className="mt-0.5 block text-[11px] text-ink-500">
                {linkableRunId(cacheSourceRunId) ? (
                  <>
                    from run{' '}
                    <span className="font-medium text-ink-800" title={cacheSourceRunId!}>
                      {runLabelFor?.(cacheSourceRunId!) || shortRunId(cacheSourceRunId!)}
                    </span>
                    {runLabelFor?.(cacheSourceRunId!) ? (
                      <span className="font-mono text-ink-400"> {shortRunId(cacheSourceRunId!)}</span>
                    ) : null}
                    {onOpenRun ? (
                      <>
                        {' '}
                        (
                        <button
                          type="button"
                          className="text-accent-800 underline-offset-2 hover:underline"
                          onClick={() => onOpenRun(cacheSourceRunId!)}
                        >
                          open
                        </button>
                        )
                      </>
                    ) : null}
                  </>
                ) : (
                  <span className="text-ink-400">source run not recorded</span>
                )}
              </span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">Wrote</dt>
          <dd className="mt-0.5 text-ink-800">{story.wrote}</dd>
        </div>
        <div>
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">Received from</dt>
          <dd className="mt-0.5 text-ink-800">
            {story.from.length
              ? story.from.map(name).join(', ')
              : 'Start of the pipeline (or external input)'}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">Sent to</dt>
          <dd className="mt-0.5 text-ink-800">
            {story.to.length ? story.to.map(name).join(', ') : 'End of this path'}
          </dd>
        </div>
      </dl>
      {failure || story.error ? (
        <div className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-2 py-1.5">
          {(() => {
            const fv = failure || failureView({ error: story.error })
            return fv ? <FailureDetails failure={fv} /> : null
          })()}
        </div>
      ) : null}
      {evaluatorMetrics != null || confusionImagePath ? (
        <EvaluatorResult metrics={evaluatorMetrics} confusionImagePath={confusionImagePath} path={path} />
      ) : null}
      {onBrowseOutputs ? (
        <div className="mt-2">
          <button
            type="button"
            className="btn-secondary !px-2.5 !py-1 text-[12px]"
            onClick={() => onBrowseOutputs(story.id)}
          >
            Open this step’s files
          </button>
        </div>
      ) : null}
    </div>
  )
}
