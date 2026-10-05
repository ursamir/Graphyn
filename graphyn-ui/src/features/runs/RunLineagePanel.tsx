/**
 * Run Overview body (below the results banner), top to bottom:
 *   summary line → path comparison table (multi-path) or compact metrics row →
 *   "What happened" (ML multi-path runs: steps grouped Shared / Path X, numbered
 *   within each group; workflow runs (`pathGrouping={false}`): one ordered list
 *   with branch context, skip reasons and handled errors; click a step to focus
 *   it) → Hot spots (fold) → Run record (collapsed slot) →
 *   registry ids (fold). File downloads live in Run outputs.
 */
import React from 'react'
import clsx from 'clsx'
import { ChevronDown, ChevronRight, RefreshCw, Trophy, X } from 'lucide-react'
import { apiJson } from '../../api/client'
import { CopyableMono, EmptyState, ErrorBanner, LoadingBlock } from '../../components/ui'
import { ReproPackButton } from '../../components/ReproPackButton'
import { displayNodeLabel, focusMatchesNode, humanizeTemplateName, shortRunId } from '../../lib/format'
import { fetchRunGraph } from '../../lib/runGraph'
import { computePipelineShape, isMultiTrackShape } from './runNodes'
import { formatMetricValue, metricLabel, pickPrimaryMetric } from '../../lib/metrics'
import { scalarMetrics, type PathResult } from './runResults'
import { BlobImage, EvaluatorResult } from './RunResults'
import type { EvaluatorOutputs } from './useRunResults'
import { failureView, linkableRunId, type FailureView } from './runRecord'
import { FailureDetails } from './FailureDetails'
import { humanizeErrorText } from '../../lib/errorText'
import {
  formatStepDuration,
  friendlyArtifactName,
  groupStepsByLane,
  pathTableColumns,
  pathTablePrimaryName,
  pathTableRows,
  pathTiming,
} from './runOverview'
import { CompactMetricsRow, PathComparisonTable } from './RunOverviewParts'
import {
  defaultOpenGroups,
  imageOutputsForNode,
  pathGroupSummary,
  stepConfigEntries,
  trackedFilesLabel,
  type ConfigEntry,
} from './stepDetails'
import { resilienceText, type StepResilience } from './runWorkflow'
import {
  handledErrorNodes,
  handledErrorText,
  handledErrorsLabel,
  skipReasonText,
  splitRunErrors,
  type StepName,
} from './runFlow'

function shortStatusLabel(status?: string | null): string {
  const s = String(status || '').toLowerCase()
  if (s === 'succeeded' || s === 'success' || s === 'completed' || s === 'done') return 'Done'
  if (s === 'failed' || s === 'error') return 'Failed'
  if (s === 'cancelled' || s === 'canceled') return 'Cancelled'
  if (s === 'running') return 'Running'
  if (s === 'queued') return 'Queued'
  if (s === 'paused') return 'Paused'
  if (s === 'skipped') return 'Skipped'
  if (s === 'awaiting_approval') return 'Awaiting approval'
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
  /** Real file names when `wrote` shows friendly names ('' otherwise). */
  wroteRaw: string
  fileCount: number
  from: string[]
  to: string[]
  /** Edges came from graph IR (true) vs sequential fallback (false). */
  wired: boolean
}

const formatDuration = formatStepDuration

function statusTone(status: string): string {
  const s = status.toLowerCase()
  if (s === 'failed' || s === 'error') return 'bg-rose-100 text-rose-900'
  if (s === 'cancelled' || s === 'canceled') return 'bg-ink-100 text-ink-700'
  if (s === 'running' || s === 'queued' || s === 'paused') return 'bg-amber-100 text-amber-950'
  if (s === 'awaiting_approval') return 'bg-violet-100 text-violet-900'
  return ''
}

/** Success / unknown read as plain text; only exceptions get a coloured badge. */
function isExceptionStatus(status: string): boolean {
  return statusTone(status) !== ''
}

function summarizeWrote(
  files: OutputFileHint[],
  opts?: { inventoryTotal?: number | null },
): { text: string; count: number; raw: string } {
  const inventoryTotal = opts?.inventoryTotal
  // Match Run outputs empty copy — “nothing listed” sounded like a bug.
  if (!files.length && !(inventoryTotal && inventoryTotal > 0)) {
    return { text: 'no files (data stayed in memory)', count: 0, raw: '' }
  }
  const names = files.map((f) => String(f.name || f.path?.split('/').pop() || '').trim()).filter(Boolean)
  const audioish = names.filter((n) => /\.(wav|flac|mp3|ogg)$/i.test(n)).length
  const total =
    typeof inventoryTotal === 'number' && inventoryTotal > names.length
      ? inventoryTotal
      : names.length
  // Prefer inventory total — UI listing caps large dumps at ~32 samples.
  // Domain-generic wording: "audio clips" only when extensions clearly dominate.
  if (total >= 6 && names.length > 0 && audioish >= names.length * 0.6) {
    return { text: `${total.toLocaleString()} audio clips`, count: total, raw: names.slice(0, 8).join(', ') }
  }
  if (total >= 6 && names.length === 0) {
    return { text: `${total.toLocaleString()} files`, count: total, raw: '' }
  }
  if (!names.length) {
    return { text: `${total.toLocaleString()} files`, count: total, raw: '' }
  }
  const models = names.filter((n) => /\.(keras|h5|tflite|onnx|pb|pt|pth)$/i.test(n) || /model/i.test(n))
  const metrics = names.filter((n) => /metrics|confusion|roc|label/i.test(n) || /\.json$/i.test(n))
  const pick = [...new Set([...models, ...metrics, ...names])].filter(Boolean)
  const shown = pick.slice(0, 3)
  const listedExtra = pick.length - shown.length
  const hidden = Math.max(0, total - names.length)
  const more = listedExtra + hidden
  // Internal names (compiled_<hex>.keras) read as "Untrained model (architecture)";
  // the raw names stay in the tooltip.
  const friendly = shown.map((n) => friendlyArtifactName(n).label)
  return {
    text: friendly.join(', ') + (more > 0 ? ` +${more.toLocaleString()} more` : ''),
    count: total,
    raw: shown.some((n, i) => friendly[i] !== n) ? shown.join(', ') : '',
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
      wroteRaw: wrote.raw,
      fileCount: wrote.count,
      from: [...new Set(fromMap.get(id) || [])],
      to: [...new Set(toMap.get(id) || [])],
      wired,
    }
  })
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

export type StepLogLine = { key: string; clock: string; text: string; failed: boolean }

/**
 * Scroll `el` into view inside its nearest scrolling ancestor only — never the
 * document (scrollIntoView would also move the app shell when it overflows).
 */
function scrollIntoPane(el: HTMLElement | null) {
  if (!el) return
  let p = el.parentElement
  while (p) {
    const oy = getComputedStyle(p).overflowY
    if ((oy === 'auto' || oy === 'scroll') && p.scrollHeight > p.clientHeight) break
    p = p.parentElement
  }
  if (!p) return
  const pr = p.getBoundingClientRect()
  const er = el.getBoundingClientRect()
  const margin = 8
  if (er.top < pr.top + margin) p.scrollTop += er.top - pr.top - margin
  else if (er.bottom > pr.bottom - margin) {
    // Taller than the pane: align the row's top instead of its bottom.
    p.scrollTop += Math.min(er.bottom - pr.bottom + margin, er.top - pr.top - margin)
  }
}

export type OverviewExtras = {
  artifactCount?: number
  provenanceCount?: number
  checkpointCount?: number
  errorCount?: number
  metrics?: Record<string, unknown> | null
  /** "Path C (DS-CNN · 30 epochs)" when `metrics` are the best path's (multi-path runs). */
  metricsPathLabel?: string | null
  /** Other paths' headline metric, shown under the metrics row for context. */
  otherPathMetrics?: Array<{ label: string; primary: { name: string; value: number } }>
  recentErrors?: Array<Record<string, unknown>>
  showRegisterCta?: boolean
  registerLabel?: string
  onRegister?: () => void
  onJumpLogs?: () => void
  /** Raw node_stats rows for duration enrichment + hot spots. */
  nodeStats?: Array<Record<string, unknown>>
}

/** Run Overview — summary, path table / metrics, step story, hot spots, record. */
export function RunLineagePanel({
  runId,
  liveStatus,
  pathGrouping,
  stepNames,
  branchContext,
  skipReasons,
  stepStatuses,
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
  paths,
  lanePaths,
  nodePaths,
  bestPathId,
  evaluator,
  cacheSources,
  stepFailures,
  runLabelFor,
  onOpenRun,
  recordSlot,
  topSlot,
  stepResilience,
  graphNodes,
  schemaFor,
  stepLogs,
  onOpenLogs,
  onOpenFile,
  narrow = false,
}: {
  /** Live run status (status poll, incl. the awaiting_approval overlay) — wins over the trace snapshot. */
  liveStatus?: string | null
  /** false → workflow run: one ordered step list, no Path groups / Paths compared. Default: follow the graph shape. */
  pathGrouping?: boolean
  /** Workflow step names (title + type secondary text); null on ML runs. */
  stepNames?: Map<string, StepName> | null
  /** node id → "check → true" (branch the step hangs off). */
  branchContext?: Map<string, string> | null
  /** node id → raw node_skip reason. */
  skipReasons?: Map<string, string> | null
  /** node id → status from the journal (fills steps the trace has no status for, e.g. skipped). */
  stepStatuses?: Map<string, string> | null
  /** Graph snapshot nodes — the config each step ran with. */
  graphNodes?: Array<{ id?: unknown; node_type?: unknown; config?: unknown }> | null
  /** Node catalog config schema for a node type (defaults → "changed" highlight). */
  schemaFor?: (nodeType: string) => { properties?: Record<string, Record<string, unknown>> } | null | undefined
  /** Last formatted log lines of one step (+ total matching). */
  stepLogs?: (nodeId: string) => { lines: StepLogLine[]; total: number }
  /** Open Logs focused on this step. */
  onOpenLogs?: (nodeId: string) => void
  /** Open one output file in Run outputs. */
  onOpenFile?: (path: string, nodeId: string) => void
  /** Detail pane narrower than ~700 px: path table renders as stacked cards. */
  narrow?: boolean
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
  /** Focus a step (null = All). Keeps Overview open. */
  onFocusStep?: (nodeId: string | null) => void
  outputFiles?: OutputFileHint[]
  /** Real inventory totals when the UI listing is sample-capped (e.g. Dataset Ingest). */
  fileTotalsByNode?: Record<string, number>
  graphEdges?: GraphEdge[] | null
  labelFor?: (nodeId: string) => string | undefined
  /** Execution order of the run's steps. */
  orderedNodeIds?: string[]
  overview?: OverviewExtras | null
  /** Every path result (multi-path comparison table). */
  paths?: PathResult[] | null
  /** Shape lane → path results (description + metrics) for fork/parallel runs. */
  lanePaths?: Map<string, PathResult> | null
  /** Node id → its path (for evaluator step stories). */
  nodePaths?: Map<string, PathResult> | null
  bestPathId?: string | null
  /** Parsed evaluator metrics.json per node (+ confusion matrix image paths). */
  evaluator?: EvaluatorOutputs | null
  /** Run record card (collapsed summary) rendered after Hot spots. */
  recordSlot?: React.ReactNode
  /** Rendered above the summary line (pending approval cards). */
  topSlot?: React.ReactNode
  /** node id → retries / routed error / continued failure (journal events). */
  stepResilience?: Map<string, StepResilience> | null
}) {
  const [trace, setTrace] = React.useState<TracePayload | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [fetchedEdges, setFetchedEdges] = React.useState<GraphEdge[] | null>(null)
  /** null = not needed / not started; true = in flight; false = settled (may be empty). */
  const [edgesFetchPending, setEdgesFetchPending] = React.useState<boolean | null>(null)

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
      setEdgesFetchPending(null)
      return
    }
    let cancelled = false
    setEdgesFetchPending(true)
    void (async () => {
      const g = await fetchRunGraph(
        rid,
        trace?.run?.graph_name || trace?.graph?.name || null,
      ).catch(() => null)
      if (cancelled) return
      const edges = g && Array.isArray(g.edges) ? normalizeEdges(g.edges as GraphEdge[]) : []
      setFetchedEdges(edges.length ? edges : null)
      setEdgesFetchPending(false)
    })()
    return () => {
      cancelled = true
    }
  }, [runId, parentEdges.length, trace?.run?.graph_name, trace?.graph?.name])

  const effectiveEdges = React.useMemo(
    () => (parentEdges.length > 0 ? parentEdges : fetchedEdges || []),
    [parentEdges, fetchedEdges],
  )

  const stories = React.useMemo(() => {
    if (!trace && !(orderedNodeIds && orderedNodeIds.length)) return [] as StepStory[]
    const built = buildStories({
      chain: Array.isArray(trace?.chain) ? trace!.chain! : [],
      nodes: Array.isArray(trace?.lineage?.nodes) ? (trace!.lineage!.nodes as TraceNode[]) : [],
      files: outputFiles || [],
      edges: effectiveEdges,
      orderedNodeIds,
      labelFor,
      nodeStatsExtra: overview?.nodeStats,
      fileTotalsByNode,
    })
    // Steps the trace never saw (skipped branches) take the journal status.
    return built.map((st) => {
      const j = stepStatuses?.get(st.id)
      return j && (st.status === 'unknown' || !st.status) ? { ...st, status: j } : st
    })
  }, [
    stepStatuses,
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
  const runStatus = String(liveStatus && liveStatus !== 'unknown' ? liveStatus : trace?.run?.status || meta.status || 'unknown')
  const graphName = String(
    trace?.graph?.name || trace?.run?.graph_name || meta.graph_name || '',
  ).trim()
  const totalMs = stories.reduce((acc, s) => acc + (s.durationMs || 0), 0)
  /** Failures routed to an error branch / continued — handled, not run errors. */
  const handledIds = handledErrorNodes(stepResilience)
  const failed = stories.filter((s) => /fail|error/i.test(s.status) && !handledIds.has(s.id))
  const flowMode = pathGrouping === false
  const cached = stories.filter((s) => s.cacheHit).length
  const shape = React.useMemo(
    () =>
      computePipelineShape(
        stories.map((s) => s.id),
        stories.some((s) => s.wired) && !flowMode ? effectiveEdges : null,
      ),
    [stories, effectiveEdges, flowMode],
  )
  const edgesWired = stories.some((s) => s.wired)
  /** Only warn after the edge self-heal settles empty — never flash while loading. */
  const showEdgesUnavailable =
    !edgesWired && edgesFetchPending === false && parentEdges.length === 0
  const multiTrack = isMultiTrackShape(shape)
  const groups = groupStepsByLane(stories, (s) => s.id, shape, lanePaths)
  const GATE_TYPE_RE = /hitl_approve|human_approval|approval_gate/i
  const hotSpots = [...stories]
    .filter((s) => s.durationMs != null && s.durationMs > 0)
    .filter(
      (s) =>
        !GATE_TYPE_RE.test(s.nodeType || '') &&
        !/awaiting_approval|waiting_approval/i.test(s.status || ''),
    )
    .sort((a, b) => (b.durationMs || 0) - (a.durationMs || 0))
    .slice(0, 5)
  const ov = overview || null
  const metrics = ov?.metrics && typeof ov.metrics === 'object' ? scalarMetrics(ov.metrics) : {}
  const savedFiles =
    typeof (ov?.artifactCount ?? trace?.lineage?.artifact_count) === 'number'
      ? Number(ov?.artifactCount ?? trace?.lineage?.artifact_count)
      : null
  const provenance =
    typeof (ov?.provenanceCount ?? trace?.lineage?.provenance_count) === 'number'
      ? Number(ov?.provenanceCount ?? trace?.lineage?.provenance_count)
      : null

  // ── Path comparison table (multi-path runs) ──
  const allPaths = (paths || []).filter(Boolean)
  const showPathTable = multiTrack && allPaths.length > 1
  const storyById = React.useMemo(() => new Map(stories.map((s) => [s.id, s])), [stories])
  const laneIdsOf = (p: PathResult): string[] => {
    for (const [lane, lp] of lanePaths || []) {
      if (lp.pathId !== p.pathId || lane === 'shared') continue
      const idx = lane.charCodeAt(0) - 65
      if (shape.branches[idx]) return shape.branches[idx]
    }
    return p.nodeIds
  }
  const tablePrimary = pathTablePrimaryName(allPaths, bestPathId)
  const tableColumns = pathTableColumns(allPaths, tablePrimary)
  const tableRows = showPathTable
    ? pathTableRows({
        paths: allPaths,
        bestPathId,
        columns: tableColumns,
        primaryName: tablePrimary,
        timingOf: (p) =>
          pathTiming(
            laneIdsOf(p),
            (id) => storyById.get(id)?.durationMs ?? null,
            (id) => storyById.get(id)?.nodeType ?? null,
          ),
      })
    : []
  const focusedPathLetter = focused ? nodePaths?.get(focused.id)?.letter ?? null : null
  const linearGot = !multiTrack ? linearOutcome(stories) : null

  // ── Collapsible groups: Shared open; best (or failed) path open; others folded ──
  const bestLane = React.useMemo(() => {
    if (!bestPathId) return null
    for (const [lane, lp] of lanePaths || []) if (lane !== 'shared' && lp.pathId === bestPathId) return lane
    return null
  }, [lanePaths, bestPathId])
  const groupKeys = groups.map((g) => g.key)
  const failedLanes = multiTrack ? [...new Set(failed.map((s) => shape.laneOf.get(s.id) || 'shared'))] : []
  const focusLane = focused ? (multiTrack ? shape.laneOf.get(focused.id) || 'shared' : groupKeys[0] ?? null) : null
  const groupSig = `${runId}|${groupKeys.join(',')}|${bestLane || ''}|${failedLanes.join(',')}`
  const [openGroups, setOpenGroups] = React.useState<{ sig: string; open: Set<string> } | null>(null)
  const openSet =
    openGroups && openGroups.sig === groupSig
      ? openGroups.open
      : defaultOpenGroups({ keys: groupKeys, bestLane, failedLanes })
  const toggleGroup = (key: string) => {
    const next = new Set(openSet)
    const isOpen = next.has(key) || key === focusLane
    if (isOpen) {
      next.delete(key)
      if (key === focusLane) onFocusStep?.(null)
    } else next.add(key)
    setOpenGroups({ sig: groupSig, open: next })
  }

  // ── Inline step details: scroll into view; Esc closes and returns focus ──
  const focusedRowRef = React.useRef<HTMLLIElement | null>(null)
  const focusedId = focused?.id ?? null
  React.useEffect(() => {
    if (!focusedId) return
    const raf = requestAnimationFrame(() => scrollIntoPane(focusedRowRef.current))
    return () => cancelAnimationFrame(raf)
  }, [focusedId])
  React.useEffect(() => {
    if (!focusedId || !onFocusStep) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      if (document.querySelector('[aria-modal="true"]')) return
      const t = e.target as HTMLElement | null
      if (t?.closest('input, textarea, select, [contenteditable="true"], details[open]')) return
      const btn = focusedRowRef.current?.querySelector<HTMLButtonElement>('button[data-step-row]')
      onFocusStep(null)
      btn?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [focusedId, onFocusStep])

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

  const errorSplit = splitRunErrors({
    errorCount: ov?.errorCount ?? null,
    recentErrors: ov?.recentErrors ?? null,
    handled: handledIds,
  })
  const runTone = statusTone(runStatus)
  const summaryBits: React.ReactNode[] = []
  summaryBits.push(
    <span key="steps">
      {stories.length} step{stories.length === 1 ? '' : 's'}
    </span>,
  )
  if (totalMs > 0) summaryBits.push(<span key="time">{formatDuration(totalMs)}</span>)
  if (failed.length > 0)
    summaryBits.push(
      <span key="failed" className="font-medium text-rose-700">
        {failed.length} failed
      </span>,
    )
  if (cached > 0) summaryBits.push(<span key="cached">{cached} cached</span>)
  if (savedFiles != null) summaryBits.push(<span key="files">{savedFiles} saved files</span>)
  const tracked = trackedFilesLabel(provenance)
  if (tracked)
    summaryBits.push(
      <span key="prov" title="Files whose content hash is recorded for this run — Verify re-checks them">
        {tracked}
      </span>,
    )
  if (Number(ov?.checkpointCount || 0) > 0)
    summaryBits.push(<span key="ckpt">{Number(ov?.checkpointCount)} checkpoints</span>)
  if (errorSplit.unhandledCount > 0)
    summaryBits.push(
      <span key="errs" className="font-medium text-rose-700">
        {errorSplit.unhandledCount} error{errorSplit.unhandledCount === 1 ? '' : 's'}
      </span>,
    )
  if (errorSplit.handledCount > 0)
    summaryBits.push(
      <span key="handled" className="font-medium text-amber-800" title="Failures routed to an error branch or continued (on_error) — the run kept going">
        {handledErrorsLabel(errorSplit.handledCount)}
      </span>,
    )

  return (
    <div className="space-y-2">
      {topSlot}
      {/* Summary line: plain text for success; badge only for exceptions. */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-0.5 text-[12px] text-ink-600">
        {runTone ? (
          <span className={clsx('rounded-full px-2 py-0.5 text-[11px] font-semibold', runTone)}>
            {shortStatusLabel(runStatus)}
          </span>
        ) : (
          <span className="font-medium text-ink-800">{shortStatusLabel(runStatus)}</span>
        )}
        {summaryBits.map((b, i) => (
          <React.Fragment key={i}>
            <span className="text-ink-300" aria-hidden>
              ·
            </span>
            {b}
          </React.Fragment>
        ))}
        {graphName ? (
          <span className="min-w-0 truncate text-ink-400" title={`Pipeline ${graphName}`}>
            · {humanizeTemplateName(graphName)}
          </span>
        ) : null}
        <span className="ml-auto flex shrink-0 items-center gap-1">
          {/* Files live on the Run outputs tab — no duplicate Browse here. */}
          <ReproPackButton runId={runId} />
          <button type="button" className="btn-quiet" aria-label="Refresh overview" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>
      {linearGot ? (
        <p className="-mt-1 px-0.5 text-[12px] text-ink-600">
          <span className="text-ink-400">Got </span>
          {linearGot}
        </p>
      ) : null}
      {!showEdgesUnavailable ? null : (
        <p className="-mt-1 px-0.5 text-[11px] text-ink-400">
          Graph edges unavailable — showing pipeline order as the connection story.
        </p>
      )}

      {showPathTable ? (
        <PathComparisonTable
          rows={tableRows}
          primaryName={tablePrimary}
          columns={tableColumns}
          activeLetter={focusedPathLetter}
          stacked={narrow}
          onSelect={(r) => {
            if (r.focusNodeId) onFocusStep?.(r.focusNodeId)
          }}
        />
      ) : Object.keys(metrics).length > 0 ? (
        <div>
          <CompactMetricsRow
            metrics={metrics}
            caption={ov?.metricsPathLabel ? `best path: ${ov.metricsPathLabel}` : null}
          />
          {ov?.otherPathMetrics && ov.otherPathMetrics.length > 0 ? (
            <p className="mt-1 px-0.5 text-[11px] text-ink-500">
              Other paths:{' '}
              {ov.otherPathMetrics
                .map((o) => `${o.label} ${metricLabel(o.primary.name)} ${formatMetricValue(o.primary.name, o.primary.value)}`)
                .join(' · ')}
            </p>
          ) : null}
        </div>
      ) : null}

      {ov?.showRegisterCta && ov.onRegister ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-ink-200 bg-white px-3 py-2">
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

      {errorSplit.unhandledRecent.length > 0 ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-[12px] font-semibold text-rose-800">Recent errors</h3>
            {errorSplit.unhandledCount > 0 && ov?.onJumpLogs ? (
              <button type="button" className="btn-secondary !px-2 !py-0.5 text-[11px]" onClick={ov.onJumpLogs}>
                Jump to errors
              </button>
            ) : null}
          </div>
          <ul className="mt-1 space-y-1 font-mono text-[11px] text-rose-900">
            {errorSplit.unhandledRecent.slice(-5).map((e, i) => (
              <li key={i}>{humanizeErrorText(String(e.message || JSON.stringify(e)))}</li>
            ))}
          </ul>
        </div>
      ) : errorSplit.unhandledCount > 0 && ov?.onJumpLogs ? (
        <button type="button" className="btn-secondary !px-2 !py-1 text-[11px]" onClick={ov.onJumpLogs}>
          Jump to errors
        </button>
      ) : null}
      {errorSplit.handledCount > 0 ? (
        <p className="px-0.5 text-[12px] text-amber-900">
          <span className="font-semibold">Handled errors</span>
          <span className="text-amber-800">
            {' — '}
            {[...handledIds]
              .map((id) => `${labelById.get(id) || id}: ${handledErrorText(stepResilience?.get(id)).replace(/^Failed → /, '')}`)
              .join(' · ')}
          </span>
        </p>
      ) : null}

      {Array.isArray(trace?.warnings) && trace!.warnings!.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
          {trace!.warnings!.map((w) => humanizeErrorText(String(w))).join(' · ')}
        </div>
      )}

      <section aria-label="What happened" className="overflow-hidden rounded-xl border border-ink-200 bg-white">
        <div className="flex items-baseline justify-between gap-2 border-b border-ink-100 px-3 py-1.5">
          <h3 className="shrink-0 text-[13px] font-semibold text-ink-900">What happened</h3>
          <span className="min-w-0 truncate text-[11px] text-ink-400">
            {focused ? 'Esc closes step details' : 'Click a step for its details'}
          </span>
        </div>
        <div className="divide-y divide-ink-100">
          {groups.map((group) => {
            const isPathLane = /^[A-Z]$/.test(group.key)
            const open = openSet.has(group.key) || group.key === focusLane
            const lanePath = isPathLane ? lanePaths?.get(group.key) ?? null : null
            const groupMs = group.rows.reduce((a, r) => a + (r.item.durationMs || 0), 0)
            const groupFailed = group.rows.some((r) => /fail|error/i.test(r.item.status))
            const parts = isPathLane
              ? pathGroupSummary({
                  letter: lanePath?.letter ?? group.key,
                  description: lanePath?.description,
                  stepCount: group.rows.length,
                  totalMs: groupMs,
                  primary: lanePath?.primary ?? null,
                })
              : [
                  group.key === 'shared' ? 'Shared steps' : group.label || 'Steps',
                  `${group.rows.length} step${group.rows.length === 1 ? '' : 's'}`,
                  ...(groupMs > 0 ? [formatDuration(groupMs)] : []),
                ]
            const isBestLane = Boolean(isPathLane && bestLane === group.key && allPaths.length > 1)
            return (
              <div key={group.key}>
                {group.label ? (
                  <button
                    type="button"
                    aria-expanded={open}
                    className="flex w-full min-w-0 items-center gap-1.5 bg-ink-50/60 px-3 py-1.5 text-left text-[12px] hover:bg-ink-100/60"
                    title={parts.join(' · ')}
                    onClick={() => toggleGroup(group.key)}
                  >
                    {open ? (
                      <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ink-400" aria-hidden />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ink-400" aria-hidden />
                    )}
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-medium text-ink-900">{parts[0]}</span>
                      <span className="text-ink-500"> · {parts.slice(1).join(' · ')}</span>
                    </span>
                    {groupFailed ? (
                      <span className="shrink-0 rounded-full bg-rose-100 px-1.5 py-0.5 text-[10px] font-semibold text-rose-900">
                        Failed
                      </span>
                    ) : null}
                    {isBestLane ? (
                      <span className="inline-flex shrink-0 items-center gap-0.5 text-[11px] font-medium text-emerald-700">
                        <Trophy className="h-3 w-3" aria-hidden /> best
                      </span>
                    ) : null}
                  </button>
                ) : null}
                {open ? (
                  <ol className="divide-y divide-ink-50">
                    {group.rows.map(({ item: s, index }) => {
                      const active = focused ? focusMatchesNode(focused.id, s.id) : false
                      const tone = statusTone(s.status)
                      const label = multiTrack ? s.label.replace(/\s·\sPath [A-Z]$/, '') : s.label
                      const name = stepNames?.get(s.id) ?? null
                      const title = name?.title || label
                      const skipped = /skip/i.test(s.status)
                      const handledText = handledErrorText(stepResilience?.get(s.id))
                      const branch = branchContext?.get(s.id) ?? ''
                      const skipText = skipped && skipReasons?.get(s.id) != null ? skipReasonText(skipReasons.get(s.id)) : ''
                      const pm = pickPrimaryMetric(evaluator?.metricsByNode[s.id])
                      const cacheSrc = cacheSources?.get(s.id)
                      const failureLine =
                        stepFailures?.get(s.id)?.headline || (s.error ? failureView({ error: s.error })?.headline || s.error : null)
                      const node = (graphNodes || []).find((n) => String(n?.id ?? '') === s.id) || null
                      const nodeType = String(node?.node_type || s.nodeType || '')
                      return (
                        <li key={s.id} ref={active ? focusedRowRef : undefined}>
                          <button
                            type="button"
                            data-step-row
                            aria-expanded={active}
                            className={clsx(
                              'flex w-full min-w-0 items-center gap-2 px-3 py-1.5 text-left transition-colors',
                              active ? 'bg-accent-50/70' : 'hover:bg-ink-50/80',
                              skipped && !active && 'opacity-70',
                            )}
                            onClick={() => onFocusStep?.(active ? null : s.id)}
                            title={active ? 'Hide step details' : 'Show step details'}
                          >
                            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-ink-100 text-[10px] font-semibold tabular-nums text-ink-600">
                              {index}
                            </span>
                            <span
                              className={clsx(
                                'min-w-0 max-w-[45%] shrink-0 truncate text-[13px] font-medium',
                                skipped ? 'text-ink-500' : 'text-ink-900',
                              )}
                              title={name?.subtitle ? `${title} — ${name.subtitle}` : s.label}
                            >
                              {title}
                              {name?.subtitle ? (
                                <span className="ml-1 text-[11px] font-normal text-ink-400">{name.subtitle}</span>
                              ) : null}
                            </span>
                            {handledText ? (
                              <span
                                className="shrink-0 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-950"
                                title={resilienceText(stepResilience?.get(s.id))}
                              >
                                {handledText}
                              </span>
                            ) : isExceptionStatus(s.status) ? (
                              <span className={clsx('shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold', tone)}>
                                {shortStatusLabel(s.status)}
                              </span>
                            ) : skipped ? (
                              <span className="shrink-0 text-[11px] text-ink-400" title={skipReasons?.get(s.id) || undefined}>
                                Skipped{skipText ? ` · ${skipText}` : ''}
                              </span>
                            ) : null}
                            {!handledText && resilienceText(stepResilience?.get(s.id)) ? (
                              <span className="shrink-0 text-[11px] text-amber-800" title={resilienceText(stepResilience?.get(s.id))}>
                                {stepResilience?.get(s.id)?.routed
                                  ? 'error routed'
                                  : stepResilience?.get(s.id)?.retries.length
                                    ? `retried ${stepResilience?.get(s.id)?.retries.length}×`
                                    : 'continued'}
                              </span>
                            ) : null}
                            {s.cacheHit ? (
                              <span
                                className="shrink-0 text-[11px] text-sky-800"
                                title={
                                  cacheSrc
                                    ? `Reused outputs of run ${runLabelFor?.(cacheSrc) || cacheSrc} (${cacheSrc})`
                                    : 'Reused cached outputs — source run not recorded'
                                }
                              >
                                cached
                              </span>
                            ) : null}
                            <span
                              className="min-w-0 flex-1 truncate text-[11px] text-ink-500"
                              title={[pm ? `${metricLabel(pm.name)} ${formatMetricValue(pm.name, pm.value)}` : '', `Wrote ${s.wroteRaw || s.wrote}`]
                                .filter(Boolean)
                                .join(' · ')}
                            >
                              {pm ? (
                                <span className="font-semibold tabular-nums text-ink-800">
                                  {metricLabel(pm.name)} {formatMetricValue(pm.name, pm.value)}
                                  <span className="font-normal text-ink-300"> · </span>
                                </span>
                              ) : null}
                              {flowMode ? (
                                <>
                                  {branch ? <span className="text-ink-600">{branch}</span> : null}
                                  {s.fileCount > 0 ? `${branch ? ' · ' : ''}${s.wrote}` : null}
                                </>
                              ) : (
                                s.wrote
                              )}
                            </span>
                            <span className="shrink-0 tabular-nums text-[11px] text-ink-500">
                              {formatDuration(s.durationMs)}
                            </span>
                          </button>
                          {failureLine && !active && !handledText ? (
                            <div className="truncate px-3 pb-1.5 pl-9 font-mono text-[11px] text-rose-700" title={failureLine}>
                              {failureLine}
                            </div>
                          ) : null}
                          {active ? (
                            <StepInlineDetails
                              story={s}
                              nodeType={nodeType}
                              labelById={labelById}
                              evaluatorMetrics={evaluator?.metricsByNode[s.id]}
                              path={nodePaths?.get(s.id) ?? null}
                              cacheSourceRunId={cacheSrc ?? null}
                              failure={stepFailures?.get(s.id) ?? null}
                              resilience={stepResilience?.get(s.id) ?? null}
                              runLabelFor={runLabelFor}
                              onOpenRun={onOpenRun}
                              config={stepConfigEntries(
                                node?.config && typeof node.config === 'object'
                                  ? (node.config as Record<string, unknown>)
                                  : null,
                                nodeType ? schemaFor?.(nodeType) : null,
                              )}
                              hasGraph={Boolean(node)}
                              images={imageOutputsForNode(
                                [
                                  ...(outputFiles || []).map((f) => ({
                                    name: String(f.name || f.path?.split('/').pop() || ''),
                                    path: String(f.path || ''),
                                    node_id: f.node_id ?? null,
                                  })),
                                  ...(evaluator?.confusionImageByNode[s.id]
                                    ? [
                                        {
                                          name: String(evaluator.confusionImageByNode[s.id].split('/').pop()),
                                          path: evaluator.confusionImageByNode[s.id],
                                          node_id: s.id,
                                        },
                                      ]
                                    : []),
                                ].filter((f) => f.path),
                                s.id,
                                focusMatchesNode,
                              )}
                              logs={stepLogs?.(s.id) ?? null}
                              onOpenLogs={onOpenLogs ? () => onOpenLogs(s.id) : undefined}
                              onOpenFile={onOpenFile ? (p) => onOpenFile(p, s.id) : undefined}
                              onBrowseOutputs={onBrowseOutputs ? () => onBrowseOutputs(s.id) : undefined}
                              onClose={onFocusStep ? () => onFocusStep(null) : undefined}
                            />
                          ) : null}
                        </li>
                      )
                    })}
                  </ol>
                ) : null}
              </div>
            )
          })}
        </div>
      </section>

      {hotSpots.length > 0 ? (
        <details className="overflow-hidden rounded-xl border border-ink-200 bg-white">
          <summary className="cursor-pointer select-none px-3 py-2 text-[13px] font-semibold text-ink-900">
            Hot spots{' '}
            <span className="text-[11px] font-normal text-ink-400">— slowest steps (not pipeline order)</span>
          </summary>
          <ul className="divide-y divide-ink-100 border-t border-ink-100">
            {hotSpots.map((s) => (
              <li
                key={s.id}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[13px]"
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

      {recordSlot}

      {(trace?.lineage?.artifacts || []).length > 0 ? (
        <details className="rounded-xl border border-ink-200 bg-white">
          <summary className="cursor-pointer select-none px-3 py-2 text-[12px] font-medium text-ink-600">
            Advanced — registry ids (support)
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

/** Settings the step ran with: changed-from-default first (highlighted), defaults behind "Show all". */
function ConfigList({ entries, hasGraph }: { entries: ConfigEntry[]; hasGraph: boolean }) {
  const [all, setAll] = React.useState(false)
  if (!entries.length) {
    return (
      <p className="text-[11px] text-ink-400">
        {hasGraph ? 'No settings — this step ran with its defaults.' : 'Graph snapshot not available for this run.'}
      </p>
    )
  }
  const explicit = entries.filter((e) => !e.fromDefault)
  const head = all ? entries : explicit.slice(0, 10)
  const hidden = entries.length - head.length
  const anyChanged = entries.some((e) => e.changed === true)
  return (
    <div>
      <dl className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-[11px]">
        {head.map((e) => (
          <React.Fragment key={e.key}>
            <dt
              className={clsx('truncate font-mono', e.changed ? 'font-semibold text-amber-900' : 'text-ink-500')}
              title={e.key}
            >
              {e.key}
            </dt>
            <dd
              className={clsx(
                'truncate font-mono',
                e.changed ? 'rounded bg-amber-50 px-1 text-amber-950' : e.fromDefault ? 'text-ink-400' : 'text-ink-800',
              )}
              title={
                e.changed
                  ? `${e.value} (default ${e.defaultValue})`
                  : e.fromDefault
                    ? `${e.value} (default — not set in the graph)`
                    : e.value
              }
            >
              {e.value}
            </dd>
          </React.Fragment>
        ))}
      </dl>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10px] text-ink-400">
        {anyChanged ? <span><span className="rounded bg-amber-50 px-1 text-amber-900">highlighted</span> = changed from default</span> : null}
        {hidden > 0 || all ? (
          <button type="button" className="font-medium text-accent-800 hover:underline" onClick={() => setAll((v) => !v)}>
            {all ? 'Show fewer' : `Show all ${entries.length}${entries.length > explicit.length ? ' (incl. defaults)' : ''}`}
          </button>
        ) : null}
      </div>
    </div>
  )
}

/** Step details, rendered inline under the clicked step row (accordion). */
function StepInlineDetails({
  story,
  nodeType,
  labelById,
  evaluatorMetrics,
  path,
  cacheSourceRunId,
  failure,
  resilience,
  runLabelFor,
  onOpenRun,
  config,
  hasGraph,
  images,
  logs,
  onOpenLogs,
  onOpenFile,
  onBrowseOutputs,
  onClose,
}: {
  story: StepStory
  nodeType: string
  labelById: Map<string, string>
  evaluatorMetrics?: unknown
  path?: PathResult | null
  cacheSourceRunId?: string | null
  failure?: FailureView | null
  resilience?: StepResilience | null
  runLabelFor?: (runId: string) => string | undefined
  onOpenRun?: (runId: string) => void
  config: ConfigEntry[]
  hasGraph: boolean
  images: Array<{ name: string; path: string }>
  logs: { lines: StepLogLine[]; total: number } | null
  onOpenLogs?: () => void
  onOpenFile?: (path: string) => void
  onBrowseOutputs?: () => void
  onClose?: () => void
}) {
  const name = (id: string) => labelById.get(id) || displayNodeLabel(id, { withCue: true })
  const fedBy = story.from.length ? story.from.map(name).join(', ') : 'start of the pipeline'
  const feeds = story.to.length ? story.to.map(name).join(', ') : 'end of this path'
  const fv = failure || (story.error ? failureView({ error: story.error }) : null)
  const logBox = React.useRef<HTMLOListElement | null>(null)
  React.useEffect(() => {
    // Newest lines at the bottom, in view.
    if (logBox.current) logBox.current.scrollTop = logBox.current.scrollHeight
  }, [logs?.lines.length])
  return (
    <div
      role="region"
      aria-label={`${story.label} details`}
      className="mx-2 mb-2 mt-0.5 space-y-2 rounded-lg border border-accent-200 bg-white px-3 py-2 text-[12px] shadow-sm"
    >
      <div className="flex min-w-0 items-start gap-2">
        <div className="min-w-0 flex-1 space-y-0.5">
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-ink-700">
            {isExceptionStatus(story.status) ? (
              <span className={clsx('rounded-full px-1.5 py-0.5 text-[11px] font-semibold', statusTone(story.status))}>
                {shortStatusLabel(story.status)}
              </span>
            ) : (
              <span className="font-medium text-ink-800">{shortStatusLabel(story.status)}</span>
            )}
            <span className="text-ink-300">·</span>
            <span className="tabular-nums">{formatDuration(story.durationMs)}</span>
            {nodeType ? (
              <>
                <span className="text-ink-300">·</span>
                <span className="font-mono text-[11px] text-ink-500">{nodeType}</span>
              </>
            ) : null}
            {story.cacheHit ? (
              <>
                <span className="text-ink-300">·</span>
                <span className="text-ink-600">
                  used cache
                  {linkableRunId(cacheSourceRunId) ? (
                    <>
                      {' from '}
                      {onOpenRun ? (
                        <button
                          type="button"
                          className="font-medium text-accent-800 underline-offset-2 hover:underline"
                          title={`Open run ${cacheSourceRunId}`}
                          onClick={() => onOpenRun(cacheSourceRunId!)}
                        >
                          {runLabelFor?.(cacheSourceRunId!) || shortRunId(cacheSourceRunId!)}
                        </button>
                      ) : (
                        <span title={cacheSourceRunId!}>{runLabelFor?.(cacheSourceRunId!) || shortRunId(cacheSourceRunId!)}</span>
                      )}
                    </>
                  ) : (
                    <span className="text-ink-400"> (source run not recorded)</span>
                  )}
                </span>
              </>
            ) : null}
          </div>
          <div className="truncate text-[11px] text-ink-500" title={`Fed by ${fedBy}\nFeeds ${feeds}`}>
            <span className="text-ink-400">Fed by </span>
            {fedBy}
            <span className="text-ink-300"> → </span>
            <span className="text-ink-400">feeds </span>
            {feeds}
          </div>
        </div>
        {onClose ? (
          <button
            type="button"
            className="btn-quiet shrink-0 !px-1 !py-0.5"
            aria-label="Close step details"
            title="Close (Esc)"
            onClick={onClose}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>

      {fv ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-2 py-1.5">
          <FailureDetails failure={fv} />
        </div>
      ) : null}

      {resilience && (resilience.retries.length || resilience.routed || resilience.continued) ? (
        <section aria-label="Retries and error handling" className="rounded-lg border border-amber-200 bg-amber-50/60 px-2.5 py-1.5 text-[11.5px] text-amber-950">
          <div className="font-semibold">{resilienceText(resilience)}</div>
          {resilience.retries.length ? (
            <ol className="mt-0.5 space-y-0.5">
              {resilience.retries.map((r, i) => (
                <li key={i} className="min-w-0 truncate" title={[r.errorType, r.error].filter(Boolean).join(': ')}>
                  Attempt {r.attempt ?? i + 2}
                  {r.maxAttempts ? `/${r.maxAttempts}` : ''}
                  {r.waitS ? ` after ${r.waitS} s` : ''}
                  {r.errorType || r.error ? (
                    <span className="text-amber-800">
                      {' '}
                      — previous try: {[r.errorType, r.error].filter(Boolean).join(': ')}
                    </span>
                  ) : null}
                </li>
              ))}
            </ol>
          ) : null}
          {resilience.routed ? (
            <p className="mt-0.5 break-words">
              Failed{resilience.routed.attempt ? ` after ${resilience.routed.attempt} attempt${resilience.routed.attempt === 1 ? '' : 's'}` : ''} — the error went to the{' '}
              <span className="font-mono">{resilience.routed.port}</span> branch instead of failing the run
              {resilience.routed.errorType || resilience.routed.error
                ? ` (${[resilience.routed.errorType, resilience.routed.error].filter(Boolean).join(': ')})`
                : ''}
              .
            </p>
          ) : null}
          {resilience.continued ? (
            <p className="mt-0.5 break-words">
              Failed and the run continued (on_error = continue); steps needing its outputs were skipped
              {resilience.continued.errorType || resilience.continued.error
                ? ` (${[resilience.continued.errorType, resilience.continued.error].filter(Boolean).join(': ')})`
                : ''}
              .
            </p>
          ) : null}
        </section>
      ) : null}

      {evaluatorMetrics != null ? <EvaluatorResult metrics={evaluatorMetrics} path={path} /> : null}

      {images.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {images.map((img) => (
            <button
              key={img.path}
              type="button"
              className="group flex flex-col items-start gap-0.5 text-left"
              title={`${img.name} — open in Run outputs`}
              onClick={() => onOpenFile?.(img.path)}
              disabled={!onOpenFile}
            >
              <BlobImage
                path={img.path}
                alt={img.name}
                className="h-28 w-auto max-w-[14rem] rounded border border-ink-200 bg-white object-contain group-hover:border-accent-300"
              />
              <span className="max-w-[14rem] truncate text-[10px] text-ink-500">{friendlyArtifactName(img.name).label}</span>
            </button>
          ))}
        </div>
      ) : null}

      <div className="grid gap-3 md:grid-cols-2">
        <section aria-label="Settings used" className="min-w-0">
          <h4 className="mb-1 text-[11px] font-semibold text-ink-700">Settings used</h4>
          <ConfigList entries={config} hasGraph={hasGraph} />
        </section>
        <section aria-label="Step logs" className="min-w-0">
          <div className="mb-1 flex items-baseline justify-between gap-2">
            <h4 className="text-[11px] font-semibold text-ink-700">
              Logs
              {logs && logs.total > 0 ? (
                <span className="font-normal text-ink-400">
                  {' '}
                  · {logs.total > logs.lines.length ? `last ${logs.lines.length} of ${logs.total.toLocaleString()}` : logs.total}
                </span>
              ) : null}
            </h4>
            {onOpenLogs ? (
              <button type="button" className="text-[11px] font-medium text-accent-800 hover:underline" onClick={onOpenLogs}>
                Open in Logs
              </button>
            ) : null}
          </div>
          {logs && logs.lines.length > 0 ? (
            <ol ref={logBox} className="max-h-40 overflow-y-auto rounded-md bg-ink-950 px-2 py-1 font-mono text-[10.5px] leading-[1.45] text-ink-100">
              {logs.lines.map((l) => (
                <li key={l.key} className={clsx('truncate', l.failed && 'text-rose-300')} title={l.text}>
                  {l.clock ? <span className="text-ink-500">{l.clock} </span> : null}
                  {l.text}
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-[11px] text-ink-400">No log lines for this step.</p>
          )}
        </section>
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 border-t border-ink-100 pt-1.5 text-[11px]">
        <span className="min-w-0 flex-1 truncate text-ink-600" title={story.wroteRaw || story.wrote}>
          <span className="text-ink-400">Wrote </span>
          {story.wrote}
        </span>
        {onBrowseOutputs ? (
          <button type="button" className="btn-secondary shrink-0 !px-2 !py-0.5 text-[11px]" onClick={onBrowseOutputs}>
            Open this step’s files
          </button>
        ) : null}
      </div>
    </div>
  )
}
