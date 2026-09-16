import React from 'react'
import { Download, Pause, Play, RefreshCw, Workflow } from 'lucide-react'
import { apiJson, apiUrl, getApiToken } from '../../api/client'
import type { GraphIR } from '../../types/graph'
import { emptyGraph } from '../../types/graph'
import { fetchRunGraph } from '../../lib/runGraph'
import { useAppStore } from '../../store/appStore'
import { runMatchesProject } from '../../lib/projectStamp'
import {
  isLiveRunStatus,
  isTerminalRunStatus,
  normalizeRunStatus,
  statusMatchesFilter,
} from '../../lib/runStatus'
import { ConfirmButton, CollapsibleJson, EmptyState, ErrorBanner, LoadingBlock, NeedProjectPrompt, SlimProgress, StatusBadge } from '../../components/ui'
import { FieldSelect } from '../../components/FieldSelect'
import { SplitPane } from '../../components/SplitPane'
import { FileViewer } from '../../components/FileViewer'
import { MasterDetail, ViewShell } from '../../layout'
import { formatBytes } from '../../lib/fileKind'
import {
  formatExecutionLine,
  formatLocaleDateTime,
  formatRelativeTime,
  formatRunMetric,
  humanizeTemplateName,
  humanNodeLabel,
  focusMatchesNode,
  shortRunId,
  skipConsecutiveByText,
} from '../../lib/format'
import { navigatePath } from '../../routes/parsePath'
import { paths } from '../../routes/paths'
import { goView } from '../../routes/nav'
import { RunLineagePanel } from './RunLineagePanel'
import { PipelineStack } from './PipelineStack'
import ExperimentsView, { type ExperimentsViewHandle } from '../experiments/ExperimentsView'

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

function guessNodeFromPath(path: string, arts: RunArtifact[], file?: OutputFile): string {
  const fromApi = String(file?.node_id || '').trim()
  if (fromApi) return fromApi
  const lower = path.toLowerCase()
  for (const a of arts) {
    const dp = String(a.data_path || a.path || '').toLowerCase()
    if (dp && (lower.includes(dp) || dp.includes(lower) || lower.endsWith(dp.split('/').pop() || '___'))) {
      return String(a.node_id || a.node_type || 'unknown')
    }
    const nid = String(a.node_id || '').toLowerCase()
    if (nid && lower.includes(nid)) return String(a.node_id)
  }
  // Heuristic: .../nodes/<id>/... or .../<node_id>/...
  const m = path.match(/nodes?\/([^/]+)/i) || path.match(/\/([a-zA-Z0-9_-]+)\/(?:out|output|artifacts)/i)
  return m ? m[1] : 'run'
}

/** Classify a downloadable path as node input vs output (heuristic). */
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

function runDisplayName(r: Pick<RunSummary, 'graph_name'>): string {
  const raw = String(r.graph_name ?? '').trim()
  if (raw) return humanizeTemplateName(raw)
  return 'Pipeline'
}

const PANEL_LABELS: Record<string, string> = {
  logs: 'Logs',
  artifacts: 'Run outputs',
  lineage: 'Lineage',
  debug: 'Summary',
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

type FormattedLogRow = {
  i: number
  l: Record<string, unknown>
  line: ReturnType<typeof formatExecutionLine>
  nodeHint: string | null
  failed: boolean
}

function VirtualRunLogList({
  rows,
  emptyLabel = 'No logs recorded for this run.',
}: {
  rows: FormattedLogRow[]
  emptyLabel?: string
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
            {slice.map(({ i, line, nodeHint, failed }) => {
              const hintLabel = nodeHint ? humanNodeLabel(nodeHint) : ''
              const showHint =
                Boolean(hintLabel) &&
                !line.text.toLowerCase().startsWith(hintLabel.toLowerCase())
              return (
              <div key={i} style={{ height: LOG_ROW_PX }} className={failed ? 'text-rose-300' : ''}>
                {showHint ? (
                  <span className="mr-1.5 rounded bg-ink-800 px-1 text-[10px] text-accent-300">
                    {hintLabel}
                  </span>
                ) : null}
                {line.text}
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

function RunsTopTabs({
  active,
  onHistory,
  onLive,
  onCompare,
}: {
  active: 'history' | 'live' | 'compare'
  onHistory: () => void
  onLive: () => void
  onCompare: () => void
}) {
  return (
    <div className="flex rounded-xl bg-ink-100/80 p-1">
      <button type="button" className={active === 'history' ? 'tab-pill tab-pill-on' : 'tab-pill'} onClick={onHistory}>
        History
      </button>
      <button type="button" className={active === 'live' ? 'tab-pill tab-pill-on' : 'tab-pill'} onClick={onLive}>
        Live
      </button>
      <button type="button" className={active === 'compare' ? 'tab-pill tab-pill-on' : 'tab-pill'} onClick={onCompare}>
        Compare
      </button>
    </div>
  )
}

/** Shared top chrome so History / Live / Compare look the same. */
function RunsChrome({
  description,
  active,
  onHistory,
  onLive,
  onCompare,
  onRefresh,
  children,
}: {
  description: string
  active: 'history' | 'live' | 'compare'
  onHistory: () => void
  onLive: () => void
  onCompare: () => void
  onRefresh?: () => void
  children: React.ReactNode
}) {
  return (
    <ViewShell
      title="Runs"
      description={description}
      actions={
        <>
          <RunsTopTabs active={active} onHistory={onHistory} onLive={onLive} onCompare={onCompare} />
          {onRefresh ? (
            <button type="button" onClick={onRefresh} className="btn-secondary">
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
          ) : null}
        </>
      }
    >
      {children}
    </ViewShell>
  )
}

/** Compare tab: same chrome Refresh as History/Live, wired to ExperimentsView.refresh. */
function CompareRunsTab({
  description,
  onHistory,
  onLive,
  onCompare,
}: {
  description: string
  onHistory: () => void
  onLive: () => void
  onCompare: () => void
}) {
  const experimentsRef = React.useRef<ExperimentsViewHandle>(null)
  return (
    <RunsChrome
      description={description}
      active="compare"
      onHistory={onHistory}
      onLive={onLive}
      onCompare={onCompare}
      onRefresh={() => experimentsRef.current?.refresh()}
    >
      <ExperimentsView ref={experimentsRef} embedded />
    </RunsChrome>
  )
}

/** History / Live: chrome + list|detail — shared app master divider. */
function RunsShell({
  description,
  active,
  onHistory,
  onLive,
  onCompare,
  onRefresh,
  list,
  detail,
}: {
  description: string
  active: 'history' | 'live' | 'compare'
  onHistory: () => void
  onLive: () => void
  onCompare: () => void
  onRefresh?: () => void
  list: React.ReactNode
  detail: React.ReactNode
}) {
  return (
    <RunsChrome
      description={description}
      active={active}
      onHistory={onHistory}
      onLive={onLive}
      onCompare={onCompare}
      onRefresh={onRefresh}
    >
      <MasterDetail master={list} detail={detail} collapsible />
    </RunsChrome>
  )
}

export default function RunsView() {
  const focusRunId = useAppStore((s) => s.focusRunId)
  const focusRunPanel = useAppStore((s) => s.focusRunPanel)
  const clearFocusRunPanel = useAppStore((s) => s.clearFocusRunPanel)
  const focusRunsTab = useAppStore((s) => s.focusRunsTab)
  const setFocusRunsTab = useAppStore((s) => s.setFocusRunsTab)
  const lastRunId = useAppStore((s) => s.lastRunId)
  const pushToast = useAppStore((s) => s.pushToast)
  const openExperiments = useAppStore((s) => s.openExperiments)
  const openProposals = useAppStore((s) => s.openProposals)
  const openProjects = useAppStore((s) => s.openProjects)
  const activeProject = useAppStore((s) => s.activeProject)
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)

  const [runs, setRuns] = React.useState<RunSummary[] | null>(null)
  const [offset, setOffset] = React.useState(0)
  const [selected, setSelected] = React.useState<string | null>(null)
  const [detail, setDetail] = React.useState<Record<string, unknown> | null>(null)
  const [status, setStatus] = React.useState<Record<string, unknown> | null>(null)
  const [debug, setDebug] = React.useState<Record<string, unknown> | null>(null)
  const [checkpoints, setCheckpoints] = React.useState<string[]>([])
  const [samples, setSamples] = React.useState<unknown>(null)
  const [outputFiles, setOutputFiles] = React.useState<OutputFile[]>([])
  const [runArtifacts, setRunArtifacts] = React.useState<RunArtifact[]>([])
  const [selectedOutputPath, setSelectedOutputPath] = React.useState<string | null>(null)
  const [focusNodeId, setFocusNodeId] = React.useState<string | null>(null)
  const [panel, setPanel] = React.useState<'logs' | 'debug' | 'checkpoints' | 'artifacts' | 'lineage'>('logs')
  const [error, setError] = React.useState<string | null>(null)
  const [statusFilter, setStatusFilter] = React.useState<string>('all')
  const [nameQuery, setNameQuery] = React.useState('')
  const [metricName, setMetricName] = React.useState('')
  const [metricMin, setMetricMin] = React.useState('')
  const [promoteAlias, setPromoteAlias] = React.useState<'latest' | 'staging' | 'prod'>('latest')
  const [promoteOpen, setPromoteOpen] = React.useState(false)
  const [regModelName, setRegModelName] = React.useState('')
  const [regModelSlug, setRegModelSlug] = React.useState('')
  const [registerBusy, setRegisterBusy] = React.useState(false)
  const [explainBusy, setExplainBusy] = React.useState(false)
  const [liveRuns, setLiveRuns] = React.useState<RunSummary[] | null>(null)
  const [liveSelected, setLiveSelected] = React.useState<string | null>(null)
  const [liveDetail, setLiveDetail] = React.useState<Record<string, unknown> | null>(null)
  const [liveStatus, setLiveStatus] = React.useState<Record<string, unknown> | null>(null)
  const [liveDebug, setLiveDebug] = React.useState<Record<string, unknown> | null>(null)
  const [liveError, setLiveError] = React.useState<string | null>(null)
  const [runModels, setRunModels] = React.useState<
    Array<{ name: string; stages?: Record<string, { run_id?: string; slug?: string; updated_at?: string }> }>
  >([])
  const limit = 50
  const pendingPanelRef = React.useRef<'logs' | 'debug' | 'checkpoints' | 'artifacts' | 'lineage' | null>(null)
  const wasLiveRunRef = React.useRef(false)
  const focusSeededForRun = React.useRef<string | null>(null)

  const goHistoryTab = React.useCallback(() => {
    setFocusRunsTab('history')
    if (activeProject) navigatePath(paths.runs(activeProject))
  }, [activeProject, setFocusRunsTab])

  const goLiveTab = React.useCallback(() => {
    setFocusRunsTab('live')
    if (activeProject) navigatePath(paths.runsLive(activeProject))
  }, [activeProject, setFocusRunsTab])

  const goCompareTab = React.useCallback(() => {
    openExperiments(selected ? { runIds: [selected] } : {})
  }, [openExperiments, selected])

  // Tab focus comes from store / pathname (/runs/live, /runs/compare) via App — no hash sync.
  React.useEffect(() => {
    if (!focusRunPanel) return
    pendingPanelRef.current = focusRunPanel
    setPanel(focusRunPanel)
    setFocusRunsTab('history')
    clearFocusRunPanel()
  }, [focusRunPanel, clearFocusRunPanel, setFocusRunsTab])

  const load = React.useCallback(async () => {
    setError(null)
    try {
      const query: Record<string, string | number> = { limit, offset }
      if (activeProject) query.project = activeProject
      setRuns(await apiJson<RunSummary[]>('/runs', { query }))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setRuns([])
    }
  }, [offset, activeProject])

  React.useEffect(() => {
    void load()
  }, [load])

  React.useEffect(() => {
    const id = focusRunId || lastRunId
    if (id) void open(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRunId])

  const open = async (id: string) => {
    const switching = selected !== id
    setSelected(id)
    setDetail(null)
    setDebug(null)
    setSamples(null)
    setRunModels([])
    setOutputFiles([])
    setRunArtifacts([])
    setSelectedOutputPath(null)
    setFocusNodeId(null)
    setPromoteOpen(false)
    focusSeededForRun.current = null
    setError(null)
    try {
      const [d, st, dbg, cps, outs, arts] = await Promise.all([
        apiJson<Record<string, unknown>>(`/runs/${id}`),
        apiJson<Record<string, unknown>>(`/runs/${id}/status`).catch(() => null),
        apiJson<Record<string, unknown>>(`/runs/${id}/debug-report`).catch(() => null),
        apiJson<string[]>(`/runs/${id}/checkpoints`).catch(() => []),
        apiJson<OutputFile[]>(`/runs/${id}/outputs`).catch(() => []),
        apiJson<RunArtifact[]>(`/runs/${id}/artifacts`).catch(() => []),
      ])
      setDetail(d)
      setStatus(st)
      setDebug(dbg)
      setCheckpoints(Array.isArray(cps) ? cps : [])
      setOutputFiles(Array.isArray(outs) ? outs : [])
      void loadRunModels(id)
      setRunArtifacts(Array.isArray(arts) ? arts : [])
      const meta = d?.meta && typeof d.meta === 'object' ? (d.meta as Record<string, unknown>) : null
      const proj = String(meta?.project ?? d?.project ?? '').trim()
      if (proj && useAppStore.getState().activeProject !== proj) {
        setActiveProject(proj)
      }
      // Only pick a default panel when opening a different run (or a forced pending panel).
      // Reloading the same run must not yank the user off Logs / Outputs / Lineage.
      if (pendingPanelRef.current) {
        setPanel(pendingPanelRef.current)
        pendingPanelRef.current = null
      } else if (switching) {
        const stStr = String(st?.status ?? meta?.status ?? d?.status ?? '').toLowerCase()
        if (stStr.includes('fail') || stStr === 'running' || stStr === 'paused' || stStr === 'cancelled') {
          setPanel('logs')
        } else {
          setPanel('debug')
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  React.useEffect(() => {
    if (!selected) return
    const metaStatus = (detail?.meta as { status?: string } | undefined)?.status
    const s = String(status?.status ?? metaStatus ?? '')
    if (!['running', 'paused'].includes(s.toLowerCase())) return
    const t = setInterval(() => {
      void apiJson<Record<string, unknown>>(`/runs/${selected}/status`)
        .then(setStatus)
        .catch(() => undefined)
    }, 2000)
    return () => clearInterval(t)
  }, [selected, status?.status, detail])

  const downloadZip = async () => {
    if (!selected) return
    try {
      const url = apiUrl(`/runs/${selected}/outputs/zip`)
      const token = getApiToken()
      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) throw new Error(`Download failed (${res.status})`)
      const blob = await res.blob()
      const obj = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = obj
      a.download = `${selected}-outputs.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(obj)
      pushToast('Zip download started', 'success')
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
      const list = Array.isArray(res?.models) ? res.models : []
      setRunModels(
        list.filter((m) => {
          const stages = m.stages || {}
          return Object.values(stages).some((s) => s && String(s.run_id || '') === runId)
        }),
      )
    } catch {
      setRunModels([])
    }
  }

  const refetchRunDetail = React.useCallback(async (id: string) => {
    try {
      const [d, st, dbg, cps, outs, arts] = await Promise.all([
        apiJson<Record<string, unknown>>(`/runs/${id}`),
        apiJson<Record<string, unknown>>(`/runs/${id}/status`).catch(() => null),
        apiJson<Record<string, unknown>>(`/runs/${id}/debug-report`).catch(() => null),
        apiJson<string[]>(`/runs/${id}/checkpoints`).catch(() => []),
        apiJson<OutputFile[]>(`/runs/${id}/outputs`).catch(() => []),
        apiJson<RunArtifact[]>(`/runs/${id}/artifacts`).catch(() => []),
      ])
      setDetail(d)
      setStatus(st)
      setDebug(dbg)
      setCheckpoints(Array.isArray(cps) ? cps : [])
      setOutputFiles(Array.isArray(outs) ? outs : [])
      setRunArtifacts(Array.isArray(arts) ? arts : [])
      void loadRunModels(id)
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
          pushToast(`Registered model ${name} @ staging`, 'success')
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
    const slug = regModelSlug.trim() || name || 'model'
    if (!name) {
      pushToast('Enter a model name', 'error')
      return
    }
    setRegisterBusy(true)
    try {
      await apiJson('/models', {
        method: 'POST',
        body: JSON.stringify({
          name,
          run_id: selected,
          slug,
          stage: 'staging',
        }),
      })
      pushToast(`Registered model ${name} @ staging`, 'success')
      setRegModelName('')
      setRegModelSlug('')
      await loadRunModels(selected)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setRegisterBusy(false)
    }
  }

  const explainFailure = async () => {
    if (!selected) return
    setExplainBusy(true)
    try {
      const recent = Array.isArray(debug?.recent_errors)
        ? (debug!.recent_errors as Array<Record<string, unknown>>)
        : []
      const errFromDebug = recent.length
        ? String(recent[recent.length - 1]?.message || JSON.stringify(recent[recent.length - 1]))
        : ''
      const runLogs = Array.isArray(detail?.logs) ? (detail!.logs as Array<Record<string, unknown>>) : []
      const errFromLogs =
        runLogs
          .map((l) => String(l.message || ''))
          .filter((m) => /fail|error/i.test(m))
          .slice(-1)[0] || ''
      const errText = (
        errFromDebug ||
        errFromLogs ||
        String(detail?.error || status?.error || 'unknown error')
      ).slice(0, 400)
      const emb = (detail?.graph ?? (detail?.meta as { graph?: unknown } | undefined)?.graph) as
        | GraphIR
        | undefined
      const baseGraph =
        emb && Array.isArray(emb.nodes) && Array.isArray(emb.edges)
          ? emb
          : emptyGraph(`fix-${shortRunId(selected)}`)
      const graph = {
        schema_version: baseGraph.schema_version || '1.1',
        nodes: Array.isArray(baseGraph.nodes) ? baseGraph.nodes : [],
        edges: Array.isArray(baseGraph.edges) ? baseGraph.edges : [],
        parameters: baseGraph.parameters || {},
        metadata: {
          ...(baseGraph.metadata || {}),
          name: baseGraph.metadata?.name || `fix-${shortRunId(selected)}`,
          seed: baseGraph.metadata?.seed ?? 42,
          description: `Explain/fix failed run ${selected}`,
          created_at: baseGraph.metadata?.created_at ?? null,
          tags: [...(baseGraph.metadata?.tags || []), 'explain-failure'],
          from_run: selected,
        },
      }
      const created = await apiJson<{ id?: string }>('/proposals', {
        method: 'POST',
        body: JSON.stringify({
          summary: `Explain / propose fix for failed run ${selected}: ${errText}`.slice(0, 280),
          graph,
          actor: 'ui-explain-failure',
        }),
      })
      pushToast('Proposal created — review in Agent inbox', 'success')
      openProposals(created?.id ? { id: String(created.id) } : {})
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setExplainBusy(false)
    }
  }

  const deleteRun = async () => {
    if (!selected) return
    try {
      await apiJson(`/runs/${selected}`, { method: 'DELETE' })
      pushToast(`Deleted run ${selected}`, 'success')
      setSelected(null)
      setDetail(null)
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
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
  const formattedLogs: FormattedLogRow[] = skipConsecutiveByText(
    logs.map((l, i) => {
      const raw = typeof l.message === 'string' ? l.message : JSON.stringify(l)
      const line = formatExecutionLine(raw)
      const nodeHint = extractLogNodeHint(l, line.text, raw)
      const failed = line.level === 'error' || String(l.level).toUpperCase() === 'ERROR'
      return { i, l, line, nodeHint, failed }
    }),
    (row) => row.line.text,
  )

  const pipelineStackItems = React.useMemo(() => {
    const items: Array<{ id: string; status?: string }> = []
    const seenLabel = new Set<string>()
    const push = (raw?: unknown, status?: unknown) => {
      const id = String(raw || '').trim()
      if (!id) return
      const label = humanNodeLabel(id).toLowerCase()
      if (seenLabel.has(label)) return
      seenLabel.add(label)
      items.push({
        id,
        status: typeof status === 'string' && status.trim() ? status : undefined,
      })
    }
    if (Array.isArray(debug?.node_stats)) {
      for (const n of debug.node_stats as Array<Record<string, unknown>>) {
        push(n.node_id || n.node_type, n.status ?? n.state)
      }
    }
    for (const a of runArtifacts) push(a.node_id || a.node_type)
    for (const f of outputFiles) {
      const g = guessNodeFromPath(f.path, runArtifacts, f)
      if (g !== 'run') push(g)
    }
    return items
  }, [debug, runArtifacts, outputFiles])

  React.useEffect(() => {
    // Only seed Focus from current_node while the run is live — on completed runs
    // that would leave the last node selected and hide most Logs / Outputs.
    if (!selected || focusSeededForRun.current === selected) return
    if (!isLiveRunStatus(runStatus)) {
      focusSeededForRun.current = selected
      return
    }
    const cur = status?.current_node != null ? String(status.current_node).trim() : ''
    if (!cur) return
    setFocusNodeId(cur)
    focusSeededForRun.current = selected
  }, [status?.current_node, selected, runStatus])

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
  const embeddedGraph = (detail?.graph ?? (detail?.meta as { graph?: unknown } | undefined)?.graph) as
    | GraphIR
    | undefined
  const canOpenGraph = Boolean(
    selected &&
      (graphName ||
        (embeddedGraph && Array.isArray(embeddedGraph.nodes) && Array.isArray(embeddedGraph.edges))),
  )

  const openGraphInBuilder = async () => {
    if (!selected) return
    try {
      if (embeddedGraph && Array.isArray(embeddedGraph.nodes) && Array.isArray(embeddedGraph.edges)) {
        loadGraphIntoBuilder(embeddedGraph)
        pushToast('Opened graph in Editor', 'success')
        return
      }
      const graph = await fetchRunGraph(selected, graphName || null)
      if (!graph) {
        pushToast(graphName ? `Graph not found for ${graphName}` : 'Graph not available for this run', 'info')
        return
      }
      loadGraphIntoBuilder(graph)
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
      if (statusNeedle && !statusMatchesFilter(r.status, statusNeedle)) return false
      if (q) {
        const rawName = String(r.graph_name ?? '')
        const hay = `${rawName} ${runDisplayName(r)} ${r.run_id}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      if (metricKey) {
        const num = metricNumeric(r.metrics as Record<string, unknown> | undefined, metricKey)
        if (num == null) return false
        if (minVal != null && Number.isFinite(minVal) && num < minVal) return false
      }
      return true
    })
  }, [runs, statusFilter, nameQuery, activeProject, metricName, metricMin])

  const selectedHiddenByFilters = Boolean(
    selected && filteredRuns && !filteredRuns.some((r) => r.run_id === selected),
  )

  const clearRunFilters = React.useCallback(() => {
    setStatusFilter('all')
    setNameQuery('')
    setMetricName('')
    setMetricMin('')
  }, [])

  const loadLive = React.useCallback(async () => {
    if (!activeProject) return
    try {
      const rows = await apiJson<RunSummary[]>('/runs', {
        query: { project: activeProject, limit: 50 },
      })
      const live = (Array.isArray(rows) ? rows : []).filter((r) => isLiveStatus(r.status))
      setLiveRuns(live)
      setLiveError(null)
      setLiveSelected((prev) => {
        if (prev && live.some((r) => r.run_id === prev)) return prev
        return live[0]?.run_id ?? null
      })
    } catch (err) {
      setLiveError(err instanceof Error ? err.message : String(err))
      setLiveRuns([])
    }
  }, [activeProject])

  React.useEffect(() => {
    if (focusRunsTab !== 'live') return
    void loadLive()
    const t = window.setInterval(() => void loadLive(), 3000)
    return () => window.clearInterval(t)
  }, [focusRunsTab, loadLive])

  React.useEffect(() => {
    if (focusRunsTab !== 'live' || !liveSelected) {
      setLiveDetail(null)
      setLiveStatus(null)
      setLiveDebug(null)
      return
    }
    let cancelled = false
    const fetchDetail = async () => {
      try {
        const [d, st, dbg] = await Promise.all([
          apiJson<Record<string, unknown>>(`/runs/${liveSelected}`),
          apiJson<Record<string, unknown>>(`/runs/${liveSelected}/status`).catch(() => null),
          apiJson<Record<string, unknown>>(`/runs/${liveSelected}/debug-report`).catch(() => null),
        ])
        if (cancelled) return
        setLiveDetail(d)
        setLiveStatus(st)
        setLiveDebug(dbg)
      } catch {
        if (!cancelled) {
          setLiveDetail(null)
          setLiveStatus(null)
          setLiveDebug(null)
        }
      }
    }
    void fetchDetail()
    const t = window.setInterval(() => void fetchDetail(), 3000)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [focusRunsTab, liveSelected])

  if (!activeProject) {
    return (
      <NeedProjectPrompt
        onOpenProjects={() => {
          openProjects()
        }}
      />
    )
  }

  if (focusRunsTab === 'live') {
    const liveNodeStats = Array.isArray(liveDebug?.node_stats)
      ? (liveDebug!.node_stats as Array<Record<string, unknown>>)
      : Array.isArray((liveDetail?.meta as { node_stats?: unknown } | undefined)?.node_stats)
        ? ((liveDetail!.meta as { node_stats: Array<Record<string, unknown>> }).node_stats)
        : []
    const currentNode = liveStatus?.current_node != null ? String(liveStatus.current_node) : null
    const wave = waveBucketsFromNodeStats(liveNodeStats)
    const workers =
      (liveDetail?.meta as { distributed_node_workers?: Record<string, string> } | undefined)
        ?.distributed_node_workers ||
      (liveStatus as { distributed_node_workers?: Record<string, string> } | null)?.distributed_node_workers
    const workerEntries = workers && typeof workers === 'object' ? Object.entries(workers) : []

    return (
      <RunsShell
        description={`Live running / pending for ${activeProject}. Polls every 3s.`}
        active="live"
        onHistory={goHistoryTab}
        onLive={goLiveTab}
        onCompare={goCompareTab}
        onRefresh={() => void loadLive()}
        list={
          <>
            {liveError && <ErrorBanner message={liveError} onRetry={() => void loadLive()} />}
            {liveRuns === null ? (
              <LoadingBlock label="Loading live runs…" />
            ) : liveRuns.length === 0 ? (
              <EmptyState
                title="No running or pending runs"
                description="Start a run from the Editor — active jobs appear here while they execute."
                action={
                  <button type="button" className="btn-primary" onClick={() => goView('builder')}>
                    Open Editor
                  </button>
                }
              />
            ) : (
              <ul className="space-y-1.5">
                {liveRuns.map((r) => (
                  <li key={r.run_id}>
                    <button
                      type="button"
                      onClick={() => setLiveSelected(r.run_id)}
                      className={`flex w-full min-w-0 flex-col gap-1 rounded-xl border px-3 py-2.5 text-left shadow-sm transition ${
                        liveSelected === r.run_id
                          ? 'border-accent-200 bg-accent-50/80 shadow-soft'
                          : 'border-ink-200/70 bg-white hover:border-ink-300'
                      }`}
                    >
                      <div className="flex min-w-0 items-start justify-between gap-2">
                        <div className="min-w-0 flex-1 truncate text-sm font-medium text-ink-900">
                          {runDisplayName(r)}
                        </div>
                        <StatusBadge status={String(r.status ?? 'unknown')} />
                      </div>
                      <div className="flex items-center justify-between gap-2 text-[11px] text-ink-500">
                        <span className="font-mono text-ink-400">{shortRunId(r.run_id)}</span>
                        <span title={formatLocaleDateTime(r.created_at)}>
                          {formatRelativeTime(r.created_at)}
                        </span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        }
        detail={
          !liveSelected ? (
            <EmptyState
              title="Select a live run"
              description="Pick a running or pending run on the left to watch progress, node wave, and workers."
            />
          ) : (
            <>
              <div className="rounded-2xl border border-ink-200/80 bg-white px-4 py-3 shadow-sm space-y-3">
                <div className="flex flex-wrap items-center gap-3">
                  <StatusBadge
                    status={String(
                      liveStatus?.status ??
                        (liveDetail?.meta as { status?: string } | undefined)?.status ??
                        liveRuns?.find((r) => r.run_id === liveSelected)?.status ??
                        'unknown',
                    )}
                  />
                  {liveStatus?.progress_pct != null && <SlimProgress pct={Number(liveStatus.progress_pct)} />}
                  {currentNode ? (
                    <span className="text-sm text-ink-600">
                      Current{' '}
                      <span className="font-medium text-ink-900">{humanNodeLabel(currentNode)}</span>
                    </span>
                  ) : null}
                </div>
                {wave.length > 0 ? (
                  <div>
                    <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                      Node status wave
                    </div>
                    <NodeStatusWave buckets={wave} />
                  </div>
                ) : (
                  <p className="text-xs text-ink-500">No node_stats yet — wave appears as nodes report status.</p>
                )}
                {workerEntries.length > 0 ? (
                  <div>
                    <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                      Worker map
                    </div>
                    <div className="flex flex-wrap gap-1.5 text-[11px] text-ink-600">
                      {workerEntries.map(([nid, wid]) => (
                        <span
                          key={nid}
                          className="rounded-md bg-ink-100 px-1.5 py-0.5 font-mono text-ink-800"
                          title={`Node ${nid}`}
                        >
                          {humanNodeLabel(nid)} → {wid}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
              {liveNodeStats.length > 0 ? (
                <div className="overflow-hidden rounded-xl border border-ink-200 bg-white">
                  <div className="border-b border-ink-100 bg-ink-50 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                    Nodes in flight
                  </div>
                  <ul className="divide-y divide-ink-100">
                    {liveNodeStats.map((n, i) => (
                      <li key={i} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                        <span className="font-medium text-ink-900">
                          {humanNodeLabel(String(n.node_type || n.node_id || `node-${i}`))}
                        </span>
                        <span className="font-mono text-[11px] text-ink-400">{String(n.node_id || '')}</span>
                        {n.status != null ? <StatusBadge status={String(n.status)} /> : null}
                        {n.duration_ms != null ? (
                          <span className="tabular-nums text-[11px] text-ink-500">{String(n.duration_ms)} ms</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => {
                    setFocusRunsTab('history')
                    if (activeProject) navigatePath(paths.run(activeProject, liveSelected))
                    void open(liveSelected)
                  }}
                >
                  Open full run (History)
                </button>
                <button type="button" className="btn-secondary" onClick={() => goView('builder')}>
                  Open Editor
                </button>
              </div>
            </>
          )
        }
      />
    )
  }

  if (focusRunsTab === 'compare') {
    return (
      <CompareRunsTab
        description={`Pick 2–5 runs on the left, then compare params and metrics${activeProject ? ` for ${activeProject}` : ''}.`}
        onHistory={goHistoryTab}
        onLive={goLiveTab}
        onCompare={goCompareTab}
      />
    )
  }

  return (
    <RunsShell
      description={`History for ${activeProject}. Open a run on the left — Logs, outputs, lineage, and summary on the right.`}
      active="history"
      onHistory={goHistoryTab}
      onLive={goLiveTab}
      onCompare={goCompareTab}
      onRefresh={() => void load()}
      list={
        <>
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {runs && runs.length > 0 ? (
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <label className="text-[11px] font-medium text-ink-500">
              Status
              <FieldSelect
                className="mt-0.5 w-[9.5rem]"
                allowEmpty={false}
                value={statusFilter}
                onChange={setStatusFilter}
                aria-label="Status filter"
                options={[
                  { value: 'all', label: 'All' },
                  { value: 'running', label: 'Running' },
                  { value: 'completed', label: 'Completed' },
                  { value: 'failed', label: 'Failed' },
                  { value: 'cancelled', label: 'Cancelled' },
                  { value: 'paused', label: 'Paused' },
                  { value: 'queued', label: 'Queued' },
                ]}
                triggerClassName="!mt-0 rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-sm text-ink-800"
              />
            </label>
            <label className="min-w-[12rem] flex-1 text-[11px] font-medium text-ink-500">
              Graph / search
              <input
                value={nameQuery}
                onChange={(e) => setNameQuery(e.target.value)}
                placeholder="Filter by graph name or run id"
                className="mt-0.5 block w-full rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
              />
            </label>
            <label className="min-w-[7rem] text-[11px] font-medium text-ink-500">
              Metric
              <input
                value={metricName}
                onChange={(e) => setMetricName(e.target.value)}
                placeholder="e.g. accuracy"
                list="run-metric-keys"
                className="mt-0.5 block w-full rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
              />
            </label>
            <label className="w-[5.5rem] text-[11px] font-medium text-ink-500">
              Min
              <input
                type="number"
                value={metricMin}
                onChange={(e) => setMetricMin(e.target.value)}
                placeholder="≥"
                disabled={!metricName.trim()}
                className="mt-0.5 block w-full rounded-lg border border-ink-200 px-2 py-1.5 text-sm disabled:opacity-50"
              />
            </label>
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
        {runs === null ? (
          <LoadingBlock />
        ) : runs.length === 0 ? (
          <EmptyState
            title="No runs in this workspace yet"
            description="Open the Editor and run a graph — History, Run outputs, Lineage, and Compare live here."
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
            title="No runs match these filters"
            description="Clear the status or search filter to see every run in this workspace."
            action={
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  setStatusFilter('all')
                  setNameQuery('')
                  setMetricName('')
                  setMetricMin('')
                }}
              >
                Clear filters
              </button>
            }
          />
        ) : (
          <ul className="space-y-1.5">
            {filteredRuns.map((r) => {
              const metric = formatRunMetric(r.metrics)
              const foreignProject =
                r.project && String(r.project).trim() && String(r.project) !== activeProject
                  ? String(r.project)
                  : null
              return (
              <li key={r.run_id}>
                <button
                  type="button"
                  onClick={() => void open(r.run_id)}
                  className={`flex w-full min-w-0 flex-col gap-1 rounded-xl border px-3 py-2.5 text-left shadow-sm transition ${
                    selected === r.run_id
                      ? 'border-accent-200 bg-accent-50/80 shadow-soft'
                      : 'border-ink-200/70 bg-white hover:border-ink-300 hover:bg-ink-50/80'
                  }`}
                >
                  <div className="flex min-w-0 items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div
                        className="truncate text-sm font-medium text-ink-900"
                        title={String(r.graph_name ?? '') || undefined}
                      >
                        {runDisplayName(r)}
                      </div>
                      {foreignProject ? (
                        <span
                          className="mt-0.5 inline-block max-w-full truncate rounded-full bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-600"
                          title={foreignProject}
                        >
                          {foreignProject}
                        </span>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <StatusBadge status={String(r.status ?? 'unknown')} />
                      {isStaleRunning(r.status, r.created_at) && (
                        <span
                          className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900"
                          title={`Still RUNNING after ${formatRelativeTime(r.created_at)} — may be a zombie journal`}
                        >
                          Stale
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex min-w-0 items-center justify-between gap-2 text-[11px] text-ink-500">
                    <span className="min-w-0 truncate tabular-nums" title={metric || undefined}>
                      {metric || '\u00a0'}
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span title={formatLocaleDateTime(r.created_at)}>
                        {formatRelativeTime(r.created_at)}
                      </span>
                      <span className="font-mono text-ink-400" title={r.run_id}>
                        {shortRunId(r.run_id)}
                      </span>
                    </span>
                  </div>
                </button>
              </li>
            )})}
          </ul>
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
        </>
      }
      detail={
        <>
        {!selected ? (
          <EmptyState
            title="Select a run"
            description="Select a run on the left to inspect Logs, Run outputs, Lineage, or Summary."
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
        ) : (
          <>
            {selectedHiddenByFilters && (
              <div
                role="status"
                className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-[12px] text-amber-950"
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
            <div className="sticky top-0 z-10 -mx-1 space-y-2 bg-white/90 px-1 pb-2 backdrop-blur-sm">
              <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ink-200/80 bg-white px-3 py-2 shadow-sm">
                <StatusBadge status={runStatus} />
                {isStaleRunning(
                  runStatus,
                  selectedSummary?.created_at ??
                    (detail?.meta as { created_at?: string } | undefined)?.created_at,
                ) && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-900">
                    Stale
                  </span>
                )}
                <div className="min-w-0 flex-1">
                  <div
                    className="truncate text-sm font-semibold text-ink-950"
                    title={selected || undefined}
                  >
                    {graphName ? humanizeTemplateName(graphName) : shortRunId(selected || '')}
                  </div>
                  <div className="flex flex-wrap items-center gap-x-2 text-[11px] text-ink-500">
                    <span
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
                    {graphName ? (
                      <span className="font-mono text-ink-400" title={selected || undefined}>
                        {shortRunId(selected || '')}
                      </span>
                    ) : null}
                    {live && status?.progress_pct != null ? (
                      <SlimProgress pct={Number(status.progress_pct)} />
                    ) : null}
                    {live && status?.current_node != null ? (
                      <span className="text-ink-600">
                        {humanNodeLabel(String(status.current_node))}
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-1">
                  {canOpenGraph ? (
                    <button
                      type="button"
                      className="btn-quiet !px-2 !py-1 text-[11px]"
                      title="Open this run’s graph in the Editor"
                      onClick={() => void openGraphInBuilder()}
                    >
                      <Workflow className="h-3.5 w-3.5" /> Editor
                    </button>
                  ) : null}
                  <details className="relative">
                    <summary
                      className="btn-quiet !px-2 !py-1 text-[11px] cursor-pointer list-none [&::-webkit-details-marker]:hidden"
                      title="Pause, resume, cancel, or delete this run"
                    >
                      Manage
                    </summary>
                    <div className="absolute right-0 z-30 mt-1 flex min-w-[10rem] flex-col gap-1 rounded-xl border border-ink-200 bg-white p-2 shadow-lg">
                      {['running'].includes(st) && (
                        <button type="button" className="btn-secondary w-full justify-start" onClick={() => void control(selected, 'pause')}>
                          <Pause className="h-3.5 w-3.5" /> Pause
                        </button>
                      )}
                      {['paused'].includes(st) && (
                        <button type="button" className="btn-secondary w-full justify-start" onClick={() => void control(selected, 'resume')}>
                          <Play className="h-3.5 w-3.5" /> Resume
                        </button>
                      )}
                      {['running', 'paused'].includes(st) && (
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
                      )}
                      {!['running', 'paused'].includes(st) && (
                        <ConfirmButton
                          label="Delete run"
                          confirmLabel={`Delete ${selected}?`}
                          danger
                          onConfirm={() => void deleteRun()}
                        />
                      )}
                    </div>
                  </details>
                  {succeeded ? (
                    <button
                      type="button"
                      className={
                        promoteOpen
                          ? 'btn-secondary !px-2 !py-1 text-[11px]'
                          : 'btn-quiet !px-2 !py-1 text-[11px]'
                      }
                      title="Point a model registry alias (latest / staging / prod) at this run’s artifacts"
                      onClick={() => setPromoteOpen((v) => !v)}
                    >
                      Promote model
                    </button>
                  ) : null}
                </div>
              </div>

              <div className="flex min-w-0 flex-wrap gap-1 rounded-xl bg-ink-100/70 p-1">
                {(['logs', 'artifacts', 'lineage', 'debug', 'checkpoints'] as const).map((p) => (
                  <button
                    key={p}
                    type="button"
                    className={panel === p ? 'tab-pill tab-pill-on' : 'tab-pill'}
                    onClick={() => setPanel(p)}
                  >
                    {PANEL_LABELS[p]}
                  </button>
                ))}
              </div>

              {sourceRunId ? (
                <p className="text-[11px] text-ink-500">
                  Source{' '}
                  <button
                    type="button"
                    className="font-mono text-accent-800 underline-offset-2 hover:underline"
                    onClick={() => {
                      pendingPanelRef.current = 'lineage'
                      void open(sourceRunId)
                    }}
                  >
                    {shortRunId(sourceRunId)}
                  </button>
                </p>
              ) : null}

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
                      Editor
                    </button>
                    <button type="button" className="btn-secondary !px-2 !py-1 text-[11px]" onClick={() => setPanel('logs')}>
                      Logs
                    </button>
                    {failed ? (
                      <button
                        type="button"
                        className="btn-secondary !px-2 !py-1 text-[11px]"
                        disabled={explainBusy}
                        onClick={() => void explainFailure()}
                      >
                        {explainBusy ? '…' : 'Explain'}
                      </button>
                    ) : null}
                  </div>
                </div>
              ) : null}

              {succeeded && promoteOpen ? (
                <div id="run-promote-panel" className="rounded-xl border border-accent-200/70 bg-white px-3 py-2.5 shadow-sm space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-[12px] text-ink-600">
                      Stage this run’s artifacts under a registry alias
                      <span className="text-ink-400"> (latest → staging → prod)</span>
                      — same path Models uses.
                    </p>
                    <div className="flex flex-wrap items-center gap-2">
                      <FieldSelect
                        className="w-[7.5rem]"
                        allowEmpty={false}
                        value={promoteAlias}
                        onChange={(v) => setPromoteAlias(v as 'latest' | 'staging' | 'prod')}
                        aria-label="Promote alias"
                        options={[
                          { value: 'latest', label: 'latest' },
                          { value: 'staging', label: 'staging' },
                          { value: 'prod', label: 'prod' },
                        ]}
                        triggerClassName="!mt-0 rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800"
                      />
                      <button type="button" className="btn-primary" onClick={() => void promote()}>
                        Promote model
                      </button>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-end gap-2 border-t border-ink-100 pt-2">
                    <label className="min-w-[8rem] flex-1 text-[11px] text-ink-500">
                      Name
                      <input
                        className="mt-0.5 w-full rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800"
                        value={regModelName}
                        onChange={(e) => setRegModelName(e.target.value)}
                        placeholder="my-model"
                      />
                    </label>
                    <label className="min-w-[8rem] flex-1 text-[11px] text-ink-500">
                      Slug
                      <input
                        className="mt-0.5 w-full rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800"
                        value={regModelSlug}
                        onChange={(e) => setRegModelSlug(e.target.value)}
                        placeholder="artifact slug"
                      />
                    </label>
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={registerBusy}
                      onClick={() => void registerModelFromRun()}
                    >
                      {registerBusy ? 'Registering…' : 'Register'}
                    </button>
                  </div>
                  {runModels.length > 0 ? (
                    <ul className="space-y-1">
                      {runModels.map((m) => {
                        const stages = m.stages || {}
                        const stageBits = Object.entries(stages)
                          .map(([k, v]) => `${k}${v?.slug ? `:${v.slug}` : ''}`)
                          .join(' · ')
                        return (
                          <li
                            key={m.name}
                            className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-ink-50 px-2 py-1 text-[12px]"
                          >
                            <span className="font-medium text-ink-900">{m.name}</span>
                            <span className="font-mono text-[11px] text-ink-500">{stageBits || 'registered'}</span>
                          </li>
                        )
                      })}
                    </ul>
                  ) : null}
                </div>
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

            <div className="flex min-h-0 min-w-0 gap-3">
              <PipelineStack
                items={pipelineStackItems}
                value={focusNodeId}
                onChange={setFocusNodeId}
                className="sticky top-[7.5rem] max-h-[calc(100vh-14rem)] self-start"
              />
              <div className="min-w-0 flex-1 space-y-3">
            {panel === 'logs' && (
              <div className="space-y-2">
                <VirtualRunLogList
                  rows={visibleLogs}
                  emptyLabel={
                    focusNodeId
                      ? `No logs for ${humanNodeLabel(focusNodeId)} — try All.`
                      : 'No logs recorded for this run.'
                  }
                />
              </div>
            )}
            {panel === 'debug' && (
              <div className="space-y-3">
                {!debug ? (
                  <div className="text-sm text-ink-500">No summary report yet.</div>
                ) : (
                  <>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 rounded-xl border border-ink-100 bg-white px-3 py-2 text-[12px]">
                      {(
                        [
                          ['Artifacts', debug.artifact_count],
                          ['Provenance', debug.provenance_count],
                          ['Checkpoints', debug.checkpoint_count],
                          ['Errors', debug.error_count],
                        ] as Array<[string, unknown]>
                      ).map(([label, val]) => (
                        <div key={label} className="flex items-baseline gap-1.5">
                          <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                            {label}
                          </span>
                          <span
                            className={`tabular-nums font-semibold ${
                              label === 'Errors' && Number(val || 0) > 0
                                ? 'text-rose-700'
                                : 'text-ink-900'
                            }`}
                          >
                            {String(val ?? 0)}
                          </span>
                        </div>
                      ))}
                    </div>
                    {Number(debug.error_count || 0) > 0 ? (
                      <button type="button" className="btn-primary" onClick={() => setPanel('logs')}>
                        Jump to errors
                      </button>
                    ) : null}
                    {Array.isArray(debug.recent_errors) && (debug.recent_errors as unknown[]).length > 0 && (
                      <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2">
                        <div className="text-[11px] font-semibold uppercase tracking-wide text-rose-700">Recent errors</div>
                        <ul className="mt-1 space-y-1 font-mono text-[11px] text-rose-900">
                          {(debug.recent_errors as Array<Record<string, unknown>>).slice(-5).map((e, i) => (
                            <li key={i}>{String(e.message || JSON.stringify(e))}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {Array.isArray(debug.node_stats) && (debug.node_stats as unknown[]).length > 0 && (
                      <div className="overflow-hidden rounded-xl border border-ink-200">
                        <div className="border-b border-ink-100 bg-ink-50 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                          {focusNodeId ? 'Timing' : 'Slowest nodes'}
                        </div>
                        <ul className="divide-y divide-ink-100">
                          {(debug.node_stats as Array<Record<string, unknown>>)
                            .filter((n) => {
                              if (!focusNodeId) return true
                              return (
                                focusMatchesNode(focusNodeId, String(n.node_id || '')) ||
                                focusMatchesNode(focusNodeId, String(n.node_type || ''))
                              )
                            })
                            .slice()
                            .sort((a, b) => Number(b.duration_ms || 0) - Number(a.duration_ms || 0))
                            .slice(0, focusNodeId ? 3 : 8)
                            .map((n, i) => {
                              const label = humanNodeLabel(String(n.node_type || n.node_id || `node-${i}`))
                              return (
                                <li
                                  key={i}
                                  className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
                                  title={String(n.node_id || n.node_type || '')}
                                >
                                  <span className="min-w-0 truncate font-medium text-ink-900">{label}</span>
                                  {n.duration_ms != null ? (
                                    <span className="shrink-0 tabular-nums text-[11px] text-ink-500">
                                      {Number(n.duration_ms).toLocaleString()} ms
                                    </span>
                                  ) : null}
                                </li>
                              )
                            })}
                        </ul>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
            {panel === 'checkpoints' && (
              <div className="space-y-2">
                {checkpoints.length === 0 ? (
                  <div className="text-sm text-ink-500">No checkpoints for this run.</div>
                ) : (
                  checkpoints.map((c) => {
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
                        {humanNodeLabel(c)}
                      </button>
                    )
                  })
                )}
                {samples != null && <CollapsibleJson value={samples} label="Samples" />}
              </div>
            )}
            {panel === 'artifacts' && (
              <div className="space-y-3">
                {(() => {
                  const artifactsDir =
                    (typeof detail?.artifacts_dir === 'string' && detail.artifacts_dir) ||
                    ((detail?.meta as { artifacts_dir?: string } | undefined)?.artifacts_dir)
                  const displayPath = typeof artifactsDir === 'string'
                    ? artifactsDir.replace(/^workspace\//, '')
                    : null
                  const isLatest = detail?.is_latest === true
                  const groups = new Map<string, OutputFile[]>()
                  for (const f of outputFiles) {
                    const g = guessNodeFromPath(f.path, runArtifacts, f)
                    if (focusNodeId) {
                      // Node focus: only that node's files — never run-level journal files.
                      if (g === 'run') continue
                      if (
                        !focusMatchesNode(focusNodeId, g) &&
                        !focusMatchesNode(focusNodeId, humanNodeLabel(g))
                      ) {
                        continue
                      }
                    }
                    const list = groups.get(g) || []
                    list.push(f)
                    groups.set(g, list)
                  }
                  const nodeOrder: string[] = []
                  for (const a of runArtifacts) {
                    const nid = String(a.node_id || '').trim()
                    if (nid && !nodeOrder.includes(nid) && groups.has(nid)) nodeOrder.push(nid)
                  }
                  for (const k of groups.keys()) {
                    if (k !== 'run' && !nodeOrder.includes(k)) nodeOrder.push(k)
                  }
                  const order = focusNodeId
                    ? nodeOrder
                    : [...nodeOrder, ...(groups.has('run') ? (['run'] as const) : [])]
                  const selectedFile =
                    outputFiles.find((f) => f.path === selectedOutputPath) ||
                    (order.length ? (groups.get(order[0]) || [])[0] : undefined)

                  const renderFileList = (files: OutputFile[], group: string) => (
                    <ul className="space-y-1">
                      {files.map((f) => {
                        const active = selectedOutputPath === f.path
                        return (
                          <li key={`${f.path}-${f.name}`}>
                            <button
                              type="button"
                              className={`w-full rounded-lg border px-2.5 py-2 text-left transition ${
                                active
                                  ? 'border-accent-400 bg-accent-50/60 shadow-sm'
                                  : 'border-ink-100 bg-white hover:border-ink-200'
                              }`}
                              onClick={() => {
                                setSelectedOutputPath(f.path)
                                if (group !== 'run') setFocusNodeId(group)
                              }}
                            >
                              <div className="truncate text-sm font-medium text-ink-900">{f.name}</div>
                              <div className="truncate font-mono text-[10px] text-ink-400">{f.path}</div>
                              <div className="text-[11px] text-ink-500">
                                {f.kind} · {formatBytes(f.size)}
                              </div>
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  )

                  return (
                    <>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                          {displayPath ? (
                            <div className="truncate font-mono text-[11px] text-ink-500">{displayPath}</div>
                          ) : null}
                          {isLatest ? (
                            <span className="mt-1 inline-flex rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">
                              Latest
                            </span>
                          ) : null}
                          {focusNodeId ? (
                            <div className="mt-1 text-[11px] text-ink-500">
                              Showing files for{' '}
                              <span className="font-medium text-ink-800">
                                {humanNodeLabel(focusNodeId)}
                              </span>
                              {' · '}
                              <button
                                type="button"
                                className="text-accent-800 underline-offset-2 hover:underline"
                                onClick={() => setFocusNodeId(null)}
                              >
                                Show all
                              </button>
                            </div>
                          ) : null}
                        </div>
                        {outputFiles.length > 0 && (
                          <button type="button" className="btn-secondary" onClick={() => void downloadZip()}>
                            <Download className="h-3.5 w-3.5" /> Download all
                          </button>
                        )}
                      </div>
                      {outputFiles.length === 0 ? (
                        <div className="text-sm text-ink-500">No downloadable files for this run.</div>
                      ) : groups.size === 0 ? (
                        <div className="text-sm text-ink-500">
                          No files for this node — select All or another step on the left.
                        </div>
                      ) : (
                        <SplitPane
                          className="min-h-[20rem] rounded-xl border border-ink-200"
                          defaultSize={280}
                          minSize={200}
                          maxSize={420}
                          storageKey="graphyn.layout.nested"
                        >
                          {[
                            <div key="list" className="space-y-3 p-2">
                              {order.map((group) => {
                                const files = groups.get(group) || []
                                if (group === 'run') {
                                  return (
                                    <div
                                      key="run"
                                      className="rounded-xl border border-dashed border-ink-200 bg-ink-50/50 p-2"
                                    >
                                      <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                                        Run-level
                                      </div>
                                      <p className="mb-2 text-[11px] text-ink-400">
                                        Journal / graph / summary for the whole run — not a node’s I/O.
                                      </p>
                                      {renderFileList(files, 'run')}
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
                                        className="text-[11px] font-semibold uppercase tracking-wide text-ink-500 hover:text-ink-800"
                                        onClick={() => setFocusNodeId(group)}
                                      >
                                        {humanNodeLabel(group)}
                                      </button>
                                    ) : null}
                                    {outputs.length > 0 ? (
                                      <div>
                                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                                          Outputs
                                        </div>
                                        {renderFileList(outputs, group)}
                                      </div>
                                    ) : null}
                                    {inputs.length > 0 ? (
                                      <div>
                                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                                          Inputs
                                        </div>
                                        {renderFileList(inputs, group)}
                                      </div>
                                    ) : null}
                                  </div>
                                )
                              })}
                            </div>,
                            <div key="preview" className="p-2">
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
              <RunLineagePanel
                runId={selected}
                focusNodeId={focusNodeId}
                runMeta={
                  (detail?.meta && typeof detail.meta === 'object'
                    ? (detail.meta as Record<string, unknown>)
                    : null) ||
                  (detail as Record<string, unknown> | null)
                }
              />
            ) : null}
              </div>
            </div>
          </>
        )}
        </>
      }
    />
  )
}
