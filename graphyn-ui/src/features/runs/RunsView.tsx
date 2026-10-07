import React from 'react'
import clsx from 'clsx'
import { createPortal } from 'react-dom'
import { Archive, Download, Loader2, MoreHorizontal, Pause, Play, RefreshCw, Repeat, Rocket, Search, ShieldCheck, SlidersHorizontal, Workflow, X } from 'lucide-react'
import { ApiError, apiJson, apiUrl, getApiToken } from '../../api/client'
import type { GraphIR } from '../../types/graph'
import { emptyGraph } from '../../types/graph'
import { fetchRunGraph } from '../../lib/runGraph'
import { resolveFullRunId } from '../../lib/runDisplay'
import { useAppStore } from '../../store/appStore'
import { runMatchesProject } from '../../lib/projectStamp'
import { usePolling } from '../../lib/usePolling'
import {
  isAwaitingApproval,
  isLiveRunStatus,
  isTerminalRunStatus,
  normalizeRunStatus,
  statusMatchesFilter,
} from '../../lib/runStatus'
import {
  ConfirmButton,
  CollapsibleJson,
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  IdeTabs,
  NeedProjectPrompt,
  SlimProgress,
  StatusBadge,
} from '../../components/ui'
import { FieldSelect } from '../../components/FieldSelect'
import { SplitPane } from '../../components/SplitPane'
import { FileViewer } from '../../components/FileViewer'
import { MasterDetail, MasterDetailToggle, useLayoutPrefs, ViewShell } from '../../layout'
import { useElementWidth } from '../../lib/viewport'
import { formatBytes } from '../../lib/fileKind'
import {
  formatExecutionLine,
  formatLocaleDateTime,
  formatLogClock,
  formatRelativeTime,
  formatRunMetric,
  humanizeTemplateName,
  displayNodeLabel,
  humanNodeLabel,
  focusMatchesNode,
  shortRunId,
  skipConsecutiveByText,
} from '../../lib/format'
import { navigatePath, panelToFocus, parsePathname } from '../../routes/parsePath'
import { paths, type RunPanel } from '../../routes/paths'
import { goView, onPathChange } from '../../routes/nav'
import { RunLineagePanel } from './RunLineagePanel'
import { apiErrorCode } from '../../api/errorCode'
import ExperimentsView, { type ExperimentsViewHandle } from '../experiments/ExperimentsView'
import {
  executionOrderFromRun,
  guessNodeFromPath,
  looksLikeOpaqueId,
  shortOutputPath,
  normalizeOutputsResponse,
  orderOutputGroups,
  artifactSlugFromPath,
  isPackageRun,
  listRunModelCandidates,
  runHasModelOutput,
  runLevelFileCue,
  sortFilesNatural,
  type NodeTruncation,
  type RunModelCandidate,
} from './runOutputs'
import {
  computePipelineShape,
  disambiguateByPath,
  extractRunFailure,
  failureProposalSummary,
  isMultiTrackShape,
  pipelineNodesFromRun,
} from './runNodes'
import { dedupeErrorRows } from '../builder/logDedupe'
import { formatMetricDelta, formatMetricValue, metricLabel, primaryMetric, regressionOf } from '../../lib/metrics'
import {
  bestPathIdFromSummary,
  overviewMetrics,
  datasetFromRun,
  defaultModelOption,
  fallbackPathResults,
  guessModelKind,
  isUntrained,
  lanePathMap,
  listRowMetric,
  modelKindLabel,
  normalizeRunModels,
  pathDisplayName,
  pathOfNodeMap,
  pathsFromSummary,
  pickBestPath,
  rankModelOptions,
  runTitle,
  suggestModelName,
  type ModelOption,
  type PathResult,
  type RegressionView,
} from './runResults'
import {
  collapseProgressRows,
  collapseWaitingRows,
  finishedNodeIds,
  formatProgressLine,
  formatWaitingLine,
  latestProgressByNode,
  parseProgress,
  runningNodesOf,
  type NodeProgress,
  type RunningNode,
} from './runProgress'
import { ProgressLogLine, RunResultsBanner } from './RunResults'
import { ShipPackageSummaryForPath } from '../edge/ShipPackageSummary'
import { isShipManifestPath } from '../edge/shipManifest'
import { useEvaluatorOutputs } from './useRunResults'
import { ReplayPanel, RunRecordCard, VerifyChecklist } from './RunRecord'
import { ApprovalGates } from './ApprovalGates'
import { resilienceByNode } from './runWorkflow'
import {
  branchContextByNode,
  branchingNodesOf,
  isMlMultiPath,
  skipReasonsByNode,
  stepDisplayNames,
  stripPathSuffix,
} from './runFlow'
import { parseStepParam, searchWithoutStep } from './stepQuery'
import {
  cacheSourcesFromNodeStats,
  compactNodeLabel,
  eventNodeLabel,
  failureView,
  failuresByNode,
  groupVerify,
  isArchivedRun,
  lastVerifyOf,
  lastVerifyText,
  linkableRunId,
  nodeLabelsFromRun,
  normalizeVerify,
  parseLastVerify,
  parseReplayConflict,
  parseVerifyCounts,
  pickProve,
  replayOfRun,
  replayRunId,
  type InputChange,
  type LastVerify,
  type VerifyCounts,
} from './runRecord'
import { ActorName } from '../../components/ActorName'
import { modelStageLabel } from '../models/modelLineage'
import { relabelLine } from '../builder/journalLog'
import { unscopeRunPaths } from '../builder/graphDrift'
import { FailureDetails } from './FailureDetails'
import {
  comparableRegression,
  friendlyArtifactName,
  graphNameOf,
  isComparableRun,
  pathCountOf,
  runFailureReason,
  stepPickerOptions,
} from './runOverview'
import { ShortId, StepPicker } from './RunOverviewParts'
import { usePaneWidth } from './usePaneWidth'
import {
  lastLogsForNode,
  orderOutputGroupsByImportance,
  pickDefaultOutput,
} from './stepDetails'

/** Close the `<details>` menu that contains the clicked item. */
function closeMenu(e: React.MouseEvent<HTMLElement>) {
  const d = e.currentTarget.closest('details')
  if (d) d.open = false
}

/** Run ids whose GET /runs/{id} returned 404 this session — never auto-reopened. */
const MISSING_RUN_IDS = new Set<string>()

type DetailPanel = 'logs' | 'checkpoints' | 'artifacts' | 'lineage'

/** Store panel value → URL panel segment (paths.runPanel). */
function panelToPath(panel: DetailPanel): RunPanel {
  if (panel === 'artifacts') return 'outputs'
  return panel
}

/** Normalize legacy Summary (`debug`) focus onto Overview (`lineage`). */
function normalizePanel(
  p: DetailPanel | 'debug' | null | undefined,
): DetailPanel | null {
  if (!p) return null
  if (p === 'debug') return 'lineage'
  return p
}

/** Fetch the outputs listing with per-node truncation info when the API supports it. */
async function fetchRunOutputs(id: string) {
  const raw = await apiJson<unknown>(`/runs/${encodeURIComponent(id)}/outputs`, { query: { with_meta: 1 } }).catch(
    () => [],
  )
  return normalizeOutputsResponse<OutputFile>(raw)
}

interface RunSummary {
  run_id: string
  status?: string
  created_at?: string
  graph_name?: string
  artifacts_dir?: string
  metrics?: Record<string, unknown>
  [key: string]: unknown
}

interface OutputFile {
  name: string
  path: string
  size: number
  kind: string
  /** Set by GET /runs/{id}/outputs when the file is tied to a node. */
  node_id?: string | null
}

function classifyOutputRole(path: string, arts: RunArtifact[]): 'input' | 'output' {
  const lower = path.toLowerCase()
  if (/(^|\/)inputs?(\/|$)/.test(lower) || /(?:^|[_\-/])input(?:[_\-./]|$)/.test(lower)) {
    return 'input'
  }
  for (const a of arts) {
    const dp = String(a.data_path || a.path || '').toLowerCase()
    if (!dp || !(lower.includes(dp) || dp.includes(lower))) continue
    const t = String(a.artifact_type || '').toLowerCase()
    if (t.includes('input') || t === 'in') return 'input'
  }
  return 'output'
}

/** Pull a node id/type/label out of a log row for Focus filtering. */
function extractLogNodeHint(
  log: Record<string, unknown>,
  formattedText: string,
  rawMessage: string,
): string | null {
  const fromObj = (obj: Record<string, unknown> | null | undefined): string | null => {
    if (!obj) return null
    for (const k of ['node_id', 'nodeId', 'node', 'node_type', 'nodeType'] as const) {
      const v = obj[k]
      if (typeof v === 'string' && v.trim()) return v.trim()
    }
    return null
  }
  const direct = fromObj(log)
  if (direct) return direct
  try {
    const ev = JSON.parse(rawMessage.trim()) as unknown
    if (ev && typeof ev === 'object' && !Array.isArray(ev)) {
      const fromEv = fromObj(ev as Record<string, unknown>)
      if (fromEv) return fromEv
    }
  } catch {
    /* plain text */
  }
  const fromRaw =
    rawMessage.match(/\bnode[_\s]?id[=: ]+([A-Za-z0-9_.-]+)/i)?.[1] ||
    rawMessage.match(/\b(?:executing|completed|failed)\s+([A-Za-z0-9_.-]+)/i)?.[1] ||
    null
  if (fromRaw) return fromRaw
  // Formatted lines look like "Trainer · started" / "Trainer · 269.7s"
  const head = formattedText.split(' · ')[0]?.trim() || ''
  if (head && !/^(pipeline|event)\b/i.test(head)) return head
  return null
}

/** Runs stuck in RUNNING with no process heartbeat — warn after this age. */
const STALE_RUNNING_MS = 60 * 60 * 1000 // 1 hour

function runningAgeMs(createdAt?: string | null): number | null {
  if (!createdAt) return null
  const t = Date.parse(createdAt)
  if (!Number.isFinite(t)) return null
  return Date.now() - t
}

function isStaleRunning(status?: string | null, createdAt?: string | null): boolean {
  if (String(status || '').toLowerCase() !== 'running') return false
  const age = runningAgeMs(createdAt)
  return age != null && age >= STALE_RUNNING_MS
}

/** Backend `display_name`, else the humanized graph name — never a bare "Pipeline". */
function runDisplayName(r: RunSummary): string {
  return runTitle(r)
}

const PANEL_LABELS: Record<string, string> = {
  logs: 'Logs',
  artifacts: 'Run outputs',
  lineage: 'Overview',
  checkpoints: 'Checkpoints',
}

interface RunArtifact {
  artifact_id?: string
  id?: string
  node_id?: string
  node_type?: string
  artifact_type?: string
  data_path?: string
  path?: string
  metadata?: Record<string, unknown>
}

const LIVE_STATUSES = new Set(['running', 'queued', 'paused'])

function isLiveStatus(status?: string | null): boolean {
  return LIVE_STATUSES.has(normalizeRunStatus(status))
}

/** Short list-friendly status text (StatusBadge otherwise echoes raw API casing). */
function shortStatusLabel(status?: string | null): string {
  if (isAwaitingApproval(status)) return 'Awaiting approval'
  switch (normalizeRunStatus(status)) {
    case 'completed':
      return 'Done'
    case 'failed':
      return 'Failed'
    case 'cancelled':
      return 'Cancelled'
    case 'running':
      return 'Running'
    case 'paused':
      return 'Paused'
    case 'queued':
      return 'Queued'
    default:
      return String(status || 'Unknown')
  }
}

function metricNumeric(metrics: Record<string, unknown> | undefined, name: string): number | null {
  if (!metrics || !name) return null
  const raw = metrics[name]
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (Array.isArray(raw) && raw.length && typeof raw[raw.length - 1] === 'number') {
    return raw[raw.length - 1] as number
  }
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

type WaveBucket = { key: string; count: number; className: string }

function waveBucketsFromNodeStats(
  nodeStats: Array<Record<string, unknown>> | undefined,
): WaveBucket[] {
  const WAVE_TONE: Record<string, string> = {
    running: 'bg-sky-400',
    queued: 'bg-amber-300',
    pending: 'bg-amber-300',
    paused: 'bg-violet-300',
    failed: 'bg-rose-400',
    error: 'bg-rose-400',
    done: 'bg-emerald-400',
    completed: 'bg-emerald-400',
    succeeded: 'bg-emerald-400',
    success: 'bg-emerald-400',
    cancelled: 'bg-ink-300',
  }
  if (!nodeStats?.length) return []
  const counts: Record<string, number> = {}
  for (const n of nodeStats) {
    const st = String(n.status ?? n.state ?? '').toLowerCase().trim()
    if (!st) continue
    counts[st] = (counts[st] || 0) + 1
  }
  return Object.entries(counts).map(([key, count]) => ({
    key,
    count,
    className: WAVE_TONE[key] || 'bg-ink-300',
  }))
}

const LOG_ROW_PX = 20
const LOG_VIEWPORT_PX = 448

function extractLogTimestamp(log: Record<string, unknown>, rawMessage: string): string {
  const direct = formatLogClock(log.timestamp ?? log.time ?? log.ts)
  if (direct) return direct
  try {
    const ev = JSON.parse(rawMessage.trim()) as Record<string, unknown>
    if (ev && typeof ev === 'object') {
      return formatLogClock(ev.timestamp ?? ev.time ?? ev.ts)
    }
  } catch {
    /* plain text */
  }
  return ''
}

type FormattedLogRow = {
  i: number
  l: Record<string, unknown>
  /** The journal event (a JSON `message` unwrapped) — node_id / node_type / node_label. */
  ev: Record<string, unknown>
  line: ReturnType<typeof formatExecutionLine>
  nodeHint: string | null
  failed: boolean
  clock: string
  /** Pretty view: collapsed node_progress (latest + history). */
  progress?: { latest: NodeProgress; history: NodeProgress[]; count: number }
  /** Pretty view: collapsed Mode B Waiting-for-worker heartbeats. */
  waiting?: { text: string; count: number }
}

function VirtualRunLogList({
  rows,
  emptyLabel = 'No logs recorded for this run.',
  labelFor,
  raw = false,
}: {
  rows: FormattedLogRow[]
  emptyLabel?: string
  /** Node id/hint → human step label (graph label + path). */
  labelFor?: (hint: string) => string | undefined
  /** Raw view: the event JSON as recorded. */
  raw?: boolean
}) {
  const scrollerRef = React.useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = React.useState(0)
  const [viewportH, setViewportH] = React.useState(LOG_VIEWPORT_PX)

  React.useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setViewportH(el.clientHeight || LOG_VIEWPORT_PX))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const totalH = rows.length * LOG_ROW_PX
  const start = Math.max(0, Math.floor(scrollTop / LOG_ROW_PX) - 4)
  const visibleCount = Math.ceil(viewportH / LOG_ROW_PX) + 8
  const end = Math.min(rows.length, start + visibleCount)
  const slice = rows.slice(start, end)
  const offsetY = start * LOG_ROW_PX

  return (
    <div
      ref={scrollerRef}
      className="max-h-[28rem] overflow-auto rounded-2xl bg-ink-950 p-4 font-mono text-[11px] leading-5 text-ink-100 shadow-soft"
      onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
    >
      {rows.length === 0 ? (
        <div className="text-ink-500">{emptyLabel}</div>
      ) : (
        <div style={{ height: totalH, position: 'relative' }}>
          <div style={{ transform: `translateY(${offsetY}px)` }}>
            {slice.map(({ i, ev, line, nodeHint, failed, clock, progress, waiting }) => {
              const evLabel = eventNodeLabel(ev)
              const hintLabel = evLabel
                ? compactNodeLabel(evLabel)
                : nodeHint
                  ? labelFor?.(nodeHint) || humanNodeLabel(nodeHint)
                  : ''
              // "Trainer · started" → "Trainer · Path C · started" (backend node_label,
              // else the path-aware stack label).
              const text = raw
                ? line.raw || line.text
                : progress
                  ? formatProgressLine(progress.latest, hintLabel || undefined)
                  : waiting
                    ? formatWaitingLine(waiting.text, waiting.count)
                    : relabelLine(line.text, ev, labelFor)
              const showHint =
                !raw &&
                !progress &&
                !waiting &&
                Boolean(hintLabel) &&
                !text.toLowerCase().startsWith(hintLabel.toLowerCase()) &&
                !text.toLowerCase().startsWith(humanNodeLabel(nodeHint || '').toLowerCase())
              return (
              <div
                key={i}
                style={{ height: LOG_ROW_PX }}
                className={`flex min-w-0 items-baseline gap-1.5 overflow-hidden whitespace-nowrap ${
                  failed ? 'text-rose-300' : waiting ? 'text-ink-400' : ''
                }`}
                title={waiting ? `${waiting.count} waiting notes` : undefined}
              >
                {clock ? (
                  <span className="shrink-0 tabular-nums text-ink-500" title={clock}>
                    {clock}
                  </span>
                ) : null}
                {showHint ? (
                  <span className="shrink-0 rounded bg-ink-800 px-1 text-[10px] text-accent-300">
                    {hintLabel}
                  </span>
                ) : null}
                {progress ? (
                  <ProgressLogLine
                    text={text}
                    progress={progress.latest}
                    history={progress.history}
                    count={progress.count}
                  />
                ) : (
                  <span className="min-w-0 truncate" title={raw ? undefined : line.raw || undefined}>
                    {text}
                  </span>
                )}
              </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

function NodeStatusWave({ buckets }: { buckets: WaveBucket[] }) {
  const total = buckets.reduce((s, b) => s + b.count, 0)
  if (total <= 0) return null
  return (
    <div className="space-y-1">
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-ink-100" role="img" aria-label="Node status wave">
        {buckets.map((b) => (
          <div
            key={b.key}
            className={`${b.className} h-full min-w-[2px]`}
            style={{ width: `${(b.count / total) * 100}%` }}
            title={`${b.key}: ${b.count}`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-ink-500">
        {buckets.map((b) => (
          <span key={b.key}>
            <span className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${b.className}`} />
            {b.key} {b.count}
          </span>
        ))}
      </div>
    </div>
  )
}

/** Compare mode: Back + title + Refresh (not a peer of History/Live). */
function CompareRunsTab({
  description,
  onBack,
}: {
  description?: string
  onBack: () => void
}) {
  const experimentsRef = React.useRef<ExperimentsViewHandle>(null)
  return (
    <ViewShell
      title="Compare"
      description={description}
      inlineToolbar
      actions={
        <>
          <button type="button" className="btn-secondary" onClick={onBack}>
            Back to runs
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => experimentsRef.current?.refresh()}
          >
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        </>
      }
    >
      <ExperimentsView ref={experimentsRef} embedded />
    </ViewShell>
  )
}

const RUNS_LIST_WIDTH_KEY = 'graphyn.runs.listWidth'

/**
 * One layout always: MasterDetail edge-to-edge (sidebar already says Runs).
 * No ViewShell title strip — selecting a run must not change the outer chrome.
 * The run list collapses only via MasterDetail's own toggle (persisted) — never
 * per tab, so Overview / Run outputs / Logs keep the same list state.
 */
function RunsShell({
  list,
  detail,
  selectedKey,
  onBack,
}: {
  list: React.ReactNode
  detail: React.ReactNode
  selectedKey: string | null
  onBack: () => void
}) {
  const { mode: layoutMode } = useLayoutPrefs()
  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--surface-muted)]">
      <MasterDetail
        listLabel="runs"
        storageKey="graphyn.runs"
        // Own list width (not the shared master width other pages narrow):
        // run names + the filter row need ≥ 300 px at 1366–1536 wide.
        widthKey={layoutMode === 'container-content' ? undefined : RUNS_LIST_WIDTH_KEY}
        defaultSize={360}
        minSize={300}
        selectedKey={selectedKey}
        onBack={onBack}
        master={list}
        detail={detail}
        collapsible
        detailClassName="!flex !flex-col !overflow-hidden !p-0"
        masterClassName="!overflow-y-auto !p-0 [scrollbar-gutter:stable]"
      />
    </div>
  )
}

/** Compact in-flight monitor (was Live-tab detail) — shown under run chrome when status is live. */
function LiveRunMonitor({
  nodeStats,
  workers,
  progress = [],
  labelFor,
  running = [],
  steps = [],
}: {
  nodeStats: Array<Record<string, unknown>>
  workers: Array<[string, string]>
  /** Latest node_progress per still-running node. */
  progress?: NodeProgress[]
  labelFor?: (nodeId: string) => string | undefined
  /** Nodes executing right now (all of them on parallel paths), path-labelled. */
  running?: RunningNode[]
  /** Pipeline steps with status (journal-derived) — includes running ones, unlike node_stats. */
  steps?: Array<{ id: string; label: string; status?: string }>
}) {
  const wave = waveBucketsFromNodeStats(nodeStats)
  if (
    wave.length === 0 &&
    workers.length === 0 &&
    nodeStats.length === 0 &&
    progress.length === 0 &&
    running.length === 0
  )
    return null
  const runningIds = new Set(running.map((r) => r.id))
  // Running steps first (with spinner), then finished ones in pipeline order.
  const doneSteps = steps.filter((s) => !runningIds.has(s.id) && s.status && s.status !== 'pending')
  const useSteps = steps.length > 0
  return (
    <div className="shrink-0 space-y-2 border-b border-ink-100 bg-ink-50/60 px-3 py-2">
      {progress.map((p) => (
        <div key={p.nodeId} className="text-[12px] text-ink-800" aria-live="polite">
          <ProgressLogLine
            text={formatProgressLine(p, labelFor?.(p.nodeId))}
            progress={p}
            history={[p]}
            count={1}
            dark={false}
          />
        </div>
      ))}
      {wave.length > 0 ? <NodeStatusWave buckets={wave} /> : null}
      {workers.length > 0 ? (
        <div className="flex flex-wrap gap-1.5 text-[11px] text-ink-600">
          {workers.map(([nid, wid]) => (
            <span
              key={nid}
              className="rounded-md bg-white px-1.5 py-0.5 font-mono text-ink-800 ring-1 ring-ink-200/80"
              title={`Node ${nid}`}
            >
              {labelFor?.(nid) || humanNodeLabel(nid)} → {wid}
            </span>
          ))}
        </div>
      ) : null}
      {useSteps && (running.length > 0 || doneSteps.length > 0) ? (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-500">
          <span className="font-medium text-ink-500">Steps</span>
          {running.map((r) => (
            <span key={r.id} className="inline-flex items-center gap-1 font-medium text-sky-800" title={`${r.id} · running`}>
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
              {r.label}
              <span className="font-mono text-[10px] text-sky-600">running</span>
            </span>
          ))}
          {doneSteps.slice(0, Math.max(0, 8 - running.length)).map((st) => (
            <span key={st.id} className="inline-flex items-center gap-1" title={st.id}>
              <span className="font-medium text-ink-800">{st.label}</span>
              <span className="font-mono text-[10px] text-ink-400">{st.status}</span>
            </span>
          ))}
          {doneSteps.length > Math.max(0, 8 - running.length) ? (
            <span className="text-ink-400">+{doneSteps.length - Math.max(0, 8 - running.length)} more</span>
          ) : null}
        </div>
      ) : !useSteps && nodeStats.length > 0 ? (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-500">
          <span className="font-medium text-ink-500">Nodes</span>
          {nodeStats.slice(0, 8).map((n, i) => (
            <span key={i} className="inline-flex items-center gap-1">
              <span className="font-medium text-ink-800">
                {labelFor?.(String(n.node_id || '')) ||
                  humanNodeLabel(String(n.node_type || n.node_id || `node-${i}`))}
              </span>
              {n.status != null ? (
                <span className="font-mono text-[10px] text-ink-400">{String(n.status)}</span>
              ) : null}
            </span>
          ))}
          {nodeStats.length > 8 ? (
            <span className="text-ink-400">+{nodeStats.length - 8} more</span>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export default function RunsView() {
  const focusRunId = useAppStore((s) => s.focusRunId)
  const focusRunPanel = useAppStore((s) => s.focusRunPanel)
  const clearFocusRunPanel = useAppStore((s) => s.clearFocusRunPanel)
  const focusRunsTab = useAppStore((s) => s.focusRunsTab)
  const setFocusRunsTab = useAppStore((s) => s.setFocusRunsTab)
  const lastRunId = useAppStore((s) => s.lastRunId)
  const setLastRunId = useAppStore((s) => s.setLastRunId)
  const pushToast = useAppStore((s) => s.pushToast)
  const openExperiments = useAppStore((s) => s.openExperiments)
  const openProposals = useAppStore((s) => s.openProposals)
  const openProjects = useAppStore((s) => s.openProjects)
  const activeProject = useAppStore((s) => s.activeProject)
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)

  const [runs, setRuns] = React.useState<RunSummary[] | null>(null)
  const [offset, setOffset] = React.useState(0)
  const [selected, setSelected] = React.useState<string | null>(null)
  // Mirrors `selected` synchronously (open() sets it before the re-render) so
  // async results can check they still belong to the selected run.
  const selectedRef = React.useRef<string | null>(null)
  selectedRef.current = selected
  const openSeqRef = React.useRef(0)
  const [detail, setDetail] = React.useState<Record<string, unknown> | null>(null)
  const [status, setStatus] = React.useState<Record<string, unknown> | null>(null)
  const [debug, setDebug] = React.useState<Record<string, unknown> | null>(null)
  const [checkpoints, setCheckpoints] = React.useState<string[]>([])
  const [samples, setSamples] = React.useState<unknown>(null)
  const [outputFiles, setOutputFiles] = React.useState<OutputFile[]>([])
  const [outputsMeta, setOutputsMeta] = React.useState<{ truncated: boolean; byNode: Record<string, NodeTruncation> }>({
    truncated: false,
    byNode: {},
  })
  /** node_id → every file of that node (GET /outputs?node_id=), loaded on "Show all". */
  const [expandedNodeFiles, setExpandedNodeFiles] = React.useState<Record<string, OutputFile[]>>({})
  const [expandingNode, setExpandingNode] = React.useState<string | null>(null)
  /** Selected run id whose GET /runs/{id} returned 404 (deleted / never existed). */
  const [notFoundRunId, setNotFoundRunId] = React.useState<string | null>(null)
  const [runArtifacts, setRunArtifacts] = React.useState<RunArtifact[]>([])
  const [selectedOutputPath, setSelectedOutputPath] = React.useState<string | null>(null)
  const [focusNodeId, setFocusNodeId] = React.useState<string | null>(null)
  const [panel, setPanel] = React.useState<DetailPanel>('logs')
  const [error, setError] = React.useState<string | null>(null)
  const [statusFilter, setStatusFilter] = React.useState<string>('all')
  const [nameQuery, setNameQuery] = React.useState('')
  /** Filter row width → icon-only search when the text box would be < ~90 px. */
  const [filterRowRef, filterRowWidth] = useElementWidth<HTMLDivElement>()
  const [searchOpen, setSearchOpen] = React.useState(false)
  const searchIconOnly = filterRowWidth > 0 && filterRowWidth < 300 && !searchOpen && !nameQuery
  const [metricName, setMetricName] = React.useState('')
  const [metricMin, setMetricMin] = React.useState('')
  const [promoteAlias, setPromoteAlias] = React.useState<'latest' | 'staging' | 'prod'>('latest')
  const [promoteOpen, setPromoteOpen] = React.useState(false)
  /** Which model branch to register when a run has multiple builders/trainers. */
  const [promoteCandidateId, setPromoteCandidateId] = React.useState<string | null>(null)
  const [regModelName, setRegModelName] = React.useState('')
  /** Every registered model → its stages (to warn before overwriting a stage). */
  const [allModelStages, setAllModelStages] = React.useState<
    Map<string, Record<string, { run_id?: string; updated_at?: string }>>
  >(new Map())
  const [regModelSlug, setRegModelSlug] = React.useState('')
  const [registerBusy, setRegisterBusy] = React.useState(false)
  const [explainBusy, setExplainBusy] = React.useState(false)
  /** "Ask agent to fix" confirmation panel open. */
  const [askAgentOpen, setAskAgentOpen] = React.useState(false)
  /** The run's Graph IR (GET /runs/{id}/graph or graph.json) when the detail doesn't embed it. */
  const [runGraph, setRunGraph] = React.useState<GraphIR | null>(null)
  /** Multi-select for Compare action (2–5). */
  const [compareIds, setCompareIds] = React.useState<string[]>([])
  /** Metric/min filters — collapsed by default so the list strip stays one row. */
  const [moreFilters, setMoreFilters] = React.useState(false)
  const [runModels, setRunModels] = React.useState<
    Array<{ name: string; stages?: Record<string, { run_id?: string; slug?: string; updated_at?: string }> }>
  >([])
  const limit = 50
  const pendingPanelRef = React.useRef<DetailPanel | null>(null)
  const wasLiveRunRef = React.useRef(false)
  const focusSeededForRun = React.useRef<string | null>(null)
  /** Runs → Logs: Raw shows every recorded event; Pretty collapses progress. */
  const [rawLogView, setRawLogView] = React.useState(false)
  /** GET /runs/{id}/models (null = not loaded / not supported by this API). */
  const [runModelRows, setRunModelRows] = React.useState<ModelOption[] | null>(null)
  /** Register: also list untrained (architecture-only) models. */
  const [showUntrained, setShowUntrained] = React.useState(false)
  const livePollTickRef = React.useRef(0)
  const evaluatorOutputs = useEvaluatorOutputs(selected, outputFiles)
  /** deployment_packager sidecar `<package>.manifest.json` → its package path. */
  const shipPackagePath = React.useMemo(() => {
    const f = outputFiles.find((o) => isShipManifestPath(o.path))
    return f ? f.path.replace(/\.manifest\.json$/i, '') : null
  }, [outputFiles])
  /** List filter: include archived runs (`GET /runs?include_archived=1`). */
  const [showArchived, setShowArchived] = React.useState(false)
  /** Replay exactly: confirm panel / in-flight / 409 inputs_changed diff. */
  const [replayOpen, setReplayOpen] = React.useState(false)
  const [replayBusy, setReplayBusy] = React.useState(false)
  const [replayConflict, setReplayConflict] = React.useState<{ message: string; changes: InputChange[] } | null>(null)
  /** Verify checklist for the selected run (null = not run yet). */
  const [verifyResult, setVerifyResult] = React.useState<{
    runId: string
    ok: boolean | null
    status: string
    verifiedAt: string
    groups: ReturnType<typeof groupVerify>
    /** Server summary counts / who verified / history size (newer APIs). */
    counts: VerifyCounts | null
    actor: { name: string; verified: boolean | null; claimed: string } | null
    historyCount: number | null
    /** Same outcome as a `last_verify` row → Run record summary line. */
    last: LastVerify | null
  } | null>(null)
  const [verifyBusy, setVerifyBusy] = React.useState(false)
  /** Advanced "Delete permanently" typed confirmation. */
  const [purgeOpen, setPurgeOpen] = React.useState(false)
  const [purgeText, setPurgeText] = React.useState('')
  const [archiveBusy, setArchiveBusy] = React.useState(false)
  /** Run detail pane width — header actions / path table adapt to it (not the viewport). */
  const [detailPaneRef, detailPaneWidth] = usePaneWidth<HTMLDivElement>()
  /** < 900 px: Verify / Replay / Open in Ship move into ⋯. */
  const compactActions = detailPaneWidth > 0 && detailPaneWidth < 900
  /** < 700 px: path table → stacked cards. */
  const narrowDetail = detailPaneWidth > 0 && detailPaneWidth < 700
  const nodeCatalog = useAppStore((s) => s.catalog)

  // Register dialog: Esc closes it.
  React.useEffect(() => {
    if (!promoteOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        setPromoteOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [promoteOpen])

  const goBackToRuns = React.useCallback(() => {
    setFocusRunsTab('history')
    if (activeProject) navigatePath(paths.runs(activeProject))
  }, [activeProject, setFocusRunsTab])

  // /runs?status=active (and /runs/live alias) seeds the Active filter once.
  React.useEffect(() => {
    const qs = new URLSearchParams(window.location.search)
    if (qs.get('status') === 'active') setStatusFilter('active')
    // ?q= seeds the search box (e.g. q=trigger:webhook from the Editor Triggers dock).
    const q = qs.get('q')
    if (q) setNameQuery(q)
  }, [])

  // Tab focus comes from store / pathname (/runs/live, /runs/compare) via App — no hash sync.
  React.useEffect(() => {
    if (!focusRunPanel) return
    const next = normalizePanel(focusRunPanel)
    if (!next) return
    pendingPanelRef.current = next
    setPanel(next)
    setFocusRunsTab('history')
    clearFocusRunPanel()
  }, [focusRunPanel, clearFocusRunPanel, setFocusRunsTab])

  /**
   * Reflect the selected run + detail panel in the address bar so a selection
   * is deep-linkable (/workspaces/<ws>/runs/<id>/<panel>). Writes history
   * directly rather than via navigatePath: navigatePath dispatches popstate,
   * and App's path sync would then call store.openRun — re-opening the run
   * we just opened and rewriting the header's "Last run" to every run the
   * user merely looks at. Back/forward is handled by the onPathChange
   * listener above. A new run selection pushes; a panel switch replaces.
   */
  /** Set by user-initiated selection (list click) so that change pushes a history entry. */
  const pushNextUrlRef = React.useRef(false)
  React.useEffect(() => {
    // No selection yet: leave the URL alone — on a deep-link load the run id
    // in the address bar is about to be opened. (Explicit deselects — Back to
    // runs, Delete — navigate themselves.)
    if (!selected || !activeProject || focusRunsTab !== 'history') return
    const parsed = parsePathname(window.location.pathname, window.location.search)
    if (parsed.view !== 'runs' || parsed.runsTab !== 'history' || parsed.workspaceId !== activeProject) return
    const target =
      notFoundRunId === selected
        ? paths.run(activeProject, selected)
        : paths.runPanel(activeProject, selected, panelToPath(panel))
    const push = pushNextUrlRef.current
    pushNextUrlRef.current = false
    if (window.location.pathname === target) return
    if (push) window.history.pushState(null, '', target)
    else window.history.replaceState(null, '', target)
  }, [activeProject, focusRunsTab, selected, panel, notFoundRunId])

  const load = React.useCallback(async () => {
    setError(null)
    try {
      const query: Record<string, string | number> = { limit, offset }
      if (activeProject) query.project = activeProject
      if (showArchived) query.include_archived = 1
      setRuns(await apiJson<RunSummary[]>('/runs', { query }))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setRuns([])
    }
  }, [offset, activeProject, showArchived])

  React.useEffect(() => {
    void load()
  }, [load])

  // Poll the list while the filter can show in-flight runs (Active / Running / Queued / Paused).
  const listPollLive =
    statusFilter === 'active' ||
    statusFilter === 'running' ||
    statusFilter === 'queued' ||
    statusFilter === 'paused'
  usePolling(load, 3000, { enabled: listPollLive && focusRunsTab === 'history', resetKey: load })

  React.useEffect(() => {
    // The address bar wins (deep link /runs/<id>[/<panel>]); otherwise fall
    // back to the store's focus / last run — but never auto-reopen a run we
    // already know 404s.
    const fromUrl = parsePathname(window.location.pathname, window.location.search)
    const id = fromUrl.view === 'runs' && fromUrl.runId ? fromUrl.runId : focusRunId || lastRunId
    if (!id || id === selectedRef.current) return
    if (!(fromUrl.runId === id) && MISSING_RUN_IDS.has(id)) return
    void open(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRunId])

  /**
   * Back / forward between run URLs. App's own path sync also reacts (via
   * store.openRun → focusRunId), and both paths are guarded by
   * `id === selectedRef.current`, so a run is only opened once.
   */
  React.useEffect(
    () =>
      onPathChange(() => {
        const parsed = parsePathname(window.location.pathname, window.location.search)
        if (parsed.view !== 'runs' || parsed.runsTab !== 'history') return
        if (parsed.runId) {
          const p = normalizePanel(panelToFocus(parsed.panel))
          if (parsed.runId !== selectedRef.current) {
            if (p) {
              pendingPanelRef.current = p
              setPanel(p)
            }
            void open(parsed.runId)
          } else {
            const step = consumeStepParam()
            if (step) {
              setFocusNodeId(step)
              setPanel('lineage')
            } else if (p) setPanel(p)
          }
        } else if (selectedRef.current) {
          clearSelection()
        }
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  /**
   * `?step=<node_id>` (Models → How it was made): read it once and drop it from
   * the address bar so later run switches don't re-apply it.
   */
  const consumeStepParam = (): string | null => {
    const step = parseStepParam(window.location.search)
    if (!step) return null
    window.history.replaceState(null, '', `${window.location.pathname}${searchWithoutStep(window.location.search)}`)
    return step
  }

  /** Drop the detail selection (e.g. "Back to runs" from a not-found run). */
  const clearSelection = () => {
    openSeqRef.current++
    selectedRef.current = null
    setSelected(null)
    setDetail(null)
    setStatus(null)
    setDebug(null)
    setOutputFiles([])
    setOutputsMeta({ truncated: false, byNode: {} })
    setExpandedNodeFiles({})
    setRunArtifacts([])
    setRunModels([])
    setRunModelRows(null)
    setNotFoundRunId(null)
    setFocusNodeId(null)
    setRunGraph(null)
    setAskAgentOpen(false)
    resetAuditPanels()
  }

  /** Close replay / verify / purge panels (run switch, delete). */
  const resetAuditPanels = () => {
    setReplayOpen(false)
    setReplayConflict(null)
    setVerifyResult(null)
    setPurgeOpen(false)
    setPurgeText('')
  }

  const open = async (requestedId: string) => {
    // `id` is rebound to the full run id once the detail resolves a short /
    // prefix id (/runs/96505918) — every later API call must use the full id.
    let id = requestedId
    const switching = selected !== id
    // Latest-request guard: a slower open(A) must never paint A's detail
    // under run B after the user switched selection.
    const seq = ++openSeqRef.current
    const stale = () => seq !== openSeqRef.current || selectedRef.current !== id
    selectedRef.current = id
    setSelected(id)
    setDetail(null)
    setDebug(null)
    setSamples(null)
    setRunModels([])
    setRunModelRows(null)
    setShowUntrained(false)
    setOutputFiles([])
    setOutputsMeta({ truncated: false, byNode: {} })
    setExpandedNodeFiles({})
    setRunArtifacts([])
    setSelectedOutputPath(null)
    // Deep link `?step=` focuses that step on Overview (path group opens, inline details shown).
    const urlStep = consumeStepParam()
    setFocusNodeId(urlStep)
    if (urlStep) {
      pendingPanelRef.current = 'lineage'
      setPanel('lineage')
    }
    setPromoteOpen(false)
    setPromoteCandidateId(null)
    setAskAgentOpen(false)
    if (switching) resetAuditPanels()
    if (switching) setRunGraph(null)
    setNotFoundRunId(null)
    focusSeededForRun.current = null
    setError(null)
    // Seed the landing panel immediately from the list row (before await) so the
    // URL effect does not briefly pin a stale Logs panel from the prior selection.
    if (switching && !pendingPanelRef.current) {
      const listSt = String(runs?.find((r) => r.run_id === id)?.status ?? '').toLowerCase()
      if (
        listSt.includes('fail') ||
        listSt === 'running' ||
        listSt === 'paused' ||
        listSt === 'cancelled' ||
        listSt === 'canceled'
      ) {
        setPanel('logs')
      } else if (listSt) {
        setPanel('lineage')
      }
    }
    try {
      // Detail first: a 404 here means the run doesn't exist (deleted, or a
      // stale deep link) — show one clear "not found" state, not a detail
      // panel full of UNKNOWN. One short retry covers a just-started async run
      // whose journal isn't on disk yet.
      let d: Record<string, unknown>
      try {
        d = await apiJson<Record<string, unknown>>(`/runs/${encodeURIComponent(id)}`)
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) throw err
        await new Promise((r) => setTimeout(r, 800))
        if (stale()) return
        try {
          d = await apiJson<Record<string, unknown>>(`/runs/${encodeURIComponent(id)}`)
        } catch (err2) {
          if (!(err2 instanceof ApiError && err2.status === 404)) throw err2
          if (stale()) return
          MISSING_RUN_IDS.add(id)
          setNotFoundRunId(id)
          setStatus(null)
          // Don't leave the header "Last run" chip pointing at a run that 404s.
          if (useAppStore.getState().lastRunId === id) setLastRunId(null)
          return
        }
      }
      if (stale()) return
      // Short-id deep link: adopt the full id (selection, URL via the
      // replaceState effect, header Last run) before any further request.
      const fullId = resolveFullRunId(id, d)
      if (fullId !== id) {
        const shortId = id
        id = fullId
        selectedRef.current = fullId
        setSelected(fullId)
        if (useAppStore.getState().lastRunId === shortId) setLastRunId(fullId)
      }
      const embedded = (d?.graph ?? (d?.meta as { graph?: unknown } | undefined)?.graph) as GraphIR | undefined
      // Empty edges[] still counts as Array.isArray — fetch the real graph so Lineage
      // can show from→to. Prefer embedded only when it has both nodes and edges.
      const embeddedUsable = Boolean(
        embedded &&
          Array.isArray(embedded.nodes) &&
          embedded.nodes.length > 0 &&
          Array.isArray(embedded.edges) &&
          embedded.edges.length > 0,
      )
      const [st, dbg, cps, outs, arts, g] = await Promise.all([
        apiJson<Record<string, unknown>>(`/runs/${id}/status`).catch(() => null),
        apiJson<Record<string, unknown>>(`/runs/${id}/debug-report`).catch(() => null),
        apiJson<string[]>(`/runs/${id}/checkpoints`).catch(() => []),
        fetchRunOutputs(id),
        apiJson<RunArtifact[]>(`/runs/${id}/artifacts`).catch(() => []),
        // Node list + edges (incl. nodes that never ran) come from the run's graph.
        embeddedUsable ? Promise.resolve(null) : fetchRunGraph(id, null).catch(() => null),
      ])
      if (stale()) return
      setRunGraph(g)
      setDetail(d)
      setStatus(st)
      setDebug(dbg)
      setCheckpoints(Array.isArray(cps) ? cps : [])
      setOutputFiles(outs.files)
      setOutputsMeta({ truncated: outs.truncated, byNode: outs.truncatedByNode })
      void loadRunModels(id)
      void loadRunModelRows(id)
      setRunArtifacts(Array.isArray(arts) ? arts : [])
      const meta = d?.meta && typeof d.meta === 'object' ? (d.meta as Record<string, unknown>) : null
      // Only pick a default panel when opening a different run (or a forced pending panel).
      // Reloading the same run must not yank the user off Logs / Outputs / Lineage.
      if (pendingPanelRef.current) {
        setPanel(normalizePanel(pendingPanelRef.current) || 'lineage')
        pendingPanelRef.current = null
      } else if (switching) {
        const stStr = String(st?.status ?? meta?.status ?? d?.status ?? '').toLowerCase()
        if (stStr.includes('fail') || stStr === 'running' || stStr === 'paused' || stStr === 'cancelled') {
          setPanel('logs')
        } else {
          setPanel('lineage')
        }
      }
    } catch (err) {
      if (stale()) return
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const selectedIsLive = (() => {
    if (!selected) return false
    const metaStatus = (detail?.meta as { status?: string } | undefined)?.status
    const s = String(status?.status ?? metaStatus ?? '').toLowerCase()
    return s === 'running' || s === 'paused' || isAwaitingApproval(s)
  })()
  usePolling(
    async () => {
      const id = selected
      if (!id) return
      const st = await apiJson<Record<string, unknown>>(`/runs/${encodeURIComponent(id)}/status`, { retries: 0 })
      // Selection changed while in flight — drop the stale result.
      if (selectedRef.current !== id) return
      setStatus(st)
      const norm = normalizeRunStatus(st?.status)
      if (norm === 'completed' || norm === 'failed' || norm === 'cancelled') {
        // Run just finished: refresh logs / outputs / artifacts for it.
        await refetchRunDetail(id)
      } else if (++livePollTickRef.current % 2 === 0) {
        // Live: refresh the journal every other tick so Logs and the step
        // progress bars (node_progress) move while training runs.
        try {
          const d = await apiJson<Record<string, unknown>>(`/runs/${encodeURIComponent(id)}`, { retries: 0 })
          if (selectedRef.current === id) setDetail(d)
        } catch {
          /* keep prior detail */
        }
      }
    },
    2000,
    { enabled: selectedIsLive, immediate: false, resetKey: selected },
  )

  const downloadZip = async () => {
    if (!selected) return
    try {
      const url = apiUrl(`/runs/${selected}/outputs/zip`)
      const token = getApiToken()
      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) throw new Error(`Download failed (${res.status})`)
      const truncated =
        (res.headers.get('X-Graphyn-Outputs-Zip-Truncated') || '').toLowerCase() === 'true'
      const countRaw = res.headers.get('X-Graphyn-Outputs-Zip-Count')
      const count = countRaw && /^\d+$/.test(countRaw) ? Number(countRaw) : null
      const blob = await res.blob()
      const obj = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = obj
      a.download = `${selected}-outputs.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(obj)
      if (truncated) {
        pushToast(
          count != null
            ? `Zip saved (${count} files in step folders) — some bulk files omitted (size/listing cap)`
            : 'Zip saved with step folders — some bulk files omitted (size/listing cap)',
          'info',
        )
      } else {
        pushToast(
          count != null
            ? `Zip downloaded (${count} files, one folder per step)`
            : 'Zip downloaded (one folder per step)',
          'success',
        )
      }
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const control = async (id: string, action: 'pause' | 'resume' | 'cancel') => {
    try {
      await apiJson(`/runs/${id}/${action}`, { method: 'POST' })
      pushToast(`${action} requested`, 'success')
      await load()
      await open(id)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const loadRunModels = async (runId: string) => {
    try {
      const res = await apiJson<{ models?: Array<{ name: string; stages?: Record<string, { run_id?: string; slug?: string; updated_at?: string }> }> }>('/models')
      if (selectedRef.current !== runId) return
      const list = Array.isArray(res?.models) ? res.models : []
      setAllModelStages(new Map(list.map((m) => [m.name, m.stages || {}])))
      setRunModels(
        list.filter((m) => {
          const stages = m.stages || {}
          return Object.values(stages).some((s) => s && String(s.run_id || '') === runId)
        }),
      )
    } catch {
      if (selectedRef.current === runId) setRunModels([])
    }
  }

  const refetchRunDetail = React.useCallback(async (id: string) => {
    try {
      const [d, st, dbg, cps, outs, arts] = await Promise.all([
        apiJson<Record<string, unknown>>(`/runs/${id}`),
        apiJson<Record<string, unknown>>(`/runs/${id}/status`).catch(() => null),
        apiJson<Record<string, unknown>>(`/runs/${id}/debug-report`).catch(() => null),
        apiJson<string[]>(`/runs/${id}/checkpoints`).catch(() => []),
        fetchRunOutputs(id),
        apiJson<RunArtifact[]>(`/runs/${id}/artifacts`).catch(() => []),
      ])
      if (selectedRef.current !== id) return
      setDetail(d)
      setStatus(st)
      setDebug(dbg)
      setCheckpoints(Array.isArray(cps) ? cps : [])
      setOutputFiles(outs.files)
      setOutputsMeta({ truncated: outs.truncated, byNode: outs.truncatedByNode })
      setExpandedNodeFiles({})
      setRunArtifacts(Array.isArray(arts) ? arts : [])
      void loadRunModels(id)
      void loadRunModelRows(id)
    } catch {
      /* keep prior detail on refresh failure */
    }
  }, [])

  React.useEffect(() => {
    if (!selected) {
      wasLiveRunRef.current = false
      return
    }
    const metaStatus = (detail?.meta as { status?: string } | undefined)?.status
    const normalized = normalizeRunStatus(status?.status ?? metaStatus)
    const live = isLiveRunStatus(normalized)
    if (wasLiveRunRef.current && !live && isTerminalRunStatus(normalized)) {
      void refetchRunDetail(selected)
      void load()
    }
    wasLiveRunRef.current = live
  }, [selected, status?.status, detail, refetchRunDetail, load])

  const promote = async (alias: 'latest' | 'staging' | 'prod' = promoteAlias) => {
    if (!selected) return
    try {
      const res = await apiJson<{ alias?: string; slug?: string }>(`/runs/${selected}/promote`, {
        method: 'POST',
        body: JSON.stringify({ alias }),
      })
      const a = res?.alias || alias
      pushToast(`Promoted to ${a}`, 'success')
      if (res?.slug && a === 'staging') {
        const name = String(res.slug).replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 48) || 'model'
        try {
          await apiJson('/models', {
            method: 'POST',
            body: JSON.stringify({
              name,
              run_id: selected,
              slug: res.slug,
              stage: 'staging',
            }),
          })
          pushToast(`Registered model ${name} in Staging`, 'success')
        } catch {
          /* registry optional if alias-only */
        }
      }
      await load()
      await open(selected)
      await loadRunModels(selected)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const registerModelFromRun = async () => {
    if (!selected) return
    const name = regModelName.trim()
    const opt = selectedModelOption
    const slug = regModelSlug.trim() || opt?.slug || runArtifactSlug || ''
    if (!name) {
      pushToast('Enter a model name', 'error')
      return
    }
    // Newer APIs derive the folder from model_path; older ones need the slug.
    if (!slug && !(opt && runModelRows)) {
      pushToast('Could not tell where this model is stored — open More options and enter the storage folder', 'error')
      return
    }
    setRegisterBusy(true)
    try {
      await apiJson('/models', {
        method: 'POST',
        body: JSON.stringify({
          name,
          run_id: selected,
          ...(slug ? { slug } : {}),
          stage: 'staging',
          // UX API: the exact model file chosen, so the registry never resolves
          // to the untrained architecture next to the trained model (older
          // APIs ignore these fields).
          ...(opt
            ? {
                model_path: opt.path,
                ...(opt.nodeId ? { node_id: opt.nodeId } : {}),
                ...(isUntrained(opt) ? { allow_untrained: true } : {}),
              }
            : {}),
        }),
      })
      pushToast(`Saved model “${name}” — find it under Models`, 'success', {
        actionLabel: 'Open Models',
        onAction: () => goView('models'),
      })
      setRegModelName('')
      setRegModelSlug('')
      await loadRunModels(selected)
    } catch (err) {
      const code = apiErrorCode(err)
      pushToast(
        code === 'compiled_untrained'
          ? 'That file is an untrained model (architecture only) — pick the trained model instead'
          : err instanceof Error
            ? err.message
            : String(err),
        'error',
      )
    } finally {
      setRegisterBusy(false)
    }
  }

  /** GET /runs/{id}/models — null when the API does not offer it (older server). */
  const loadRunModelRows = async (runId: string) => {
    try {
      const raw = await apiJson<unknown>(`/runs/${encodeURIComponent(runId)}/models`, { retries: 0 })
      if (selectedRef.current !== runId) return
      const rows = normalizeRunModels(raw)
      setRunModelRows(rows.length ? rows : null)
    } catch {
      if (selectedRef.current === runId) setRunModelRows(null)
    }
  }

  /** Real failure (node id + error text) for the selected run, or null. */
  const runFailure = React.useMemo(
    () =>
      extractRunFailure({
        events: Array.isArray(detail?.logs) ? (detail!.logs as Array<Record<string, unknown>>) : [],
        detail,
        status,
        debug,
      }),
    [detail, status, debug],
  )

  /**
   * "Ask agent to fix": creates a pending proposal (the run's graph + the real
   * failing node / error) in the Agent inbox for an agent to fill in. The
   * proposal graph is the run's unchanged graph — the agent supplies the fix.
   * Stays on this page; the toast offers "Open proposal".
   */
  const askAgentToFix = async () => {
    if (!selected) return
    const runId = selected
    setExplainBusy(true)
    try {
      const failure = runFailure
      const emb = (detail?.graph ?? (detail?.meta as { graph?: unknown } | undefined)?.graph) as
        | GraphIR
        | undefined
      const baseGraph =
        emb && Array.isArray(emb.nodes) && Array.isArray(emb.edges)
          ? emb
          : runGraph && Array.isArray(runGraph.nodes)
            ? runGraph
            : emptyGraph(`fix-${shortRunId(runId)}`)
      const errorLine = failure?.error ? failure.error.slice(0, 1000) : 'No error message was recorded'
      const graph = {
        schema_version: baseGraph.schema_version || '1.1',
        nodes: Array.isArray(baseGraph.nodes) ? baseGraph.nodes : [],
        edges: Array.isArray(baseGraph.edges) ? baseGraph.edges : [],
        parameters: baseGraph.parameters || {},
        metadata: {
          ...(baseGraph.metadata || {}),
          name: baseGraph.metadata?.name || `fix-${shortRunId(runId)}`,
          seed: baseGraph.metadata?.seed ?? 42,
          description: `Fix failed run ${runId}${failure?.nodeId ? ` — node ${failure.nodeId}` : ''}: ${errorLine}`,
          created_at: baseGraph.metadata?.created_at ?? null,
          tags: [...(baseGraph.metadata?.tags || []), 'explain-failure'],
          from_run: runId,
          failed_node: failure?.nodeId ?? null,
          failure_error: errorLine,
        },
      }
      const created = await apiJson<{ id?: string }>('/proposals', {
        method: 'POST',
        body: JSON.stringify({
          summary: failureProposalSummary(runId, failure),
          graph,
          actor: 'ui-explain-failure',
        }),
      })
      setAskAgentOpen(false)
      const pid = created?.id ? String(created.id) : ''
      pushToast('Sent to Agent inbox — an agent can now propose a fix', 'success', {
        actionLabel: 'Open proposal',
        onAction: () => openProposals(pid ? { id: pid } : {}),
        ttlMs: 15000,
      })
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setExplainBusy(false)
    }
  }

  /**
   * Audit API present (record / record_status on GET /runs/{id})? On that API
   * DELETE /runs/{id} archives; on an older container DELETE still hard-deletes,
   * so Archive is only offered when the new contract is detected.
   */
  const auditApi = Boolean(detail && ('record_status' in detail || 'record' in detail))

  const dropSelectionAfterRemove = async (runId: string) => {
    if (useAppStore.getState().lastRunId === runId) setLastRunId(null)
    clearSelection()
    if (activeProject) window.history.replaceState(null, '', paths.runs(activeProject))
    await load()
  }

  /** Archive (default): hidden from lists, record + files kept, audited. */
  const archiveRun = async () => {
    if (!selected || !auditApi) return
    const runId = selected
    setArchiveBusy(true)
    try {
      await apiJson(`/runs/${encodeURIComponent(runId)}`, { method: 'DELETE' })
      pushToast(`Archived run ${shortRunId(runId)} — its record and files are kept`, 'success', {
        actionLabel: 'Undo',
        onAction: () => void restoreRun(runId),
        ttlMs: 12000,
      })
      if (showArchived) {
        await load()
        await refetchRunDetail(runId)
      } else {
        await dropSelectionAfterRemove(runId)
      }
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setArchiveBusy(false)
    }
  }

  const restoreRun = async (runId: string) => {
    try {
      await apiJson(`/runs/${encodeURIComponent(runId)}/restore`, { method: 'POST' })
      pushToast(`Restored run ${shortRunId(runId)}`, 'success')
      await load()
      if (selectedRef.current === runId) await refetchRunDetail(runId)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  /** Hard delete — typed confirmation (full run id) in the advanced menu. */
  const purgeRun = async () => {
    if (!selected) return
    const runId = selected
    if (purgeText.trim() !== runId) return
    setArchiveBusy(true)
    try {
      if (auditApi) {
        await apiJson(`/runs/${encodeURIComponent(runId)}`, {
          method: 'DELETE',
          query: { purge: true },
          headers: { 'X-Confirm-Purge': runId },
        })
      } else {
        // Older API: DELETE is the (only) hard delete.
        await apiJson(`/runs/${encodeURIComponent(runId)}`, { method: 'DELETE' })
      }
      pushToast(`Permanently deleted run ${shortRunId(runId)}`, 'success')
      MISSING_RUN_IDS.add(runId)
      await dropSelectionAfterRemove(runId)
    } catch (err) {
      const code = apiErrorCode(err)
      pushToast(
        code === 'confirm_required'
          ? 'The server needs the full run id to confirm a permanent delete'
          : err instanceof Error
            ? err.message
            : String(err),
        'error',
      )
    } finally {
      setArchiveBusy(false)
    }
  }

  /** Replay exactly: POST /runs/{id}/replay (inputs checked; 409 → diff + Replay anyway). */
  const replayRun = async (force: boolean) => {
    if (!selected) return
    const runId = selected
    setReplayBusy(true)
    try {
      const res = await apiJson<Record<string, unknown>>(`/runs/${encodeURIComponent(runId)}/replay`, {
        method: 'POST',
        body: JSON.stringify({ check_inputs: true, force }),
      })
      const newId = replayRunId(res)
      setReplayOpen(false)
      setReplayConflict(null)
      pushToast(newId ? `Replay started — run ${shortRunId(newId)}` : 'Replay started', 'success')
      await load()
      if (newId && selectedRef.current === runId) {
        pushNextUrlRef.current = true
        pendingPanelRef.current = 'logs'
        void open(newId)
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setReplayConflict(parseReplayConflict(err.body))
      } else if (err instanceof ApiError && (err.status === 404 || err.status === 405) && !auditApi) {
        pushToast('This server version cannot replay runs yet', 'info')
      } else {
        pushToast(err instanceof Error ? err.message : String(err), 'error')
      }
    } finally {
      setReplayBusy(false)
    }
  }

  /** Verify: GET /runs/{id}/verify → checklist (graph snapshot, inputs, outputs, record hash/chain). */
  const verifyRun = async () => {
    if (!selected) return
    const runId = selected
    setVerifyBusy(true)
    try {
      // POST records the verify (who/when) server-side; older APIs only have GET (405 → retry).
      const verifyPath = `/runs/${encodeURIComponent(runId)}/verify`
      let raw: Record<string, unknown>
      try {
        raw = await apiJson<Record<string, unknown>>(verifyPath, {
          method: 'POST',
          body: JSON.stringify({}),
          timeoutMs: 300_000,
          retries: 0,
        })
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 405)) throw err
        raw = await apiJson<Record<string, unknown>>(verifyPath, { timeoutMs: 300_000, retries: 0 })
      }
      if (selectedRef.current !== runId) return
      const v = normalizeVerify(raw)
      const last = parseLastVerify(raw)
      const hc = Number(raw?.history_count)
      setVerifyResult({
        runId,
        ok: v.ok,
        status: v.status,
        verifiedAt: String(raw?.checked_at ?? raw?.verified_at ?? new Date().toISOString()),
        groups: groupVerify(v.items),
        counts: parseVerifyCounts(raw?.summary),
        actor:
          last && last.actor
            ? { name: last.actor, verified: last.actorVerified, claimed: last.claimedActor }
            : null,
        historyCount: Number.isFinite(hc) ? hc : null,
        last: last ? { ...last, ok: last.ok ?? v.ok } : null,
      })
      // Keep the list row's verified tick and the detail's last_verify in step without a reload.
      if (last) {
        const lv = {
          checked_at: last.checkedAt,
          actor: last.actor,
          actor_verified: last.actorVerified,
          ok: last.ok ?? v.ok,
          status: last.status,
          passed: last.passed,
          total: last.total,
        }
        setRuns((prev) => (prev ? prev.map((r) => (r.run_id === runId ? { ...r, last_verify: lv } : r)) : prev))
        setDetail((prev) => (prev && selectedRef.current === runId ? { ...prev, last_verify: lv } : prev))
      }
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 405) && !auditApi) {
        pushToast('This server version cannot verify runs yet', 'info')
      } else {
        pushToast(err instanceof Error ? err.message : String(err), 'error')
      }
    } finally {
      setVerifyBusy(false)
    }
  }

  const loadCheckpointSamples = async (nodeId: string) => {
    if (!selected) return
    try {
      setSamples(
        await apiJson(`/runs/${selected}/checkpoints/${encodeURIComponent(nodeId)}/samples`, {
          query: { n: 10 },
        }),
      )
      setPanel('checkpoints')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const runStatus = String(
    status?.status ??
      (detail?.meta as { status?: string } | undefined)?.status ??
      runs?.find((r) => r.run_id === selected)?.status ??
      'unknown',
  )
  const logs = Array.isArray(detail?.logs) ? (detail!.logs as Array<Record<string, unknown>>) : []
  const baseLogRows: FormattedLogRow[] = logs.map((l, i) => {
    const raw = typeof l.message === 'string' ? l.message : JSON.stringify(l)
    const line = formatExecutionLine(raw)
    const nodeHint = extractLogNodeHint(l, line.text, raw)
    const failed = line.level === 'error' || String(l.level).toUpperCase() === 'ERROR'
    const clock = extractLogTimestamp(l, raw)
    let ev: Record<string, unknown> = l
    if (typeof l.message === 'string' && l.message.trim().startsWith('{')) {
      try {
        const inner = JSON.parse(l.message) as unknown
        if (inner && typeof inner === 'object' && !Array.isArray(inner)) ev = { ...l, ...(inner as Record<string, unknown>) }
      } catch {
        /* plain text */
      }
    }
    return { i, l, ev, line: { ...line, raw: JSON.stringify(l) }, nodeHint, failed, clock }
  })
  // Pretty: one live line per node for node_progress (latest + history), Mode B
  // Waiting heartbeats collapsed to one line with "....", then drop the
  // pipeline-level error row that restates the preceding node_error.
  // Raw: every event as recorded.
  const formattedLogs: FormattedLogRow[] = rawLogView
    ? baseLogRows
    : dedupeErrorRows(
        skipConsecutiveByText(
          collapseWaitingRows(
            collapseProgressRows(baseLogRows, (row) => row.l),
            (row) => row.line.text,
          ).map((c) =>
            c.kind === 'progress'
              ? {
                  ...c.row,
                  nodeHint: c.progress.nodeId,
                  progress: { latest: c.progress, history: c.history, count: c.count },
                }
              : c.kind === 'waiting'
                ? {
                    ...c.row,
                    waiting: { text: c.text, count: c.count },
                  }
                : c.row,
          ),
          (row) =>
            row.progress
              ? `progress:${row.progress.latest.nodeId}:${row.progress.count}`
              : row.waiting
                ? `waiting:${row.waiting.text}:${row.waiting.count}`
                : row.line.text,
        ),
        (row) => row.line.text,
        (row) => (row.failed ? 'error' : row.line.level),
      )



  React.useEffect(() => {
    if (!focusNodeId || panel !== 'checkpoints' || !selected) return
    const hit = checkpoints.find((c) => focusMatchesNode(focusNodeId, c))
    if (hit) void loadCheckpointSamples(hit)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusNodeId, panel, checkpoints, selected])

  const visibleLogs = focusNodeId
    ? formattedLogs.filter((row) => focusMatchesNode(focusNodeId, row.nodeHint))
    : formattedLogs

  const selectedSummary = runs?.find((r) => r.run_id === selected)
  const detailMeta =
    detail?.meta && typeof detail.meta === 'object' ? (detail.meta as Record<string, unknown>) : null
  /** Last verify: this session's Verify response, else GET /runs/{id} / list row `last_verify`. */
  const headerLastVerify: LastVerify | null =
    (verifyResult && verifyResult.runId === selected ? verifyResult.last : null) ??
    lastVerifyOf(detail) ??
    lastVerifyOf(selectedSummary)
  /** Who started the selected run (record → meta → detail) + identity proof. */
  const runActor = (() => {
    const pv = (pickProve(detail) ?? {}) as Record<string, unknown>
    const srcs = [pv, detailMeta ?? {}, (detail ?? {}) as Record<string, unknown>]
    const pick = (k: string) => {
      for (const o of srcs) {
        const v = o[k]
        if (typeof v === 'string' && v.trim()) return v.trim()
      }
      return ''
    }
    const verifiedRaw = srcs.map((o) => o.actor_verified).find((v) => typeof v === 'boolean')
    return {
      name: pick('actor'),
      verified: typeof verifiedRaw === 'boolean' ? verifiedRaw : null,
      claimed: pick('claimed_actor'),
    }
  })()
  const runNodeStats = (
    Array.isArray(debug?.node_stats)
      ? debug.node_stats
      : Array.isArray(selectedSummary?.node_stats)
        ? selectedSummary.node_stats
        : Array.isArray(detailMeta?.node_stats)
          ? detailMeta.node_stats
          : []
  ) as Array<Record<string, unknown>>
  const runWorkerMap =
    (detailMeta?.distributed_node_workers as Record<string, string> | undefined) ||
    (status as { distributed_node_workers?: Record<string, string> } | null)?.distributed_node_workers ||
    null
  const runWorkerEntries: Array<[string, string]> =
    runWorkerMap && typeof runWorkerMap === 'object' ? Object.entries(runWorkerMap) : []
  const runMetrics = (selectedSummary?.metrics ?? detailMeta?.metrics ?? null) as
    | Record<string, unknown>
    | null
  const showCheckpointsTab =
    checkpoints.length > 0 || isLiveRunStatus(runStatus) || panel === 'checkpoints'
  const detailPanelOptions = (
    ['lineage', 'artifacts', 'logs', 'checkpoints'] as const
  ).filter((p) => p !== 'checkpoints' || showCheckpointsTab)
  const sourceRunId = String(
    (detail?.meta as { source_run_id?: string } | undefined)?.source_run_id ??
      detail?.source_run_id ??
      '',
  ).trim()
  const graphName = String(
    selectedSummary?.graph_name ??
      (detail?.meta as { graph_name?: string } | undefined)?.graph_name ??
      detail?.graph_name ??
      '',
  ).trim()
  const headerTitle = runTitle(
    detail ? { ...(selectedSummary || {}), ...detail, run_id: selected } : selectedSummary ?? { run_id: selected },
  )
  const embeddedGraph = (detail?.graph ?? (detail?.meta as { graph?: unknown } | undefined)?.graph) as
    | GraphIR
    | undefined
  const stackGraph =
    embeddedGraph &&
    Array.isArray(embeddedGraph.nodes) &&
    embeddedGraph.nodes.length > 0 &&
    Array.isArray(embeddedGraph.edges) &&
    embeddedGraph.edges.length > 0
      ? embeddedGraph
      : runGraph
  // Promote only when this run actually wrote a model artifact — a graph is a
  // workflow; trainers/metrics alone do not imply something to stage.
  const runProducedModel = runHasModelOutput({
    files: outputFiles,
    artifacts: runArtifacts,
    metrics: (selectedSummary?.metrics ?? detailMeta?.metrics ?? null) as Record<string, unknown> | null,
    nodeStats: runNodeStats,
    // Registered models whose stage points at this run (rows from /runs/{id}/models
    // are candidates, not registrations — their kinds gate trained vs untrained).
    registeredModels: runModels.length,
    modelKinds: runModelRows ? runModelRows.map((r) => r.kind) : null,
    graphNodeTypes: Array.isArray(stackGraph?.nodes)
      ? stackGraph.nodes.map((n) => (n as { node_type?: string }).node_type)
      : null,
    graphName,
  })
  /** Ship / deploy package run — its output is a package, not a model. */
  const packageRun = isPackageRun({
    graphNodeTypes: Array.isArray(stackGraph?.nodes)
      ? stackGraph.nodes.map((n) => (n as { node_type?: string }).node_type)
      : null,
    artifacts: runArtifacts,
    graphName,
  })
  /**
   * Node list for the run: every graph node in execution order (so a node that
   * never ran after a failure still shows, numbered correctly), status from
   * journal events → node_stats; not-run on a failed/cancelled run → skipped.
   * Nodes only seen in artifacts / outputs (no graph available) are appended.
   */
  const rawStackItems = (() => {
    const items = pipelineNodesFromRun({
      graph: stackGraph as Parameters<typeof pipelineNodesFromRun>[0]['graph'],
      nodeStats: runNodeStats,
      events: logs,
      runStatus,
      disambiguate: false,
    }).map((n) => ({ id: n.id, label: n.label, nodeType: n.nodeType, status: n.status }))
    const seen = new Set(items.map((i) => i.id))
    const push = (raw?: unknown) => {
      const id = String(raw || '').trim()
      if (!id || seen.has(id) || looksLikeOpaqueId(id) || id === 'run') return
      seen.add(id)
      // Base label only — disambiguateByPath adds "· Path B" for duplicates.
      items.push({ id, label: humanNodeLabel(id), nodeType: undefined, status: undefined })
    }
    for (const a of runArtifacts) push(a.node_id || a.node_type)
    for (const f of outputFiles) {
      const g = guessNodeFromPath(f.path, runArtifacts, f, { runId: selected })
      if (g !== 'run') push(g)
    }
    return items
  })()

  /** Fork/parallel shape from the graph edges (before deciding whether it is an ML multi-path run). */
  const rawShape = computePipelineShape(
    rawStackItems.map((i) => i.id),
    stackGraph && Array.isArray(stackGraph.edges) ? stackGraph.edges : null,
  )
  const graphNodeList = (Array.isArray(stackGraph?.nodes) ? stackGraph!.nodes : []) as Array<{
    id?: unknown
    node_type?: unknown
    label?: unknown
    on_error?: unknown
  }>
  const nodeTypeOfId = (id: string): string | null =>
    String(graphNodeList.find((n) => String(n?.id ?? '') === id)?.node_type ?? '') ||
    rawStackItems.find((i) => i.id === id)?.nodeType ||
    null

  // ── Results (backend summary, else evaluator metrics.json fallback) ──
  const backendPaths = (() => {
    const fromDetail = pathsFromSummary(detail)
    return fromDetail.length ? fromDetail : pathsFromSummary(selectedSummary)
  })()
  const resultsFor = (shape: typeof rawShape): PathResult[] => {
    if (backendPaths.length === 0) {
      return fallbackPathResults({
        shape,
        graphNodes: (stackGraph?.nodes as Parameters<typeof fallbackPathResults>[0]['graphNodes']) ?? null,
        metricsByNode: evaluatorOutputs.metricsByNode,
      })
    }
    // Backend paths: note which node produced the metrics (for the step story).
    return backendPaths.map((p) => {
      if (p.metricsNodeId) return p
      const hit = p.nodeIds.filter((id) => evaluatorOutputs.metricsByNode[id] != null).pop()
      return hit ? { ...p, metricsNodeId: hit } : p
    })
  }
  const rawPathResults = resultsFor(rawShape)
  /**
   * Path A… grouping only for ML-style multi-path runs (≥2 paths with metrics,
   * or ≥2 branches that train / evaluate). Workflow fan-out (if_switch /
   * approvals / error branches) reads as one ordered step list.
   */
  const mlMultiPath = isMlMultiPath({ shape: rawShape, paths: rawPathResults, nodeTypeOf: nodeTypeOfId })
  const pipelineShape = mlMultiPath ? rawShape : computePipelineShape(rawStackItems.map((i) => i.id), null)
  // Backend `summary.paths` can list workflow sinks too — only keep Path chrome / best-path
  // metrics when this run is ML multi-path.
  const pathResults: PathResult[] = mlMultiPath ? rawPathResults : resultsFor(pipelineShape)
  const bestPath = pickBestPath(pathResults, bestPathIdFromSummary(detail) ?? bestPathIdFromSummary(selectedSummary))
  const runPrimary = primaryMetric(detail) ?? primaryMetric(selectedSummary) ?? bestPath?.primary ?? null
  // Overview Metrics box: best path on multi-path runs (matches the results banner).
  const overviewMetricsView = overviewMetrics({
    runMetrics,
    paths: pathResults,
    backendBest: bestPathIdFromSummary(detail) ?? bestPathIdFromSummary(selectedSummary),
  })
  const lanePaths = lanePathMap(pipelineShape, pathResults)
  const nodePaths = pathOfNodeMap(
    pathResults,
    isMultiTrackShape(pipelineShape) ? pipelineShape.laneOf : null,
  )
  for (const [id, lane] of pipelineShape.laneOf) {
    const p = lanePaths.get(lane)
    if (p && lane !== 'shared' && !nodePaths.has(id)) nodePaths.set(id, p)
  }
  const multiPath = isMultiTrackShape(pipelineShape) && pathResults.length > 1
  /** Backend path-aware labels (meta.node_labels / record / node_stats[].node_label). */
  const backendNodeLabels = nodeLabelsFromRun(detail, runNodeStats)
  /** Plugin catalog label for a node type ("IF Switch", "HTTP Request"). */
  const catalogTypeLabel = (nodeType: string): string =>
    nodeCatalog.find((n) => n.node_type === nodeType)?.label || humanNodeLabel(nodeType)
  /** Workflow step names: IR label → node id (shared type) → catalog type label. */
  const stepNames = stepDisplayNames(graphNodeList, catalogTypeLabel)
  /** Non-ML runs: never "Http request · Path C" — IR label / id / catalog label instead. */
  const flowLabel = (id: string): string | undefined => {
    const n = stepNames.get(id)
    if (n) return n.title
    const b = backendNodeLabels.get(id)
    return b ? stripPathSuffix(compactNodeLabel(b)) : undefined
  }
  const pipelineStackItems = disambiguateByPath(rawStackItems, (id) => {
    if (!multiPath) return null
    const p = nodePaths.get(id)
    return p ? `Path ${p.letter}` : null
  }).map(({ id, label, status }) => {
    if (!mlMultiPath) return { id, label: flowLabel(id) ?? label, status }
    const b = backendNodeLabels.get(id)
    return { id, label: b ? compactNodeLabel(b) : label, status }
  })
  /** node id → step label for logs / stories / registry ids (backend label first on ML runs). */
  const stepLabel = (id: string): string | undefined => {
    if (!mlMultiPath) return flowLabel(id) ?? pipelineStackItems.find((it) => it.id === id)?.label
    const b = backendNodeLabels.get(id)
    if (b) return compactNodeLabel(b)
    return pipelineStackItems.find((it) => it.id === id)?.label
  }
  /** Workflow context for the step list: branch taken, skip reasons. */
  const flowBranching = branchingNodesOf(graphNodeList)
  const branchContext = branchContextByNode(
    (Array.isArray(stackGraph?.edges) ? stackGraph!.edges : []) as Parameters<typeof branchContextByNode>[0],
    { branchingNodes: flowBranching.branching, errorPorts: flowBranching.errorPorts },
  )
  const skipReasons = skipReasonsByNode(logs)
  const nodeTypeLabel = catalogTypeLabel
  /** Cached steps → the run whose outputs were reused (`cache_source_run_id`). */
  const cacheSources = cacheSourcesFromNodeStats(
    runNodeStats,
    (pickProve(detail) as { cache?: unknown } | null)?.cache,
  )
  const stepFailures = failuresByNode(logs)
  const stepResilience = React.useMemo(() => resilienceByNode(detail?.logs), [detail?.logs])
  const replayOf = replayOfRun(detail) || replayOfRun(selectedSummary)
  const selectedArchived = isArchivedRun(detail) || isArchivedRun(selectedSummary)
  const runDataset = datasetFromRun({
    run: detail ?? selectedSummary,
    events: logs,
    graphNodes: (stackGraph?.nodes as Parameters<typeof datasetFromRun>[0]['graphNodes']) ?? null,
  })
  /**
   * Regression line: only against earlier runs of the SAME pipeline (graph name)
   * and path count. A backend regression whose previous run is not comparable
   * (or not loaded) is replaced by the best comparable run, else hidden.
   */
  const runRegression: RegressionView | null = (() => {
    if (!selected || !runPrimary) return null
    const reg = regressionOf(detail) ?? regressionOf(selectedSummary)
    const backend: RegressionView | null = reg
      ? {
          delta: reg.delta,
          previousValue: reg.previousValue,
          previousRunId: reg.previousRunId,
          metricName:
            String(
              ((detail?.regression ?? detailMeta?.regression ?? selectedSummary?.regression) as { metric?: unknown } | undefined)
                ?.metric ?? '',
            ) || runPrimary.name,
        }
      : null
    return comparableRegression({
      runId: selected,
      graphName,
      pathCount: mlMultiPath ? (backendPaths.length || pathResults.length || null) : null,
      createdAt:
        (selectedSummary?.created_at as string | undefined) ??
        (detailMeta?.created_at as string | undefined) ??
        null,
      current: runPrimary,
      backend,
      rows: (runs || []) as Array<Record<string, unknown>>,
      metricOf: (row) => primaryMetric(row),
    })
  })()
  /**
   * Live per-node progress: journal node_progress events, then the latest-per-
   * node map on GET /runs/{id} and the 2 s /status poll (`node_progress`),
   * minus nodes that already finished.
   */
  const liveProgress: Map<string, NodeProgress> = (() => {
    if (!isLiveRunStatus(runStatus)) return new Map<string, NodeProgress>()
    const latest = latestProgressByNode(logs)
    for (const src of [detail?.node_progress, detailMeta?.node_progress, status?.node_progress]) {
      if (!src || typeof src !== 'object' || Array.isArray(src)) continue
      for (const [nid, ev] of Object.entries(src as Record<string, unknown>)) {
        const p = parseProgress(ev && typeof ev === 'object' ? { type: 'node_progress', node_id: nid, ...(ev as object) } : null)
        if (p) latest.set(p.nodeId, p)
      }
    }
    for (const id of finishedNodeIds(logs)) latest.delete(id)
    for (const it of rawStackItems) {
      if (it.status && it.status !== 'running' && it.status !== 'pending') latest.delete(it.id)
    }
    return latest
  })()

  /** Node(s) executing now — journal statuses first, backend current_node only as fallback. */
  const runningNow: RunningNode[] = isLiveRunStatus(runStatus)
    ? runningNodesOf(pipelineStackItems, {
        currentNode: status?.current_node,
        pathOf: (id) => {
          if (!multiPath) return null
          const p = nodePaths.get(id)
          return p ? `Path ${p.letter}` : null
        },
      })
    : []

  const runningNowKey = runningNow.map((r) => r.id).join('|')
  React.useEffect(() => {
    // Only seed Focus while the run is live — on completed runs that would
    // leave the last node selected and hide most Logs / Outputs. Seed from the
    // node actually running (not the backend current_node, which can name the
    // last finished step), and only when exactly one runs — parallel paths
    // keep the whole-run view so no running step's logs are hidden.
    if (!selected || focusSeededForRun.current === selected) return
    if (!isLiveRunStatus(runStatus)) {
      focusSeededForRun.current = selected
      return
    }
    if (runningNowKey === '' || runningNowKey.includes('|')) return
    setFocusNodeId(runningNowKey)
    focusSeededForRun.current = selected
  }, [runningNowKey, selected, runStatus])

  /** Compact step dropdown for Logs / Run outputs / Checkpoints. */
  const stepOptions = stepPickerOptions(
    pipelineStackItems,
    isMultiTrackShape(pipelineShape) ? pipelineShape.laneOf : null,
  )
  const focusLabel = focusNodeId
    ? pipelineStackItems.find((i) => focusMatchesNode(focusNodeId, i.id))?.label ||
      displayNodeLabel(focusNodeId, { withCue: true })
    : ''

  const modelCandidates = React.useMemo(() => {
    if (!runProducedModel) return [] as RunModelCandidate[]
    const labelFor = (nodeId: string) =>
      pipelineStackItems.find((i) => focusMatchesNode(nodeId, i.id))?.label
    // Stamp node_id on files via guess when missing so dual trainers split.
    const files = outputFiles.map((f) => ({
      ...f,
      node_id:
        f.node_id ||
        (() => {
          const g = guessNodeFromPath(f.path, runArtifacts, f, { runId: selected })
          return g === 'run' ? undefined : g
        })(),
    }))
    return listRunModelCandidates({ files, artifacts: runArtifacts, labelFor })
  }, [runProducedModel, outputFiles, runArtifacts, pipelineStackItems, selected])

  /** Run-wide pack slug from meta (fallback when a branch path has no pack). */
  const runArtifactSlug = React.useMemo(() => {
    const dir =
      (typeof detail?.artifacts_dir === 'string' && detail.artifacts_dir) ||
      ((detail?.meta as { artifacts_dir?: string } | undefined)?.artifacts_dir) ||
      ''
    return artifactSlugFromPath(String(dir)) || ''
  }, [detail])

  /**
   * Register options: GET /runs/{id}/models when the API has it, else model
   * files discovered in Run outputs. Each gets its path (A/B), kind
   * (trained / optimized / untrained) and that path's metrics.
   */
  const graphNodeTypeOf = (id?: string) =>
    id
      ? String(
          ((stackGraph?.nodes as Array<{ id?: unknown; node_type?: unknown }> | undefined) || []).find(
            (n) => String(n.id) === id,
          )?.node_type ?? '',
        ) || undefined
      : undefined
  const modelOptions: ModelOption[] = (() => {
    const fill = (o: ModelOption): ModelOption => {
      const p =
        (o.pathId ? pathResults.find((x) => x.pathId === o.pathId) : undefined) ||
        (o.nodeId ? nodePaths.get(o.nodeId) : undefined)
      return {
        ...o,
        pathId: o.pathId ?? p?.pathId,
        pathLabel: multiPath && p ? pathDisplayName(p) : o.pathLabel,
        // Path metrics describe the trained model only — never an untrained
        // (architecture-only) or converted artifact, even if the API copied them.
        metrics:
          o.kind !== 'trained' && o.kind !== 'unknown'
            ? {}
            : Object.keys(o.metrics).length || !p
              ? o.metrics
              : p.metrics,
      }
    }
    if (runModelRows && runModelRows.length > 0) return runModelRows.map(fill)
    return modelCandidates.map((c) => {
      const path = c.pathHint || c.id.replace(/^file:/, '')
      const nodeType = graphNodeTypeOf(c.nodeId)
      return fill({
        id: c.id,
        path,
        nodeId: c.nodeId,
        nodeType,
        kind: guessModelKind(path, nodeType || c.nodeId?.replace(/_[0-9a-f]+$|_\d+$/i, '')),
        metrics: {},
        labels: [],
        slug: c.artifactSlug,
      })
    })
  })()
  const rankedModelOptions = rankModelOptions(modelOptions, bestPath?.pathId)
  const untrainedCount = rankedModelOptions.filter(isUntrained).length
  const visibleModelOptions = showUntrained
    ? rankedModelOptions
    : rankedModelOptions.filter((o) => !isUntrained(o))
  const selectedModelOption =
    modelOptions.find((o) => o.id === promoteCandidateId) || defaultModelOption(modelOptions, bestPath?.pathId)
  const modelOptionsKey = modelOptions.map((o) => o.id).join('|')

  const applyModelOption = (o: ModelOption) => {
    setPromoteCandidateId(o.id)
    const p = (o.pathId ? pathResults.find((x) => x.pathId === o.pathId) : undefined) || (o.nodeId ? nodePaths.get(o.nodeId) : undefined)
    setRegModelName(suggestModelName(o, graphName || 'model', (p?.description || '').split(' · ')[0] || (multiPath && p ? `path-${p.letter}` : '')))
    // POST /models slug must be the workspace pack (speech-commands, optimized),
    // not the node id — register looks up artifacts/<slug>/runs/<run_id>.
    setRegModelSlug(o.slug || runArtifactSlug || '')
  }
  const applyModelOptionRef = React.useRef(applyModelOption)
  applyModelOptionRef.current = applyModelOption

  // Default selection when the form opens: best path's trained model — never untrained.
  React.useEffect(() => {
    if (!promoteOpen || !modelOptionsKey) return
    if (promoteCandidateId && modelOptionsKey.split('|').includes(promoteCandidateId)) return
    const def = defaultModelOption(modelOptions, bestPath?.pathId)
    if (def) applyModelOptionRef.current(def)
    // modelOptionsKey captures the option list
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [promoteOpen, modelOptionsKey, promoteCandidateId, bestPath?.pathId])

  const canOpenGraph = Boolean(
    selected &&
      (graphName ||
        (stackGraph && Array.isArray(stackGraph.nodes) && stackGraph.nodes.length > 0)),
  )

  const openGraphInBuilder = async () => {
    if (!selected) return
    try {
      // The Editor's linked run becomes this run, so its execution log and
      // node statuses hydrate from this run's journal.
      setLastRunId(selected)
      if (stackGraph && Array.isArray(stackGraph.nodes) && stackGraph.nodes.length > 0) {
        // Run-scoped write folders (…/runs/<id>/<node>/) are removed so a re-run
        // never writes into this run's folder; the Editor compares against the
        // recorded graph.json (drift banner).
        loadGraphIntoBuilder(unscopeRunPaths(stackGraph, selected), { fromRunId: selected })
        pushToast('Opened this run’s graph in the Editor', 'success')
        return
      }
      const graph = await fetchRunGraph(selected, graphName || null)
      if (!graph) {
        pushToast(graphName ? `Graph not found for ${graphName}` : 'Graph not available for this run', 'info')
        return
      }
      loadGraphIntoBuilder(unscopeRunPaths(graph, selected), { fromRunId: selected })
      pushToast(
        graphName ? `Opened ${humanizeTemplateName(graphName)} in Editor` : 'Opened graph in Editor',
        'success',
      )
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const filteredRuns = React.useMemo(() => {
    if (!runs) return null
    const q = nameQuery.trim().toLowerCase()
    const statusNeedle = statusFilter === 'all' ? '' : statusFilter.toLowerCase()
    const metricKey = metricName.trim()
    const minRaw = metricMin.trim()
    const minVal = minRaw === '' ? null : Number(minRaw)
    return runs.filter((r) => {
      if (activeProject && !runMatchesProject(r, activeProject)) return false
      if (!showArchived && isArchivedRun(r)) return false
      if (statusNeedle && !statusMatchesFilter(r.status, statusNeedle)) return false
      if (q) {
        const rawName = String(r.graph_name ?? '')
        const rr = r as unknown as { trigger?: unknown; actor?: unknown; meta?: { trigger?: unknown } }
        const trigger = String(rr.trigger ?? rr.meta?.trigger ?? '')
        // `trigger:webhook` / `trigger:schedule` and the actor are searchable too.
        const hay = `${rawName} ${runDisplayName(r)} ${r.run_id} ${trigger ? `trigger:${trigger}` : ''} ${String(rr.actor ?? '')}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      if (metricKey) {
        const num = metricNumeric(r.metrics as Record<string, unknown> | undefined, metricKey)
        if (num == null) return false
        if (minVal != null && Number.isFinite(minVal) && num < minVal) return false
      }
      return true
    })
  }, [runs, statusFilter, nameQuery, activeProject, metricName, metricMin, showArchived])

  const filtersActive =
    statusFilter !== 'all' || nameQuery.trim() !== '' || metricName.trim() !== ''
  // Only when the user's filters are what hides it: the run exists (loaded
  // here and in this page of the list) and a filter excludes it. A 404'd run
  // or one on another page is not "hidden by filters".
  const selectedHiddenByFilters = Boolean(
    filtersActive &&
      selected &&
      notFoundRunId !== selected &&
      runs?.some((r) => r.run_id === selected) &&
      filteredRuns &&
      !filteredRuns.some((r) => r.run_id === selected),
  )

  const clearRunFilters = React.useCallback(() => {
    setStatusFilter('all')
    setNameQuery('')
    setMetricName('')
    setMetricMin('')
  }, [])

  // Active filter + nothing selected → auto-follow newest in-flight run.
  React.useEffect(() => {
    if (statusFilter !== 'active' || selected || !filteredRuns?.length) return
    const first = filteredRuns.find((r) => isLiveStatus(r.status))
    if (first) void open(first.run_id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, filteredRuns, selected])

  // Land on Runs with no deep-link / focus → open the newest visible run once.
  // Survives filter changes until the user explicitly clears selection (Back).
  const didAutoSelectRef = React.useRef(false)
  React.useEffect(() => {
    didAutoSelectRef.current = false
  }, [activeProject])
  React.useEffect(() => {
    if (didAutoSelectRef.current || selected || !filteredRuns?.length) return
    const fromUrl = parsePathname(window.location.pathname, window.location.search)
    if (fromUrl.view === 'runs' && fromUrl.runId) return
    if (focusRunId) return
    didAutoSelectRef.current = true
    void open(filteredRuns[0].run_id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filteredRuns, selected, focusRunId])

  const toggleCompareId = React.useCallback((runId: string) => {
    setCompareIds((prev) => {
      if (prev.includes(runId)) return prev.filter((id) => id !== runId)
      if (prev.length >= 5) return prev
      return [...prev, runId]
    })
  }, [])

  const startCompare = React.useCallback(() => {
    if (compareIds.length < 2) return
    openExperiments({ runIds: compareIds.slice(0, 5) })
  }, [compareIds, openExperiments])

  if (!activeProject) {
    return (
      <NeedProjectPrompt
        onOpenProjects={() => {
          openProjects()
        }}
      />
    )
  }

  if (focusRunsTab === 'compare') {
    return (
      <CompareRunsTab
        description={`Pick 2–5 runs on the left, then compare params and metrics${activeProject ? ` for ${activeProject}` : ''}.`}
        onBack={goBackToRuns}
      />
    )
  }

  return (
    <RunsShell
      selectedKey={selected}
      onBack={() => {
        clearSelection()
        if (activeProject) navigatePath(paths.runs(activeProject))
      }}
      list={
        <div className="flex h-full min-h-0 flex-col">
        <div className="shrink-0 space-y-1.5 border-b border-ink-100 bg-white px-2.5 py-1.5 pr-9">
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        <div ref={filterRowRef} className="flex min-w-0 items-center gap-1.5">
            <FieldSelect
              className="w-[7.25rem] shrink-0"
              allowEmpty={false}
              value={statusFilter}
              onChange={setStatusFilter}
              aria-label="Status filter"
              options={[
                { value: 'all', label: 'All' },
                { value: 'active', label: 'Active' },
                { value: 'running', label: 'Running' },
                { value: 'completed', label: 'Done' },
                { value: 'failed', label: 'Failed' },
                { value: 'cancelled', label: 'Cancelled' },
                { value: 'paused', label: 'Paused' },
                { value: 'queued', label: 'Queued' },
              ]}
              triggerClassName="!mt-0 !py-1 rounded-md border border-ink-200 bg-white px-2 text-[12px] text-ink-800"
            />
            {searchIconOnly ? (
              <button
                type="button"
                className="btn-quiet ml-auto shrink-0 !px-1.5 !py-1"
                title="Filter runs by name or id"
                aria-label="Filter runs"
                onClick={() => setSearchOpen(true)}
              >
                <Search className="h-3.5 w-3.5" />
              </button>
            ) : (
              <input
                value={nameQuery}
                onChange={(e) => setNameQuery(e.target.value)}
                onBlur={() => {
                  if (!nameQuery.trim()) setSearchOpen(false)
                }}
                autoFocus={searchOpen && !nameQuery}
                placeholder="Filter runs…"
                aria-label="Filter by graph name or run id"
                className="min-w-[3rem] flex-1 rounded-md border border-ink-200 px-2 py-1 text-[12px]"
              />
            )}
            <button
              type="button"
              className={clsx(
                'btn-quiet shrink-0 !px-1.5 !py-1',
                (moreFilters || metricName.trim()) && 'text-accent-800',
              )}
              title="Metric filters"
              aria-pressed={moreFilters || Boolean(metricName.trim())}
              onClick={() => setMoreFilters((v) => !v)}
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              className={clsx('btn-quiet shrink-0 !px-1.5 !py-1', showArchived && 'text-accent-800')}
              title={showArchived ? 'Hide archived runs' : 'Show archived runs'}
              aria-label="Show archived"
              aria-pressed={showArchived}
              onClick={() => {
                setOffset(0)
                setShowArchived((v) => !v)
              }}
            >
              <Archive className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              className="btn-quiet shrink-0 !px-1.5 !py-1"
              title="Refresh runs"
              onClick={() => void load()}
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
          {moreFilters || metricName.trim() ? (
            <div className="flex min-w-0 items-center gap-1.5">
              <input
                value={metricName}
                onChange={(e) => setMetricName(e.target.value)}
                placeholder="Metric"
                aria-label="Metric name"
                list="run-metric-keys"
                className="min-w-0 flex-1 rounded-md border border-ink-200 px-2 py-1 text-[12px]"
              />
              <input
                type="number"
                value={metricMin}
                onChange={(e) => setMetricMin(e.target.value)}
                placeholder="≥"
                aria-label="Minimum metric"
                disabled={!metricName.trim()}
                className="w-14 shrink-0 rounded-md border border-ink-200 px-2 py-1 text-[12px] disabled:opacity-50"
              />
              <datalist id="run-metric-keys">
                {Array.from(
                  new Set(
                    (runs || []).flatMap((r) => Object.keys((r.metrics as Record<string, unknown>) || {})),
                  ),
                )
                  .sort()
                  .map((k) => (
                    <option key={k} value={k} />
                  ))}
              </datalist>
            </div>
          ) : null}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2 [scrollbar-gutter:stable]">
        {runs === null ? (
          <LoadingBlock />
        ) : runs.length === 0 ? (
          <EmptyState
            compact
            title="No runs in this workspace yet"
            description="Open the Editor and run a graph — inspect logs, outputs, and lineage here."
            action={
              <button
                type="button"
                className="btn-primary"
                onClick={() => goView('builder')}
              >
                Open Editor
              </button>
            }
          />
        ) : !filteredRuns || filteredRuns.length === 0 ? (
          <EmptyState
            compact
            title="No runs match these filters"
            description="Clear the status or search filter to see every run in this workspace."
            action={
              <button
                type="button"
                className="btn-primary"
                onClick={clearRunFilters}
              >
                Clear filters
              </button>
            }
          />
        ) : (
          <>
          {compareIds.length > 0 ? (
            <div className="mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-[12px]">
              <span className="font-medium text-ink-800">
                {compareIds.length} selected
              </span>
              <button
                type="button"
                className="btn-quiet !px-2 !py-0.5 text-[11px]"
                onClick={() => setCompareIds([])}
              >
                Clear
              </button>
              <button
                type="button"
                className="btn-secondary !px-2 !py-0.5 text-[11px]"
                disabled={compareIds.length < 2 || compareIds.length > 5}
                title={
                  compareIds.length < 2
                    ? 'Select at least 2 runs to compare'
                    : compareIds.length > 5
                      ? 'Compare supports at most 5 runs'
                      : 'Compare selected runs'
                }
                onClick={startCompare}
              >
                Compare{compareIds.length >= 2 ? ` (${compareIds.length})` : ''}
              </button>
            </div>
          ) : null}
          <ul className="divide-y divide-ink-100 overflow-hidden rounded-lg border border-ink-200/70">
            {filteredRuns.map((r) => {
              const metric =
                listRowMetric({
                  primary: primaryMetric(r),
                  paths: pathsFromSummary(r),
                  bestPathId: bestPathIdFromSummary(r),
                }) ?? formatRunMetric(r.metrics)
              // Row arrow only against a comparable earlier run (same pipeline + path count).
              const rowRegRaw = regressionOf(r)
              const rowReg =
                rowRegRaw?.previousRunId &&
                (runs || []).some(
                  (o) =>
                    o.run_id === rowRegRaw.previousRunId &&
                    isComparableRun(o, { graphName: graphNameOf(r), pathCount: pathCountOf(r) }),
                )
                  ? rowRegRaw
                  : null
              const rowFailed = normalizeRunStatus(r.status) === 'failed'
              const failReason = rowFailed ? runFailureReason(r) : null
              const rowReplayOf = replayOfRun(r)
              const foreignProject =
                r.project && String(r.project).trim() && String(r.project) !== activeProject
                  ? String(r.project)
                  : null
              const checked = compareIds.includes(r.run_id)
              const rowVerify = lastVerifyOf(r)
              const packageRow = isPackageRun({
                graphName: String(r.graph_name ?? ''),
                graphNodeTypes: Array.isArray((r as { node_types?: unknown }).node_types)
                  ? ((r as { node_types?: unknown[] }).node_types as unknown[]).map(String)
                  : undefined,
              })
              return (
              <li key={r.run_id} className="flex min-w-0 items-stretch">
                {Boolean(selected) || compareIds.length > 0 ? (
                <label
                  className="flex w-10 shrink-0 cursor-pointer items-center justify-center self-stretch border-r border-ink-100 hover:bg-ink-50 has-[:disabled]:cursor-not-allowed"
                  title="Select for compare"
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    className="h-4 w-4 cursor-pointer rounded border-ink-300"
                    checked={checked}
                    disabled={!checked && compareIds.length >= 5}
                    onChange={() => toggleCompareId(r.run_id)}
                    aria-label={`Select ${shortRunId(r.run_id)} for compare`}
                  />
                </label>
                ) : null}
                <button
                  type="button"
                  onClick={() => {
                    if (r.run_id !== selected) pushNextUrlRef.current = true
                    void open(r.run_id)
                  }}
                  aria-current={selected === r.run_id ? 'true' : undefined}
                  className={
                    selected === r.run_id
                      ? 'ide-row is-active min-w-0 flex-1 flex-col items-stretch gap-0.5 !px-2.5 !py-2'
                      : 'ide-row min-w-0 flex-1 flex-col items-stretch gap-0.5 !px-2.5 !py-2'
                  }
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <div
                      className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink-900"
                      title={String(r.graph_name ?? '') || undefined}
                    >
                      {runDisplayName(r)}
                    </div>
                    {packageRow ? (
                      <span className="shrink-0 rounded-full bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-800">
                        Package
                      </span>
                    ) : null}
                    {isArchivedRun(r) ? (
                      <span className="shrink-0 rounded-full bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-600">
                        Archived
                      </span>
                    ) : null}
                    {isAwaitingApproval(r.status) ? (
                      <StatusBadge kind="run" status={String(r.status)} />
                    ) : (
                      <StatusBadge status={shortStatusLabel(r.status)} />
                    )}
                    {isStaleRunning(r.status, r.created_at) ? (
                      <span
                        className="shrink-0 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900"
                        title={`Still RUNNING after ${formatRelativeTime(r.created_at)} — may be a zombie journal`}
                      >
                        Stale
                      </span>
                    ) : null}
                  </div>
                  <div className="flex min-w-0 items-center justify-between gap-2 text-[11px] text-ink-500">
                    <span
                      className="min-w-0 truncate tabular-nums"
                      title={
                        [rowReplayOf ? `Replay of run ${rowReplayOf}` : '', failReason || metric || foreignProject || '']
                          .filter(Boolean)
                          .join(' · ') || undefined
                      }
                    >
                      {linkableRunId(rowReplayOf) ? (
                        <span className="text-ink-400">
                          Replay of <span className="font-mono">{shortRunId(rowReplayOf)}</span>
                          {failReason || metric || foreignProject ? ' · ' : ''}
                        </span>
                      ) : null}
                      {failReason ? (
                        <span className="text-ink-600">{failReason}</span>
                      ) : (
                        metric || foreignProject || (rowReplayOf ? '' : '\u00a0')
                      )}
                      {!failReason && metric && rowReg && rowReg.delta < -0.005 ? (
                        <span
                          className="ml-1 font-semibold text-rose-700"
                          title={`Lower than the best earlier run of this pipeline${
                            rowReg.previousValue != null
                              ? ` (${formatMetricValue(primaryMetric(r)?.name || '', rowReg.previousValue)})`
                              : ''
                          }`}
                        >
                          ↓{formatMetricDelta(primaryMetric(r)?.name || '', Math.abs(rowReg.delta)).replace(/^\+/, '')}
                        </span>
                      ) : null}
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span title={formatLocaleDateTime(r.created_at)}>
                        {formatRelativeTime(r.created_at)}
                      </span>
                      <span className="inline-flex items-center gap-0.5 font-mono text-ink-400" title={r.run_id}>
                        {rowVerify?.ok ? (
                          <span
                            className="inline-flex"
                            title={`Last verify passed${rowVerify.checkedAt ? ` · ${formatLocaleDateTime(rowVerify.checkedAt)}` : ''}${rowVerify.actor ? ` · by ${rowVerify.actor}` : ''}`}
                          >
                            <ShieldCheck className="h-3 w-3 text-emerald-600" aria-label="verified" />
                          </span>
                        ) : null}
                        {shortRunId(r.run_id)}
                      </span>
                    </span>
                  </div>
                </button>
              </li>
            )})}
          </ul>
          </>
        )}
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            className="btn-secondary"
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - limit))}
          >
            Prev
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={!runs || runs.length < limit}
            onClick={() => setOffset((o) => o + limit)}
          >
            Next
          </button>
          {runs && runs.length > 0 ? (
            <span className="text-[11px] text-ink-400">
              {offset + 1}–{offset + runs.length}
            </span>
          ) : null}
        </div>
        </div>
        </div>
      }
      detail={
        <>
        {!selected ? (
          <div className="flex h-full min-h-0 items-center justify-center bg-white p-6">
          <EmptyState
            compact
            title="Select a run"
            description="Overview, outputs, and logs for any workflow run appear here."
            action={
              runs && runs.length > 0 ? (
                <button type="button" className="btn-secondary" onClick={() => void open(runs[0].run_id)}>
                  Open latest run
                </button>
              ) : (
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => goView('builder')}
                >
                  Open Editor
                </button>
              )
            }
          />
          </div>
        ) : notFoundRunId === selected ? (
          <div className="p-4">
          <EmptyState
            compact
            title={`Run ${shortRunId(selected)} not found`}
            description="It may have been deleted, or the link points at a run from another API instance."
            action={
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  clearSelection()
                  if (activeProject) navigatePath(paths.runs(activeProject))
                }}
              >
                Back to runs
              </button>
            }
          />
          </div>
        ) : (
          <div ref={detailPaneRef} className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
            {selectedHiddenByFilters && (
              <div
                role="status"
                className="mx-3 mt-3 flex shrink-0 flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-[12px] text-amber-950"
              >
                <span>Selected run hidden by filters</span>
                <button type="button" className="btn-secondary !px-2 !py-0.5 text-[11px]" onClick={clearRunFilters}>
                  Clear filters
                </button>
              </div>
            )}
            {(() => {
              const st = (runStatus || '').toLowerCase()
              const succeeded = st === 'succeeded' || st === 'completed' || st === 'success'
              const failed = st === 'failed' || st === 'error'
              const cancelled = st === 'cancelled' || st === 'canceled'
              const live = isLiveRunStatus(runStatus)
              return (
            <div className="shrink-0 space-y-1 border-b border-ink-100 bg-white px-3 py-1.5">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <MasterDetailToggle />
                {isAwaitingApproval(runStatus) ? (
                  <StatusBadge kind="run" status={String(runStatus)} />
                ) : (
                  <StatusBadge status={shortStatusLabel(runStatus)} />
                )}
                {isStaleRunning(
                  runStatus,
                  selectedSummary?.created_at ??
                    (detail?.meta as { created_at?: string } | undefined)?.created_at,
                ) && (
                  <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900">
                    Stale
                  </span>
                )}
                <span
                  className={clsx(
                    'min-w-0 truncate text-[13px] font-semibold text-ink-950',
                    compactActions ? 'max-w-[16rem]' : 'max-w-[24rem]',
                  )}
                  title={selected || undefined}
                >
                  {headerTitle}
                </span>
                <span
                  className="text-[11px] text-ink-500"
                  title={formatLocaleDateTime(
                    selectedSummary?.created_at ??
                      (detail?.meta as { created_at?: string } | undefined)?.created_at,
                  )}
                >
                  {formatRelativeTime(
                    selectedSummary?.created_at ??
                      (detail?.meta as { created_at?: string } | undefined)?.created_at,
                  )}
                </span>
                {selected ? <ShortId value={selected} label="run id" /> : null}
                {headerLastVerify ? (
                  <span
                    className={clsx(
                      'inline-flex items-center gap-0.5 text-[11px]',
                      headerLastVerify.ok ? 'text-emerald-700' : 'text-rose-700',
                    )}
                    title={lastVerifyText(headerLastVerify).text}
                  >
                    <ShieldCheck className="h-3 w-3" aria-hidden />
                    {headerLastVerify.ok ? 'Verified' : headerLastVerify.status === 'unsealed' ? 'Not sealed' : 'Verify failed'}
                  </span>
                ) : null}
                {runActor.name ? (
                  <span className="inline-flex min-w-0 items-center gap-1 text-[11px] text-ink-500">
                    by <ActorName actor={runActor.name} verified={runActor.verified} claimed={runActor.claimed} className="text-ink-700" />
                  </span>
                ) : null}
                {live && status?.progress_pct != null ? (
                  <SlimProgress pct={Number(status.progress_pct)} />
                ) : null}
                {live && runningNow.length > 0 ? (
                  <span
                    className="inline-flex items-center gap-1 text-[11px] text-ink-600"
                    title={runningNow.map((r) => r.id).join(', ')}
                  >
                    <Loader2 className="h-3 w-3 animate-spin text-sky-600" aria-hidden />
                    {runningNow.map((r) => r.label).join(' · ')}
                  </span>
                ) : null}
                {sourceRunId ? (
                  <span className="text-[11px] text-ink-500">
                    Source{' '}
                    <button
                      type="button"
                      className="font-mono text-accent-800 underline-offset-2 hover:underline"
                      title={`Open run ${sourceRunId}`}
                      onClick={() => {
                        pendingPanelRef.current = 'lineage'
                        void open(sourceRunId)
                      }}
                    >
                      {shortRunId(sourceRunId)}
                    </button>
                  </span>
                ) : null}
                {linkableRunId(replayOf) ? (
                  <span className="text-[11px] text-ink-500">
                    Replay of{' '}
                    <button
                      type="button"
                      className="font-mono text-accent-800 underline-offset-2 hover:underline"
                      title={`Open run ${replayOf}`}
                      onClick={() => {
                        pushNextUrlRef.current = true
                        pendingPanelRef.current = 'lineage'
                        void open(replayOf)
                      }}
                    >
                      run {shortRunId(replayOf)}
                    </button>
                  </span>
                ) : null}
                {selectedArchived ? (
                  <span
                    className="rounded-full bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-600"
                    title="Archived runs are hidden from the list; the record and files are kept"
                  >
                    Archived
                  </span>
                ) : null}
                <div className="ml-auto flex shrink-0 flex-wrap items-center gap-1">
                  {['running', 'paused'].includes(st) ? (
                    <details className="relative">
                      <summary
                        className="btn-secondary !px-2 !py-1 text-[11px] cursor-pointer list-none [&::-webkit-details-marker]:hidden"
                        title="Pause, resume, or cancel this run"
                      >
                        Manage
                      </summary>
                      <div className="absolute right-0 z-30 mt-1 flex min-w-[10rem] flex-col gap-1 rounded-xl border border-ink-200 bg-white p-2 shadow-lg">
                        {st === 'running' && (
                          <button type="button" className="btn-secondary w-full justify-start" onClick={() => void control(selected, 'pause')}>
                            <Pause className="h-3.5 w-3.5" /> Pause
                          </button>
                        )}
                        {st === 'paused' && (
                          <button type="button" className="btn-secondary w-full justify-start" onClick={() => void control(selected, 'resume')}>
                            <Play className="h-3.5 w-3.5" /> Resume
                          </button>
                        )}
                        <ConfirmButton
                          label={
                            isStaleRunning(
                              runStatus,
                              selectedSummary?.created_at ??
                                (detail?.meta as { created_at?: string } | undefined)?.created_at,
                            )
                              ? 'Cancel stale run'
                              : 'Cancel run'
                          }
                          confirmLabel="Confirm cancel"
                          danger
                          onConfirm={() => void control(selected, 'cancel')}
                        />
                      </div>
                    </details>
                  ) : null}
                  {!live && auditApi && !compactActions ? (
                    <>
                      <button
                        type="button"
                        className="btn-quiet !px-2 !py-1 text-[11px]"
                        disabled={verifyBusy}
                        title="Re-check the record hash, chain, graph snapshot, inputs and outputs"
                        onClick={() => void verifyRun()}
                      >
                        <ShieldCheck className="h-3.5 w-3.5" /> {verifyBusy ? 'Verifying…' : 'Verify'}
                      </button>
                      <button
                        type="button"
                        className={clsx('btn-quiet !px-2 !py-1 text-[11px]', replayOpen && 'text-accent-800')}
                        aria-expanded={replayOpen}
                        title="Start a new run from this run’s exact graph snapshot and seed"
                        onClick={() => {
                          setReplayConflict(null)
                          setReplayOpen((v) => !v)
                        }}
                      >
                        <Repeat className="h-3.5 w-3.5" /> Replay exactly
                      </button>
                    </>
                  ) : null}
                  {/* Primary action last (rightmost): Register model, or the package for Ship runs. */}
                  {succeeded && packageRun ? (
                    <>
                      {activeProject && !compactActions ? (
                        <button
                          type="button"
                          className="btn-secondary !px-2 !py-1 text-[11px]"
                          title="Open Ship with this run’s package"
                          onClick={() =>
                            navigatePath(`${paths.ship(activeProject)}?run_id=${encodeURIComponent(selected)}`)
                          }
                        >
                          <Rocket className="h-3.5 w-3.5" /> Open in Ship
                        </button>
                      ) : null}
                      {outputFiles.length > 0 ? (
                        <button
                          type="button"
                          className="btn-primary !px-2 !py-1 text-[11px]"
                          title="Download this run’s package files as a zip (one folder per step)"
                          onClick={() => void downloadZip()}
                        >
                          <Download className="h-3.5 w-3.5" /> Download package
                        </button>
                      ) : null}
                    </>
                  ) : null}
                  {succeeded && runProducedModel ? (
                    <button
                      type="button"
                      className="btn-primary !px-2 !py-1 text-[11px]"
                      aria-haspopup="dialog"
                      aria-expanded={promoteOpen}
                      title="Save a model from this run to Models"
                      onClick={() => {
                        setPromoteCandidateId(null)
                        setRegModelName('')
                        setRegModelSlug('')
                        setPromoteOpen(true)
                      }}
                    >
                      Register model
                    </button>
                  ) : null}
                  {canOpenGraph || !live ? (
                    <details className="relative">
                      <summary
                        className="btn-quiet !px-1.5 !py-1 text-[11px] cursor-pointer list-none [&::-webkit-details-marker]:hidden"
                        title="More actions"
                        aria-label="More run actions"
                      >
                        <MoreHorizontal className="h-3.5 w-3.5" />
                      </summary>
                      <div className="absolute right-0 z-30 mt-1 flex w-64 max-w-[calc(100vw-2rem)] flex-col gap-0.5 rounded-xl border border-ink-200 bg-white p-1.5 text-[12px] shadow-lg">
                        {compactActions && !live && auditApi ? (
                          <>
                            <button
                              type="button"
                              className="btn-quiet w-full justify-start !px-2 !py-1 text-[12px]"
                              disabled={verifyBusy}
                              title="Re-check the record hash, chain, graph snapshot, inputs and outputs"
                              onClick={(e) => {
                                closeMenu(e)
                                void verifyRun()
                              }}
                            >
                              <ShieldCheck className="h-3.5 w-3.5" /> {verifyBusy ? 'Verifying…' : 'Verify'}
                            </button>
                            <button
                              type="button"
                              className="btn-quiet w-full justify-start !px-2 !py-1 text-[12px]"
                              title="Start a new run from this run’s exact graph snapshot and seed"
                              onClick={(e) => {
                                closeMenu(e)
                                setReplayConflict(null)
                                setReplayOpen(true)
                              }}
                            >
                              <Repeat className="h-3.5 w-3.5" /> Replay exactly
                            </button>
                          </>
                        ) : null}
                        {compactActions && succeeded && packageRun && activeProject ? (
                          <button
                            type="button"
                            className="btn-quiet w-full justify-start !px-2 !py-1 text-[12px]"
                            title="Open Ship with this run’s package"
                            onClick={(e) => {
                              closeMenu(e)
                              navigatePath(`${paths.ship(activeProject)}?run_id=${encodeURIComponent(selected)}`)
                            }}
                          >
                            <Rocket className="h-3.5 w-3.5" /> Open in Ship
                          </button>
                        ) : null}
                        {canOpenGraph ? (
                          <button
                            type="button"
                            className="btn-quiet w-full justify-start !px-2 !py-1 text-[12px]"
                            title="Open this run’s graph in the Editor"
                            onClick={(e) => {
                              closeMenu(e)
                              void openGraphInBuilder()
                            }}
                          >
                            <Workflow className="h-3.5 w-3.5" /> Open in Editor
                          </button>
                        ) : null}
                        {!live && auditApi ? (
                          selectedArchived ? (
                            <button
                              type="button"
                              className="btn-quiet w-full justify-start !px-2 !py-1 text-[12px]"
                              title="Show this run in the list again"
                              onClick={(e) => {
                                closeMenu(e)
                                void restoreRun(selected)
                              }}
                            >
                              <Archive className="h-3.5 w-3.5" /> Restore
                            </button>
                          ) : (
                            <ConfirmButton
                              label="Archive"
                              confirmLabel="Archive run? (kept, hidden)"
                              disabled={archiveBusy}
                              className="w-full justify-start !px-2 !py-1 text-[12px]"
                              onConfirm={() => void archiveRun()}
                            />
                          )
                        ) : null}
                        {!live ? (
                          <>
                            <div className="my-1 border-t border-ink-100" />
                            <button
                              type="button"
                              className="btn-quiet w-full justify-start !px-2 !py-1 text-[12px] text-rose-700"
                              onClick={(e) => {
                                closeMenu(e)
                                setPurgeText('')
                                setPurgeOpen(true)
                              }}
                            >
                              Delete permanently…
                            </button>
                            <p className="px-2 pb-1 text-[11px] text-ink-400">
                              {auditApi
                                ? 'Removes the run’s files and journal for good. Archive keeps the audit record.'
                                : 'This server cannot archive runs — deleting removes the run for good.'}
                            </p>
                          </>
                        ) : null}
                      </div>
                    </details>
                  ) : null}
                </div>
              </div>

              {replayOpen && auditApi ? (
                <ReplayPanel
                  graphHash={String(
                    (pickProve(detail) as { graph_hash?: unknown } | null)?.graph_hash ??
                      detailMeta?.graph_hash ??
                      '',
                  )}
                  seed={(() => {
                    const v =
                      (pickProve(detail) as { seed?: unknown } | null)?.seed ??
                      (stackGraph?.metadata as { seed?: unknown } | undefined)?.seed
                    return typeof v === 'number' ? v : null
                  })()}
                  busy={replayBusy}
                  conflict={replayConflict}
                  onReplay={(force) => void replayRun(force)}
                  onCancel={() => {
                    setReplayOpen(false)
                    setReplayConflict(null)
                  }}
                />
              ) : null}
              {verifyResult && verifyResult.runId === selected ? (
                <VerifyChecklist
                  groups={verifyResult.groups}
                  ok={verifyResult.ok}
                  status={verifyResult.status}
                  verifiedAt={verifyResult.verifiedAt}
                  labelFor={stepLabel}
                  onClose={() => setVerifyResult(null)}
                  counts={verifyResult.counts}
                  actor={verifyResult.actor}
                  runId={selected}
                  historyCount={verifyResult.historyCount}
                />
              ) : null}
              {purgeOpen ? (
                <div
                  role="dialog"
                  aria-label="Delete run permanently"
                  className="w-full space-y-2 rounded-lg border border-rose-200 bg-rose-50/60 px-3 py-2 text-[12px] text-rose-950"
                >
                  <p>
                    <span className="font-semibold">Delete permanently</span> removes this run’s journal, outputs and
                    record. It cannot be undone{auditApi ? ' — Archive keeps everything and only hides the run' : ''}.
                    Type the full run id to confirm:
                  </p>
                  <p className="select-all font-mono text-[11px] text-rose-900">{selected}</p>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <input
                      value={purgeText}
                      onChange={(e) => setPurgeText(e.target.value)}
                      placeholder="run id"
                      aria-label="Type the run id to confirm"
                      className="min-w-[16rem] flex-1 rounded-md border border-rose-200 bg-white px-2 py-1 font-mono text-[11px]"
                    />
                    <button
                      type="button"
                      className="btn-danger !px-2 !py-1 text-[11px]"
                      disabled={archiveBusy || purgeText.trim() !== selected}
                      onClick={() => void purgeRun()}
                    >
                      {archiveBusy ? 'Deleting…' : 'Delete permanently'}
                    </button>
                    <button type="button" className="btn-quiet !px-2 !py-1 text-[11px]" onClick={() => setPurgeOpen(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : null}

              {/* Results banner is Overview-only — Outputs/Logs stay execution-focused. */}
              {!live && panel === 'lineage' ? (
                <RunResultsBanner
                  paths={pathResults}
                  bestPathId={bestPath?.pathId ?? null}
                  multiTrack={multiPath}
                  dataset={runDataset}
                  phase={graphName}
                  regression={runRegression}
                  onOpenRun={(rid) => {
                    pushNextUrlRef.current = true
                    pendingPanelRef.current = 'lineage'
                    void open(rid)
                  }}
                  onFocusPath={(p) => {
                    const target = p.metricsNodeId || p.nodeIds[p.nodeIds.length - 1]
                    if (target) setFocusNodeId(target)
                    setPanel('lineage')
                  }}
                />
              ) : null}

              {/* One row always: tabs scroll sideways instead of wrapping. */}
              <div className="-mx-3 overflow-x-auto px-3 [scrollbar-width:none] [&>.ide-tabs]:!flex-nowrap [&_.ide-tab]:shrink-0 [&_.ide-tab]:whitespace-nowrap">
                <IdeTabs
                  aria-label="Run detail"
                  value={panel}
                  options={detailPanelOptions.map((p) => ({
                    id: p,
                    label: PANEL_LABELS[p],
                  }))}
                  onChange={(next) => setPanel(next as DetailPanel)}
                />
              </div>

              {isStaleRunning(
                runStatus,
                selectedSummary?.created_at ??
                  (detail?.meta as { created_at?: string } | undefined)?.created_at,
              ) && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-950">
                  Running a long time
                  {logs.length === 0 ? ' with no logs' : ''} — likely a zombie journal. Use Manage → Cancel.
                </div>
              )}

              {failed || cancelled ? (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-200/80 bg-rose-50/60 px-3 py-1.5">
                  <span className="text-[12px] font-semibold text-rose-950">
                    {failed ? 'Run failed' : 'Run cancelled'}
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    <button type="button" className="btn-primary !px-2 !py-1 text-[11px]" onClick={() => void openGraphInBuilder()}>
                      Open in Editor
                    </button>
                    <button type="button" className="btn-secondary !px-2 !py-1 text-[11px]" onClick={() => setPanel('logs')}>
                      Logs
                    </button>
                    {failed ? (
                      <button
                        type="button"
                        className="btn-secondary !px-2 !py-1 text-[11px]"
                        disabled={explainBusy}
                        aria-expanded={askAgentOpen}
                        title="Create a proposal in the Agent inbox for an agent to fix this failure"
                        onClick={() => setAskAgentOpen((v) => !v)}
                      >
                        Ask agent to fix
                      </button>
                    ) : null}
                  </div>
                  {failed && runFailure ? (
                    <div className="w-full min-w-0 text-[11px]">
                      {runFailure.nodeId ? (
                        <button
                          type="button"
                          className="font-semibold text-rose-950 hover:underline"
                          title={runFailure.nodeId}
                          onClick={() => {
                            setFocusNodeId(runFailure.nodeId)
                            setPanel('lineage')
                          }}
                        >
                          {(runFailure.nodeLabel && compactNodeLabel(runFailure.nodeLabel)) ||
                            stepLabel(runFailure.nodeId) ||
                            humanNodeLabel(runFailure.nodeType || runFailure.nodeId)}
                        </button>
                      ) : null}
                      {(() => {
                        const fv = failureView({
                          error: runFailure.error,
                          errorType: runFailure.errorType,
                          traceback: runFailure.traceback,
                        })
                        return fv ? <FailureDetails failure={fv} dense /> : null
                      })()}
                    </div>
                  ) : null}
                  {failed && askAgentOpen ? (
                    <div
                      role="dialog"
                      aria-label="Ask agent to fix"
                      className="w-full space-y-2 rounded-lg border border-ink-200 bg-white px-3 py-2 text-[12px] text-ink-700"
                    >
                      <p>
                        This creates a <span className="font-semibold">pending proposal</span> in the Agent inbox with
                        this run’s graph and its failure — it does not change anything yet. An agent (or you) fills in
                        the fix; review and accept it there.
                      </p>
                      <p className="font-mono text-[11px] text-ink-500">
                        {failureProposalSummary(selected, runFailure)}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        <button
                          type="button"
                          className="btn-primary !px-2 !py-1 text-[11px]"
                          disabled={explainBusy}
                          onClick={() => void askAgentToFix()}
                        >
                          {explainBusy ? 'Sending…' : 'Send to Agent inbox'}
                        </button>
                        <button
                          type="button"
                          className="btn-quiet !px-2 !py-1 text-[11px]"
                          onClick={() => setAskAgentOpen(false)}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {succeeded && runProducedModel && promoteOpen ? createPortal(
                <div
                  className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/30 p-4"
                  onMouseDown={(e) => {
                    if (e.target === e.currentTarget) setPromoteOpen(false)
                  }}
                >
                <div
                  id="run-promote-panel"
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="run-promote-title"
                  className="flex max-h-[calc(100dvh-2rem)] w-full max-w-xl flex-col overflow-hidden rounded-xl border border-ink-200 bg-white shadow-xl"
                >
                  <div className="flex shrink-0 items-start justify-between gap-2 border-b border-ink-100 px-4 py-2.5">
                    <div className="min-w-0">
                      <h2 id="run-promote-title" className="text-[13px] font-semibold text-ink-900">Register a model from this run</h2>
                      <p className="mt-0.5 text-[11px] text-ink-500">
                        Pick the model to keep and give it a name — it appears under Models, ready to test or ship to a device.
                      </p>
                    </div>
                    <button
                      type="button"
                      className="btn-quiet shrink-0 !px-1.5 !py-1"
                      aria-label="Close"
                      title="Close (Esc)"
                      onClick={() => setPromoteOpen(false)}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain px-4 py-3">
                  {rankedModelOptions.length > 0 ? (
                    <div className="space-y-1.5">
                      <div className="text-[12px] font-medium text-ink-700">Which model?</div>
                      {visibleModelOptions.length === 0 ? (
                        <p className="rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[12px] text-amber-950">
                          This run has no trained model — only an untrained architecture. Check that training ran, or show
                          untrained models below.
                        </p>
                      ) : null}
                      <ul
                        className="space-y-1"
                        role="radiogroup"
                        aria-label="Model to save"
                      >
                        {visibleModelOptions.map((o) => {
                          const active = selectedModelOption?.id === o.id
                          const untrained = isUntrained(o)
                          const isBest = Boolean(multiPath && bestPath && o.pathId === bestPath.pathId)
                          const pm = Object.keys(o.metrics).length
                            ? primaryMetric({ metrics: o.metrics })
                            : null
                          // compiled_<hex>.keras → "Untrained model (architecture)" (raw path in the tooltip).
                          const fileName = friendlyArtifactName(o.path).label
                          return (
                            <li key={o.id}>
                              <label
                                className={clsx(
                                  'flex cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-1.5 text-[12px]',
                                  active ? 'border-accent-300 bg-accent-50/60' : 'border-ink-200 hover:bg-ink-50',
                                  untrained && 'opacity-70',
                                )}
                                title={o.path}
                              >
                                <input
                                  type="radio"
                                  className="mt-0.5"
                                  name="promote-model-option"
                                  checked={active}
                                  onChange={() => applyModelOption(o)}
                                />
                                <span className="min-w-0 flex-1">
                                  <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                                    <span className="font-medium text-ink-900">
                                      {o.pathLabel || modelKindLabel(o.kind)}
                                    </span>
                                    {o.pathLabel ? (
                                      <span className={clsx('text-[11px]', untrained ? 'text-amber-800' : 'text-ink-500')}>
                                        {modelKindLabel(o.kind)}
                                      </span>
                                    ) : null}
                                    {isBest && !untrained ? (
                                      <span className="rounded bg-emerald-100 px-1 text-[10px] font-semibold text-emerald-900">
                                        best
                                      </span>
                                    ) : null}
                                    {pm && !untrained ? (
                                      <span className="ml-auto shrink-0 text-[11px] font-semibold tabular-nums text-ink-800">
                                        {metricLabel(pm.name)} {formatMetricValue(pm.name, pm.value)}
                                      </span>
                                    ) : null}
                                  </span>
                                  <span className="mt-0.5 block truncate text-[11px] text-ink-400">
                                    {fileName}
                                    {o.format ? ` · ${o.format}` : ''}
                                    {o.sizeBytes != null ? ` · ${formatBytes(o.sizeBytes)}` : ''}
                                    {o.labels.length ? ` · ${o.labels.length} labels` : ''}
                                  </span>
                                  {untrained ? (
                                    <span className="mt-0.5 block text-[11px] text-amber-800">
                                      Not trained yet — predictions will be random.
                                    </span>
                                  ) : null}
                                </span>
                              </label>
                            </li>
                          )
                        })}
                      </ul>
                      <div className="flex flex-wrap items-end gap-2">
                        <label className="min-w-[10rem] flex-1 text-[11px] text-ink-500">
                          Model name
                          <input
                            className="mt-0.5 w-full rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800"
                            value={regModelName}
                            autoFocus
                            onChange={(e) => setRegModelName(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' && !registerBusy && selectedModelOption) void registerModelFromRun()
                            }}
                            placeholder="my-model"
                          />
                          {(() => {
                            const existing = allModelStages.get(regModelName.trim())
                            if (!existing) return null
                            const staging = existing.staging?.run_id
                            const prod = existing.prod?.run_id
                            return (
                              <span className="mt-1 block text-[11px] text-amber-800">
                                “{regModelName.trim()}” already exists — saving makes this run its new{' '}
                                <b>Staging</b> version
                                {staging && staging !== selected ? ` (replaces Staging from run ${shortRunId(staging)})` : ''}
                                {prod ? `; prod stays on run ${shortRunId(prod)}` : ''}. Pick another name for a separate model.
                              </span>
                            )
                          })()}
                        </label>
                      </div>
                    </div>
                  ) : (
                    <p className="text-[12px] text-ink-600">No model files were found in this run’s outputs.</p>
                  )}
                  <details className="rounded-lg border border-ink-100 bg-ink-50/40">
                    <summary className="cursor-pointer select-none px-2.5 py-1.5 text-[11px] font-medium text-ink-500">
                      More options
                    </summary>
                    <div className="space-y-2 border-t border-ink-100 px-2.5 py-2">
                      {untrainedCount > 0 ? (
                        <label className="flex items-center gap-2 text-[11px] text-ink-600">
                          <input
                            type="checkbox"
                            className="h-3.5 w-3.5 rounded border-ink-300"
                            checked={showUntrained}
                            onChange={(e) => setShowUntrained(e.target.checked)}
                          />
                          Also list untrained models ({untrainedCount}) — architecture only, not useful for predictions
                        </label>
                      ) : null}
                      <label className="block text-[11px] text-ink-500">
                        Storage folder
                        <input
                          className="mt-0.5 w-full rounded-lg border border-ink-200 bg-white px-2 py-1.5 font-mono text-xs text-ink-800"
                          value={regModelSlug}
                          onChange={(e) => setRegModelSlug(e.target.value)}
                          placeholder="speech-commands"
                          title="Workspace folder under artifacts/<folder>/runs/<run id> (filled in automatically)"
                        />
                      </label>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-[11px] text-ink-600" title="POST /runs/{id}/promote — points latest / staging / production at this whole run’s outputs">
                          Mark all of this run’s outputs as
                        </span>
                        <div className="flex flex-wrap items-center gap-2">
                          <FieldSelect
                            className="w-[7.5rem]"
                            allowEmpty={false}
                            value={promoteAlias}
                            onChange={(v) => setPromoteAlias(v as 'latest' | 'staging' | 'prod')}
                            aria-label="Release channel"
                            options={[
                              { value: 'latest', label: 'Latest' },
                              { value: 'staging', label: 'Staging' },
                              { value: 'prod', label: 'Production' },
                            ]}
                            triggerClassName="!mt-0 rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800"
                          />
                          <button type="button" className="btn-secondary !px-2 !py-1 text-[11px]" onClick={() => void promote()}>
                            Apply
                          </button>
                        </div>
                      </div>
                      {selectedModelOption ? (
                        <p className="break-all font-mono text-[10px] text-ink-400">{selectedModelOption.path}</p>
                      ) : null}
                    </div>
                  </details>
                  {runModels.length > 0 ? (
                    <div className="space-y-1.5 border-t border-ink-100 pt-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[12px] font-medium text-ink-700">Already saved from this run</div>
                        <button
                          type="button"
                          className="btn-quiet !px-1.5 !py-0.5 text-[11px]"
                          onClick={() => goView('models')}
                        >
                          Open Models
                        </button>
                      </div>
                      <ul className="space-y-1">
                        {runModels.map((m) => {
                          const stages = Object.keys(m.stages || {})
                          return (
                            <li
                              key={m.name}
                              className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-ink-50 px-2 py-1 text-[12px]"
                              title={Object.entries(m.stages || {})
                                .map(([k, v]) => `${k}${v?.slug ? `: ${v.slug}` : ''}`)
                                .join(' · ')}
                            >
                              <span className="font-medium text-ink-900">{m.name}</span>
                              <span className="text-[11px] text-ink-500">
                                {stages.length
                                  ? stages.map((k) => modelStageLabel(k)).join(' · ')
                                  : 'saved'}
                              </span>
                            </li>
                          )
                        })}
                      </ul>
                    </div>
                  ) : null}
                  </div>
                  <div className="flex shrink-0 items-center justify-end gap-2 border-t border-ink-100 bg-white px-4 py-2.5">
                    <button type="button" className="btn-quiet !px-2.5 !py-1.5 text-[12px]" onClick={() => setPromoteOpen(false)}>
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="btn-primary !px-3 !py-1.5 text-[12px]"
                      disabled={registerBusy || !selectedModelOption}
                      title={!selectedModelOption ? 'Pick a model first' : undefined}
                      onClick={() => void registerModelFromRun()}
                    >
                      {registerBusy ? 'Saving…' : 'Save model'}
                    </button>
                  </div>
                </div>
                </div>,
                document.body,
              ) : null}

              {!succeeded && !failed && !cancelled && runModels.length > 0 ? (
                <div className="rounded-lg border border-ink-200/70 bg-white px-3 py-2 text-[12px]">
                  <span className="font-medium text-ink-800">Models · </span>
                  {runModels.map((m) => m.name).join(', ')}
                </div>
              ) : null}
            </div>
              )
            })()}

            {isLiveRunStatus(runStatus) ? (
              <LiveRunMonitor
                nodeStats={runNodeStats}
                workers={runWorkerEntries}
                progress={[...liveProgress.values()]}
                labelFor={(id) => pipelineStackItems.find((it) => it.id === id)?.label}
                running={runningNow}
                steps={pipelineStackItems}
              />
            ) : null}

            {/* No left step column: Overview focuses steps from "What happened";
                Logs / Run outputs / Checkpoints use the compact step picker. */}
            <div className="flex min-h-0 flex-1 overflow-hidden px-3 py-2">
              <div
                className={clsx(
                  'min-h-0 min-w-0 flex-1 [scrollbar-gutter:stable]',
                  panel === 'artifacts'
                    ? 'flex flex-col overflow-hidden'
                    : 'space-y-3 overflow-y-auto',
                )}
              >
            {panel === 'logs' && (
              <div className="space-y-2">
                {visibleLogs.length > 0 || focusNodeId ? (
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-500">
                    <StepPicker options={stepOptions} value={focusNodeId} onChange={setFocusNodeId} />
                    <span>
                      {`${visibleLogs.length.toLocaleString()} line${visibleLogs.length === 1 ? '' : 's'}`}
                      {focusNodeId ? null : isMultiTrackShape(pipelineShape) ? (
                        <> · {pipelineShape.branches.length} paths in this run</>
                      ) : null}
                    </span>
                    <button
                      type="button"
                      className="btn-quiet ml-auto !px-1.5 !py-0.5 text-[11px]"
                      aria-pressed={rawLogView}
                      title={
                        rawLogView
                          ? 'Readable view: one live line per training step'
                          : 'Show every recorded event exactly as written'
                      }
                      onClick={() => setRawLogView((v) => !v)}
                    >
                      {rawLogView ? 'Readable' : 'Raw'}
                    </button>
                  </div>
                ) : null}
                <VirtualRunLogList
                  rows={visibleLogs}
                  raw={rawLogView}
                  labelFor={stepLabel}
                  emptyLabel={
                    focusNodeId
                      ? `No logs for ${focusLabel} — try All.`
                      : 'No logs recorded for this run.'
                  }
                />
              </div>
            )}
            {panel === 'checkpoints' && (
              <div className="space-y-2">
                {checkpoints.length > 0 ? (
                  <StepPicker options={stepOptions} value={focusNodeId} onChange={setFocusNodeId} />
                ) : null}
                {(() => {
                  const visible = focusNodeId
                    ? checkpoints.filter((c) => focusMatchesNode(focusNodeId, c))
                    : checkpoints
                  if (checkpoints.length === 0) {
                    return (
                      <div className="space-y-1 text-sm text-ink-500">
                        <p>
                          {focusNodeId
                            ? `No checkpoints for ${focusLabel}.`
                            : 'No resume checkpoints for this run.'}
                        </p>
                        <p className="text-[12px] text-ink-400">
                          Optional — many workflows (preprocess, export, one-shot graphs) never write
                          them. Use Run outputs for the files this run produced.
                        </p>
                      </div>
                    )
                  }
                  if (visible.length === 0) {
                    return (
                      <div className="text-sm text-ink-500">
                        No checkpoints for {focusLabel} — select All or another step.
                      </div>
                    )
                  }
                  return visible.map((c) => {
                    const active = focusMatchesNode(focusNodeId, c)
                    return (
                      <button
                        key={c}
                        type="button"
                        className={`block w-full rounded-lg border px-3 py-2 text-left text-sm hover:bg-ink-50 ${
                          active ? 'border-accent-400 bg-accent-50/50' : 'border-ink-200'
                        }`}
                        onClick={() => {
                          setFocusNodeId(c)
                          void loadCheckpointSamples(c)
                        }}
                      >
                        {displayNodeLabel(c, { withCue: true })}
                      </button>
                    )
                  })
                })()}
                {samples != null && <CollapsibleJson value={samples} label="Samples" />}
              </div>
            )}
            {panel === 'artifacts' && (
              <div className="flex min-h-0 flex-1 flex-col gap-3">
                {(() => {
                  const artifactsDir =
                    (typeof detail?.artifacts_dir === 'string' && detail.artifacts_dir) ||
                    ((detail?.meta as { artifacts_dir?: string } | undefined)?.artifacts_dir)
                  const displayPath = typeof artifactsDir === 'string'
                    ? artifactsDir.replace(/^workspace\//, '')
                    : null
                  const isLatest = detail?.is_latest === true
                  const groups = new Map<string, OutputFile[]>()
                  // Nodes whose full listing was loaded via "Show all" replace
                  // their (capped) entries from the run-wide listing.
                  const expandedIds = new Set(Object.keys(expandedNodeFiles))
                  const allFiles: OutputFile[] = [
                    ...outputFiles.filter(
                      (f) => !expandedIds.has(guessNodeFromPath(f.path, runArtifacts, f, { runId: selected })),
                    ),
                    ...Object.entries(expandedNodeFiles).flatMap(([nid, fs]) =>
                      fs.map((f) => ({ ...f, node_id: f.node_id || nid })),
                    ),
                  ]
                  for (const f of allFiles) {
                    const g = guessNodeFromPath(f.path, runArtifacts, f, { runId: selected })
                    if (focusNodeId) {
                      // Node focus: only that node's files — never run-level journal files.
                      // Match on group id only (not humanNodeLabel): label soft-match
                      // would re-merge dual Trainers/Evaluators (trainer_b66a5330 → "Trainer").
                      if (g === 'run') continue
                      if (!focusMatchesNode(focusNodeId, g)) continue
                    }
                    const list = groups.get(g) || []
                    list.push(f)
                    groups.set(g, list)
                  }
                  for (const [k, fs] of groups) groups.set(k, sortFilesNatural(fs))
                  // Execution order (node_stats.node_index → graph → journal),
                  // so groups read Dataset Ingest → … → Trainer, and nodes that
                  // only passed data in memory still get a row.
                  const execOrder = executionOrderFromRun({
                    nodeStats: runNodeStats,
                    graphNodes: (stackGraph?.nodes as Array<{ id?: unknown }> | undefined)?.length
                      ? pipelineStackItems.map((i) => ({ id: i.id }))
                      : undefined,
                    events: logs,
                  })
                  // All steps: most important first — the best path's Evaluator /
                  // Trainer / Edge Optimizer, other paths, other steps, run-level,
                  // and dataset ingest (hundreds of input wavs) last.
                  const bestLaneForOutputs = (() => {
                    if (!multiPath || !bestPath) return null
                    for (const [lane, lp] of lanePaths) if (lane !== 'shared' && lp.pathId === bestPath.pathId) return lane
                    return null
                  })()
                  const sourceIds = new Set(
                    pipelineStackItems
                      .map((i) => i.id)
                      .filter(
                        (id) =>
                          Array.isArray(stackGraph?.edges) &&
                          stackGraph.edges.length > 0 &&
                          !stackGraph.edges.some((e) => String((e as { dst_id?: unknown }).dst_id) === id),
                      ),
                  )
                  const order = focusNodeId
                    ? orderOutputGroups(
                        execOrder.filter((id) => focusMatchesNode(focusNodeId, id)),
                        groups.keys(),
                      ).filter((k) => k !== 'run')
                    : orderOutputGroupsByImportance(
                        orderOutputGroups(execOrder, groups.keys()),
                        (id) => ({
                          nodeType:
                            ((stackGraph?.nodes || []) as Array<{ id?: unknown; node_type?: unknown }>).find(
                              (n) => String(n.id) === id,
                            )?.node_type as string | undefined,
                          lane: isMultiTrackShape(pipelineShape) ? pipelineShape.laneOf.get(id) ?? null : null,
                          isSource: sourceIds.has(id),
                        }),
                        bestLaneForOutputs,
                      )
                  // Only files visible for the current focus — never keep a prior step's
                  // selection (e.g. 7.wav) while showing "No file outputs" for another node.
                  const visibleFiles = order.flatMap((g) => groups.get(g) || [])
                  const selectedFile =
                    (selectedOutputPath
                      ? visibleFiles.find((f) => f.path === selectedOutputPath)
                      : undefined) ||
                    pickDefaultOutput(order.filter((g) => g !== 'run').map((g) => groups.get(g) || [])) ||
                    visibleFiles[0]

                  const showAllForNode = async (nid: string) => {
                    if (!selected) return
                    const runId = selected
                    setExpandingNode(nid)
                    try {
                      const res = await apiJson<{ items?: OutputFile[]; total?: number; has_more?: boolean }>(
                        `/runs/${encodeURIComponent(runId)}/outputs`,
                        { query: { node_id: nid, limit: 1000, offset: 0 } },
                      )
                      if (selectedRef.current !== runId) return
                      const items = Array.isArray(res) ? (res as OutputFile[]) : Array.isArray(res?.items) ? res.items : []
                      setExpandedNodeFiles((prev) => ({ ...prev, [nid]: items }))
                      const total = typeof res?.total === 'number' ? res.total : items.length
                      setOutputsMeta((prev) => {
                        const byNode = { ...prev.byNode }
                        if (total > items.length) byNode[nid] = { shown: items.length, total }
                        else delete byNode[nid]
                        return { ...prev, byNode }
                      })
                    } catch (err) {
                      pushToast(err instanceof Error ? err.message : String(err), 'error')
                    } finally {
                      setExpandingNode((cur) => (cur === nid ? null : cur))
                    }
                  }

                  const renderTruncation = (nid: string, shownCount: number) => {
                    if (nid === 'run' || looksLikeOpaqueId(nid)) return null
                    const t = outputsMeta.byNode[nid]
                    if (!t || t.total <= shownCount) return null
                    const more = t.total - shownCount
                    const expanded = Boolean(expandedNodeFiles[nid])
                    return (
                      <div className="mt-1.5 flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-ink-200 bg-ink-50/80 px-2.5 py-1.5 text-[11px] text-ink-600">
                        <span>
                          <span className="font-medium text-ink-800">{humanNodeLabel(nid)}</span>
                          {' · '}
                          +{more.toLocaleString()} more {more === 1 ? 'file' : 'files'} not listed
                          {' '}
                          <span className="text-ink-400">
                            ({shownCount.toLocaleString()} of {t.total.toLocaleString()})
                          </span>
                        </span>
                        {!expanded ? (
                          <button
                            type="button"
                            className="font-medium text-accent-800 hover:underline disabled:opacity-50"
                            disabled={expandingNode === nid}
                            onClick={() => void showAllForNode(nid)}
                          >
                            {expandingNode === nid ? 'Loading…' : `Show all ${t.total.toLocaleString()}`}
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className="font-medium text-accent-800 hover:underline"
                          title="Zip with one folder per pipeline step (prioritised; huge wav trees may be capped)"
                          onClick={() => void downloadZip()}
                        >
                          Download zip
                        </button>
                      </div>
                    )
                  }

                  const activePath = selectedFile?.path ?? null
                  const renderFileList = (files: OutputFile[], group: string) => {
                    /* Basename collisions (six labels.txt in one step) are
                       indistinguishable rows — the full path only sat in the
                       tooltip. Show the parent dir when a name repeats. */
                    const nameCounts = new Map<string, number>()
                    for (const f of files) nameCounts.set(f.name, (nameCounts.get(f.name) ?? 0) + 1)
                    const parentDir = (p: string): string | null => {
                      const segs = p.split('/').filter(Boolean)
                      return segs.length >= 2 ? segs[segs.length - 2] : null
                    }
                    const disambiguate = (f: OutputFile): string | null =>
                      (nameCounts.get(f.name) ?? 0) > 1 ? parentDir(f.path) : null
                    return (
                    <ul className="space-y-0.5">
                      {files.map((f) => {
                        const active = activePath === f.path
                        const cue = group === 'run' ? runLevelFileCue(f.name) : null
                        // compiled_<hex>.keras → "Untrained model (architecture)"; raw name in the tooltip / path line.
                        const friendly = friendlyArtifactName(f.name)
                        const dupDir = disambiguate(f)
                        return (
                          <li key={`${f.path}-${f.name}`}>
                            <button
                              type="button"
                              className={`w-full min-w-0 rounded-md px-2 py-1.5 text-left transition ${
                                active ? 'bg-accent-50 ring-1 ring-accent-300' : 'hover:bg-ink-50'
                              }`}
                              title={shortOutputPath(f.path, { runId: selected })}
                              onClick={() => {
                                setSelectedOutputPath(f.path)
                                if (group !== 'run') setFocusNodeId(group)
                              }}
                            >
                              <div
                                className="text-[13px] font-medium leading-snug text-ink-900 [overflow-wrap:anywhere]"
                              >
                                {cue ? cue.title : friendly.label}
                              </div>
                              {cue ? (
                                <div className="text-[11px] text-ink-500" title={cue.hint}>
                                  {cue.hint}
                                </div>
                              ) : null}
                              {cue ? (
                                <div className="font-mono text-[10px] leading-snug text-ink-400 [overflow-wrap:anywhere]">
                                  {f.name} · {formatBytes(f.size)}
                                </div>
                              ) : null}
                              {!cue ? (
                                <div className="text-[11px] text-ink-500">
                                  {f.kind} · {formatBytes(f.size)}
                                  {dupDir ? ` · ${dupDir}/` : ''}
                                </div>
                              ) : null}
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                    )
                  }

                  return (
                    <>
                      <div className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-500">
                        <StepPicker options={stepOptions} value={focusNodeId} onChange={setFocusNodeId} />
                        {displayPath ? (
                          <span className="min-w-0 truncate font-mono" title={displayPath}>
                            {displayPath}
                          </span>
                        ) : null}
                        {isLatest ? <span className="shrink-0 text-ink-600">· latest</span> : null}
                        {focusNodeId ? (
                          <button
                            type="button"
                            className="shrink-0 font-medium text-accent-800 underline-offset-2 hover:underline"
                            onClick={() => setFocusNodeId(null)}
                          >
                            Show all steps
                          </button>
                        ) : null}
                        {outputFiles.length > 0 ? (
                          <button
                            type="button"
                            className="btn-quiet ml-auto !px-2 !py-0.5 text-[11px]"
                            title="Zip with one folder per pipeline step (prioritised; huge wav trees may be capped)"
                            onClick={() => void downloadZip()}
                          >
                            <Download className="h-3.5 w-3.5" /> Download zip
                          </button>
                        ) : null}
                      </div>
                      {outputsMeta.truncated && !(focusNodeId && visibleFiles.length === 0) ? (
                        <p className="shrink-0 truncate text-[11px] text-amber-900">
                          {Object.keys(outputsMeta.byNode).filter((k) => !looksLikeOpaqueId(k)).length > 0
                            ? 'Some steps have more files than shown — Show all on that step, or Download zip.'
                            : 'Listing capped here — Download zip packs more (still prioritised; not every wav).'}
                        </p>
                      ) : null}
                      {order.length === 0 || (focusNodeId && visibleFiles.length === 0) ? (
                        <div className="text-sm text-ink-500">
                          {focusNodeId
                            ? `No file outputs for ${focusLabel} — data stayed in memory. Choose All or another step.`
                            : 'No downloadable files for this run.'}
                        </div>
                      ) : (
                        <SplitPane
                          className="min-h-0 flex-1 rounded-xl border border-ink-200 bg-white"
                          // Narrow detail pane: file list above the preview instead of side by side.
                          orientation={narrowDetail ? 'vertical' : 'horizontal'}
                          defaultSize={narrowDetail ? 220 : 360}
                          minSize={narrowDetail ? 120 : 240}
                          maxSize={narrowDetail ? 480 : 640}
                          secondaryMinSize={narrowDetail ? 160 : 360}
                          storageKey={narrowDetail ? 'graphyn.layout.runOutputs.stack' : 'graphyn.layout.runOutputs'}
                          paneOverflow="hidden"
                        >
                          {[
                            <div key="list" className="h-full min-w-0 space-y-3 overflow-x-hidden overflow-y-auto p-2 [scrollbar-gutter:stable]">
                              {order.map((group) => {
                                const files = groups.get(group) || []
                                const groupLabel =
                                  pipelineStackItems.find((it) => focusMatchesNode(group, it.id))
                                    ?.label || displayNodeLabel(group, { withCue: true })
                                if (group === 'run') {
                                  return (
                                    <div key="run" className="border-t border-dashed border-ink-200 pt-2">
                                      <div className="text-[12px] font-semibold text-ink-800">Whole run</div>
                                      <p className="mb-1 text-[11px] text-ink-400">
                                        Graph, summary, and replay records for the entire run — not one step’s files.
                                      </p>
                                      {renderFileList(files, 'run')}
                                    </div>
                                  )
                                }
                                if (files.length === 0) {
                                  return (
                                    <div key={group} className="space-y-1">
                                      <div className="text-[12px] font-semibold text-ink-800">{groupLabel}</div>
                                      <p
                                        className="text-[11px] text-ink-400"
                                        title="This step passed its results to the next node in memory and wrote no files"
                                      >
                                        Passed data in memory (no files)
                                      </p>
                                    </div>
                                  )
                                }
                                const inputs = files.filter(
                                  (f) => classifyOutputRole(f.path, runArtifacts) === 'input',
                                )
                                const outputs = files.filter(
                                  (f) => classifyOutputRole(f.path, runArtifacts) !== 'input',
                                )
                                return (
                                  <div key={group} className="space-y-2">
                                    {!focusNodeId ? (
                                      <button
                                        type="button"
                                        className="text-left text-[12px] font-semibold text-ink-800 hover:text-accent-800"
                                        title="Show only this step’s files"
                                        onClick={() => setFocusNodeId(group)}
                                      >
                                        {groupLabel}
                                      </button>
                                    ) : null}
                                    {outputs.length > 0 ? (
                                      <div>
                                        {inputs.length > 0 ? <div className="mb-0.5 text-[11px] text-ink-400">Outputs</div> : null}
                                        {renderFileList(outputs, group)}
                                      </div>
                                    ) : null}
                                    {inputs.length > 0 ? (
                                      <div>
                                        <div className="mb-0.5 text-[11px] text-ink-400">Inputs</div>
                                        {renderFileList(inputs, group)}
                                      </div>
                                    ) : null}
                                    {renderTruncation(group, files.length)}
                                  </div>
                                )
                              })}
                            </div>,
                            <div key="preview" className="h-full min-w-0 overflow-x-hidden overflow-y-auto p-2 [scrollbar-gutter:stable]">
                              {selectedFile ? (
                                <FileViewer
                                  path={selectedFile.path}
                                  name={selectedFile.name}
                                  size={selectedFile.size}
                                />
                              ) : (
                                <p className="p-4 text-sm text-ink-500">Select a file to preview.</p>
                              )}
                            </div>,
                          ]}
                        </SplitPane>
                      )}
                    </>
                  )
                })()}
              </div>
            )}
            {panel === 'lineage' && selected ? (
              <>
              {/* Package card lives in the scroll pane (not the shrink-0 chrome) so
                  Edge · deploy Overview still reaches What happened / Hot spots / Run record. */}
              {shipPackagePath ? (
                <ShipPackageSummaryForPath
                  packagePath={shipPackagePath}
                  refreshKey={selected}
                  collapsible
                  onOpenRun={(rid) => {
                    pushNextUrlRef.current = true
                    pendingPanelRef.current = 'lineage'
                    void open(rid)
                  }}
                />
              ) : null}
              <RunLineagePanel
                runId={selected}
                liveStatus={runStatus}
                pathGrouping={mlMultiPath}
                stepNames={mlMultiPath ? null : stepNames}
                branchContext={mlMultiPath ? null : branchContext}
                skipReasons={skipReasons}
                stepStatuses={new Map(pipelineStackItems.map((i) => [i.id, i.status ?? '']))}
                focusNodeId={focusNodeId}
                runMeta={
                  (detail?.meta && typeof detail.meta === 'object'
                    ? (detail.meta as Record<string, unknown>)
                    : null) ||
                  (detail as Record<string, unknown> | null)
                }
                outputFiles={outputFiles}
                fileTotalsByNode={Object.fromEntries(
                  Object.entries(outputsMeta.byNode).map(([nid, t]) => [nid, t.total]),
                )}
                orderedNodeIds={pipelineStackItems.map((i) => i.id)}
                graphEdges={
                  stackGraph && Array.isArray(stackGraph.edges) && stackGraph.edges.length > 0
                    ? (stackGraph.edges as Array<{ src_id?: unknown; dst_id?: unknown }>)
                    : null
                }
                labelFor={(id) =>
                  stepLabel(id) ?? pipelineStackItems.find((i) => focusMatchesNode(id, i.id))?.label
                }
                cacheSources={cacheSources}
                stepFailures={stepFailures}
                stepResilience={stepResilience}
                topSlot={
                  <ApprovalGates
                    runId={selected}
                    runStatus={runStatus}
                    labelFor={(id) => stepLabel(id) ?? pipelineStackItems.find((i) => focusMatchesNode(id, i.id))?.label}
                    onDecided={() => void refetchRunDetail(selected)}
                  />
                }
                runLabelFor={(rid) => {
                  const row = runs?.find((r) => r.run_id === rid)
                  return row ? runDisplayName(row) : undefined
                }}
                onOpenRun={(rid) => {
                  pushNextUrlRef.current = true
                  pendingPanelRef.current = 'lineage'
                  void open(rid)
                }}
                paths={pathResults}
                lanePaths={lanePaths}
                nodePaths={nodePaths}
                recordSlot={
                  <RunRecordCard
                    stepLabel={(id) => stepLabel(id) ?? pipelineStackItems.find((i) => focusMatchesNode(id, i.id))?.label}
                    verify={verifyResult && verifyResult.runId === selected ? { ok: verifyResult.ok, status: verifyResult.status } : null}
                    lastVerify={headerLastVerify}
                    runId={selected}
                    detail={detail}
                    graphSeed={(stackGraph?.metadata as { seed?: unknown } | undefined)?.seed}
                    nodeTypeLabel={nodeTypeLabel}
                    onOpenRun={(rid) => {
                      pushNextUrlRef.current = true
                      pendingPanelRef.current = 'lineage'
                      void open(rid)
                    }}
                    onViewRaw={() => {
                      const hit = outputFiles.find((f) => f.name === 'prove.json' && f.path.includes(selected))
                      setFocusNodeId(null)
                      setSelectedOutputPath(hit?.path ?? `workspace/runs/${selected}/prove.json`)
                      setPanel('artifacts')
                    }}
                  />
                }
                bestPathId={pathResults.length > 1 ? bestPath?.pathId ?? null : null}
                evaluator={evaluatorOutputs}
                narrow={narrowDetail}
                graphNodes={(stackGraph?.nodes as Array<{ id?: unknown; node_type?: unknown; config?: unknown }> | undefined) ?? null}
                schemaFor={(t) => nodeCatalog.find((n) => n.node_type === t)?.config_schema ?? null}
                stepLogs={(nid) => {
                  const res = lastLogsForNode(formattedLogs, nid, (row) => row.nodeHint, focusMatchesNode, 20)
                  return {
                    total: res.total,
                    lines: res.rows.map((row) => ({
                      key: String(row.i),
                      clock: row.clock,
                      text: row.line.text,
                      failed: row.failed,
                    })),
                  }
                }}
                onOpenLogs={(nid) => {
                  setFocusNodeId(nid)
                  setPanel('logs')
                }}
                onOpenFile={(path) => {
                  // All steps, so the file is visible whichever group it lands in.
                  setFocusNodeId(null)
                  setSelectedOutputPath(path)
                  setPanel('artifacts')
                }}
                onFocusStep={setFocusNodeId}
                onBrowseOutputs={(nodeId) => {
                  setFocusNodeId(nodeId || null)
                  setPanel('artifacts')
                }}
                overview={{
                  artifactCount:
                    typeof debug?.artifact_count === 'number' ? debug.artifact_count : undefined,
                  provenanceCount:
                    typeof debug?.provenance_count === 'number' ? debug.provenance_count : undefined,
                  checkpointCount:
                    typeof debug?.checkpoint_count === 'number' ? debug.checkpoint_count : undefined,
                  errorCount: typeof debug?.error_count === 'number' ? debug.error_count : undefined,
                  metrics: overviewMetricsView.metrics,
                  metricsPathLabel: overviewMetricsView.pathLabel,
                  otherPathMetrics: overviewMetricsView.others,
                  recentErrors: Array.isArray(debug?.recent_errors)
                    ? (debug.recent_errors as Array<Record<string, unknown>>)
                    : undefined,
                  nodeStats: Array.isArray(debug?.node_stats)
                    ? (debug.node_stats as Array<Record<string, unknown>>)
                    : runNodeStats,
                  // Chrome "Register model" is the single entry — no duplicate Overview banner.
                  showRegisterCta: false,
                  onJumpLogs: () => setPanel('logs'),
                }}
              />
              </>
            ) : null}
              </div>
            </div>
          </div>
        )}
        </>
      }
    />
  )
}
