import React from 'react'
import { Download, Pause, Play, RefreshCw, Workflow } from 'lucide-react'
import { apiJson, apiUrl, downloadOutputFile, fetchOutputBlobUrl, getApiToken } from '../../api/client'
import type { GraphIR } from '../../types/graph'
import { emptyGraph } from '../../types/graph'
import { fetchRunGraph } from '../../lib/runGraph'
import { useAppStore } from '../../store/appStore'
import { runMatchesProject } from '../../lib/projectStamp'
import { normalizeRunStatus, statusMatchesFilter } from '../../lib/runStatus'
import { ConfirmButton, CollapsibleJson, EmptyState, ErrorBanner, LoadingBlock, NeedProjectPrompt, PageHeader, SlimProgress, StatusBadge } from '../../components/ui'
import {
  formatExecutionLine,
  formatLocaleDateTime,
  formatRelativeTime,
  formatRunMetric,
  humanizeTemplateName,
  humanNodeLabel,
  shortRunId,
  skipConsecutiveByText,
} from '../../lib/format'
import { navigatePath } from '../../routes/parsePath'
import { paths } from '../../routes/paths'
import { goView } from '../../routes/nav'
import { RunLineagePanel } from './RunLineagePanel'
import ExperimentsView from '../experiments/ExperimentsView'

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
}

function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—"
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function isPreviewImage(file: OutputFile): boolean {
  if (file.kind === 'dir') return false
  const n = file.name.toLowerCase()
  return n.endsWith('.png') || n.endsWith('.jpg') || n.endsWith('.jpeg') || n.endsWith('.webp') || n.endsWith('.gif')
}

function isPreviewJson(file: OutputFile): boolean {
  if (file.kind === 'dir') return false
  const n = file.name.toLowerCase()
  return n.endsWith('.json') || n.endsWith('.jsonl')
}

function guessNodeFromPath(path: string, arts: RunArtifact[]): string {
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
  debug: 'Details',
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
  currentNode?: string | null,
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
  if (!nodeStats?.length) {
    if (currentNode) return [{ key: 'running', count: 1, className: WAVE_TONE.running }]
    return []
  }
  const counts: Record<string, number> = {}
  for (const n of nodeStats) {
    let st = String(n.status ?? n.state ?? '').toLowerCase().trim()
    if (!st) {
      st = currentNode && String(n.node_id || '') === String(currentNode) ? 'running' : 'done'
    }
    counts[st] = (counts[st] || 0) + 1
  }
  return Object.entries(counts).map(([key, count]) => ({
    key,
    count,
    className: WAVE_TONE[key] || 'bg-ink-300',
  }))
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
  const [previewUrls, setPreviewUrls] = React.useState<Record<string, string>>({})
  const [jsonPreviews, setJsonPreviews] = React.useState<Record<string, string>>({})
  const [expandedFile, setExpandedFile] = React.useState<string | null>(null)
  const [panel, setPanel] = React.useState<'logs' | 'debug' | 'checkpoints' | 'artifacts' | 'lineage'>('logs')
  const [error, setError] = React.useState<string | null>(null)
  const [statusFilter, setStatusFilter] = React.useState<string>('all')
  const [nameQuery, setNameQuery] = React.useState('')
  const [metricName, setMetricName] = React.useState('')
  const [metricMin, setMetricMin] = React.useState('')
  const [promoteAlias, setPromoteAlias] = React.useState<'latest' | 'staging' | 'prod'>('latest')
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
    setSelected(id)
    setDetail(null)
    setDebug(null)
    setSamples(null)
    setRunModels([])
    setOutputFiles([])
    setRunArtifacts([])
    setJsonPreviews({})
    setExpandedFile(null)
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
      const stStr = String(st?.status ?? meta?.status ?? d?.status ?? '').toLowerCase()
      if (pendingPanelRef.current) {
        setPanel(pendingPanelRef.current)
        pendingPanelRef.current = null
      } else if (stStr.includes('fail') || stStr === 'running' || stStr === 'paused' || stStr === 'cancelled') {
        setPanel('logs')
      } else {
        setPanel('artifacts')
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

  React.useEffect(() => {
    const plots = outputFiles.filter(isPreviewImage)
    let cancelled = false
    const created: string[] = []
    void (async () => {
      const next: Record<string, string> = {}
      for (const file of plots.slice(0, 12)) {
        try {
          const url = await fetchOutputBlobUrl(file.path)
          created.push(url)
          if (cancelled) {
            URL.revokeObjectURL(url)
            continue
          }
          next[file.path] = url
        } catch {
          /* preview is optional */
        }
      }
      if (!cancelled) setPreviewUrls(next)
    })()
    return () => {
      cancelled = true
      created.forEach((u) => URL.revokeObjectURL(u))
    }
  }, [outputFiles])

  React.useEffect(() => {
    const jsons = outputFiles.filter(isPreviewJson).slice(0, 8)
    let cancelled = false
    void (async () => {
      const next: Record<string, string> = {}
      for (const file of jsons) {
        try {
          const url = await fetchOutputBlobUrl(file.path)
          const text = await (await fetch(url)).text()
          URL.revokeObjectURL(url)
          if (cancelled) continue
          next[file.path] = text.slice(0, 4000)
        } catch {
          /* optional */
        }
      }
      if (!cancelled) setJsonPreviews(next)
    })()
    return () => {
      cancelled = true
    }
  }, [outputFiles])

  const downloadFile = async (file: OutputFile) => {
    try {
      await downloadOutputFile(file.path, file.name)
      pushToast(`Downloading ${file.name}`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

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
  const formattedLogs = skipConsecutiveByText(
    logs.map((l, i) => {
      const raw = typeof l.message === 'string' ? l.message : JSON.stringify(l)
      const line = formatExecutionLine(raw)
      return { i, l, line }
    }),
    (row) => row.line.text,
  )

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
    const wave = waveBucketsFromNodeStats(liveNodeStats, currentNode)
    const workers =
      (liveDetail?.meta as { distributed_node_workers?: Record<string, string> } | undefined)
        ?.distributed_node_workers ||
      (liveStatus as { distributed_node_workers?: Record<string, string> } | null)?.distributed_node_workers
    const workerEntries = workers && typeof workers === 'object' ? Object.entries(workers) : []

    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="shrink-0 border-b border-ink-200/70 bg-white/80 px-5 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-type-page text-ink-950">Runs</h1>
              <p className="mt-0.5 text-type-meta text-ink-400">
                Live running / pending for {activeProject}. Polls every 3s.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <RunsTopTabs active="live" onHistory={goHistoryTab} onLive={goLiveTab} onCompare={goCompareTab} />
              <button type="button" onClick={() => void loadLive()} className="btn-secondary">
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </button>
            </div>
          </div>
        </div>
        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-2">
          <div className="overflow-y-auto border-r border-ink-200/70 bg-white/40 p-5">
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
                      className={`grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 rounded-xl border px-3 py-2.5 text-left shadow-sm transition ${
                        liveSelected === r.run_id
                          ? 'border-accent-200 bg-accent-50/80 shadow-soft'
                          : 'border-ink-200/70 bg-white hover:border-ink-300'
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-ink-900">{runDisplayName(r)}</div>
                        <div className="font-mono text-[11px] text-ink-400">{shortRunId(r.run_id)}</div>
                      </div>
                      <StatusBadge status={String(r.status ?? 'unknown')} />
                      <div className="text-[11px] text-ink-500" title={formatLocaleDateTime(r.created_at)}>
                        {formatRelativeTime(r.created_at)}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="overflow-y-auto space-y-4 p-5">
            {!liveSelected ? (
              <EmptyState title="Select a live run" description="Pick a running or pending run to see node wave and workers." />
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
                      node_stats
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
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    setFocusRunsTab('history')
                    if (activeProject) navigatePath(paths.run(activeProject, liveSelected))
                    void open(liveSelected)
                  }}
                >
                  Open in History
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (focusRunsTab === 'compare') {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="shrink-0 border-b border-ink-200/70 bg-white/80 px-5 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-type-page text-ink-950">Runs</h1>
              <p className="mt-0.5 text-type-meta text-ink-400">
                Pick 2–3 runs to compare params and metrics
                {activeProject ? ` for ${activeProject}` : ''}.
              </p>
            </div>
            <RunsTopTabs active="compare" onHistory={goHistoryTab} onLive={goLiveTab} onCompare={goCompareTab} />
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          <ExperimentsView embedded />
        </div>
      </div>
    )
  }

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-2">
      <div className="overflow-y-auto border-r border-ink-200/70 bg-white/40 p-5">
        <PageHeader
          title="Runs"
          description={`History for ${activeProject}. One hub for History, Live, Run outputs, Lineage, and Compare.`}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <RunsTopTabs active="history" onHistory={goHistoryTab} onLive={goLiveTab} onCompare={goCompareTab} />
              <button type="button" onClick={() => void load()} className="btn-secondary">
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </button>
            </div>
          }
        />
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {runs && runs.length > 0 ? (
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <label className="text-[11px] font-medium text-ink-500">
              Status
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="mt-0.5 block rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-sm text-ink-800"
              >
                <option value="all">All</option>
                <option value="running">Running</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="cancelled">Cancelled</option>
                <option value="paused">Paused</option>
                <option value="queued">Queued</option>
              </select>
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
              return (
              <li key={r.run_id}>
                <button
                  type="button"
                  onClick={() => void open(r.run_id)}
                  className={`grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-0.5 rounded-xl border px-3 py-2.5 text-left shadow-sm transition sm:grid-cols-[minmax(0,1.4fr)_auto_minmax(4rem,auto)_auto_auto] ${
                    selected === r.run_id
                      ? 'border-accent-200 bg-accent-50/80 shadow-soft'
                      : 'border-ink-200/70 bg-white hover:border-ink-300 hover:bg-ink-50/80'
                  }`}
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-ink-900" title={String(r.graph_name ?? '') || undefined}>
                      {runDisplayName(r)}
                    </div>
                    {r.project && String(r.project) !== activeProject ? (
                      <span className="mt-0.5 inline-flex rounded-full bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-600">
                        {String(r.project)}
                      </span>
                    ) : activeProject ? (
                      <span className="mt-0.5 inline-flex rounded-full bg-accent-50 px-1.5 py-0.5 text-[10px] font-medium text-accent-800">
                        {activeProject}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-1.5 justify-self-end">
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
                  <div className="hidden truncate text-[11px] text-ink-600 sm:block">
                    {metric ?? ''}
                  </div>
                  <div
                    className="hidden text-[11px] text-ink-500 sm:block"
                    title={formatLocaleDateTime(r.created_at)}
                  >
                    {formatRelativeTime(r.created_at)}
                  </div>
                  <div className="font-mono text-[11px] text-ink-400" title={r.run_id}>
                    {shortRunId(r.run_id)}
                  </div>
                  <div className="col-span-2 flex items-center gap-2 text-[11px] text-ink-500 sm:hidden">
                    {metric ? <span>{metric}</span> : null}
                    <span title={formatLocaleDateTime(r.created_at)}>{formatRelativeTime(r.created_at)}</span>
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
      </div>

      <div className="overflow-y-auto space-y-4 p-5">
        {!selected ? (
          <EmptyState
            title="Select a run"
            description="Select a run on the left to inspect Logs, Run outputs, Lineage, or Compare."
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
            <div className="rounded-2xl border border-ink-200/80 bg-white px-4 py-3 shadow-sm">
              <div className="flex flex-wrap items-center gap-3">
                <StatusBadge status={runStatus} />
                {isStaleRunning(runStatus, selectedSummary?.created_at ?? (detail?.meta as { created_at?: string } | undefined)?.created_at) && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-900">
                    Stale RUNNING
                  </span>
                )}
                {status?.progress_pct != null && (
                  <SlimProgress pct={Number(status.progress_pct)} />
                )}
                {status?.current_node != null && (
                  <span className="text-sm text-ink-600">
                    Current node{' '}
                    <span className="font-medium text-ink-900">{humanNodeLabel(String(status.current_node))}</span>
                  </span>
                )}
              </div>
              {sourceRunId ? (
                <p className="mt-2 text-xs text-ink-500">
                  Source run{' '}
                  <button
                    type="button"
                    className="font-mono text-accent-800 underline-offset-2 hover:underline"
                    onClick={() => {
                      pendingPanelRef.current = 'lineage'
                      void open(sourceRunId)
                    }}
                  >
                    {sourceRunId.slice(0, 12)}…
                  </button>
                </p>
              ) : null}
              {(() => {
                const place = (detail?.meta as { distributed_node_workers?: Record<string, string> } | undefined)
                  ?.distributed_node_workers
                if (!place || typeof place !== 'object') return null
                const entries = Object.entries(place)
                if (entries.length === 0) return null
                return (
                  <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-ink-600">
                    <span className="font-medium text-ink-500">Workers</span>
                    {entries.map(([nid, wid]) => (
                      <span
                        key={nid}
                        className="rounded-md bg-ink-100 px-1.5 py-0.5 font-mono text-ink-800"
                        title={`Node ${nid}`}
                      >
                        {humanNodeLabel(nid)} → {wid}
                      </span>
                    ))}
                  </div>
                )
              })()}
            </div>

            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                {canOpenGraph && (
                  <button
                    type="button"
                    className="btn-quiet"
                    onClick={() => void openGraphInBuilder()}
                  >
                    <Workflow className="h-3.5 w-3.5" /> Open in Editor
                  </button>
                )}
                {(() => {
                  const st = (runStatus || '').toLowerCase()
                  const ok = st === 'succeeded' || st === 'completed' || st === 'success'
                  if (!ok) return null
                  return (
                    <button
                      type="button"
                      className="btn-quiet"
                      onClick={() => {
                        const el = document.getElementById('run-promote-panel')
                        el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
                      }}
                    >
                      Promote
                    </button>
                  )
                })()}
              </div>
              <details className="rounded-lg border border-ink-100 bg-ink-50/50">
                <summary className="cursor-pointer select-none px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                  Ops
                </summary>
                <div className="flex flex-wrap gap-2 border-t border-ink-100 px-2.5 py-2">
                  {['running'].includes(runStatus.toLowerCase()) && (
                    <button type="button" className="btn-secondary" onClick={() => void control(selected, 'pause')}>
                      <Pause className="h-3.5 w-3.5" /> Pause
                    </button>
                  )}
                  {['paused'].includes(runStatus.toLowerCase()) && (
                    <button type="button" className="btn-secondary" onClick={() => void control(selected, 'resume')}>
                      <Play className="h-3.5 w-3.5" /> Resume
                    </button>
                  )}
                  {['running', 'paused'].includes(runStatus.toLowerCase()) && (
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
                  {!['running', 'paused'].includes(runStatus.toLowerCase()) && (
                    <ConfirmButton
                      label="Delete run"
                      confirmLabel={`Delete ${selected}?`}
                      danger
                      onConfirm={() => void deleteRun()}
                    />
                  )}
                </div>
              </details>
            </div>
            {isStaleRunning(
              runStatus,
              selectedSummary?.created_at ??
                (detail?.meta as { created_at?: string } | undefined)?.created_at,
            ) && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-950">
                <div className="font-medium">This run has been RUNNING for a long time</div>
                <p className="mt-1 text-xs text-amber-900/90">
                  Started {formatRelativeTime(selectedSummary?.created_at ?? (detail?.meta as { created_at?: string } | undefined)?.created_at)}
                  {logs.length === 0 ? ' and has no logs' : ''}. The API still reports{' '}
                  <span className="font-semibold">running</span> — often a zombie journal after a
                  crashed worker. Use <span className="font-semibold">Cancel run</span> (click
                  twice to confirm) to mark it terminal, or delete after it leaves RUNNING.
                </p>
              </div>
            )}
            {(() => {
              const st = (runStatus || '').toLowerCase()
              const succeeded = st === 'succeeded' || st === 'completed' || st === 'success'
              const failed = st === 'failed' || st === 'error'
              const cancelled = st === 'cancelled' || st === 'canceled'
              if (failed || cancelled) {
                return (
                  <div className="rounded-2xl border border-rose-200/80 bg-rose-50/50 px-4 py-3">
                    <div className="text-[13px] font-semibold text-rose-950">
                      {failed ? 'Run failed' : 'Run cancelled'}
                    </div>
                    <p className="mt-0.5 text-[12px] text-rose-900/80">
                      Fix the graph or inputs, then re-run from the Editor. Check Logs for the failing step.
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => void openGraphInBuilder()}
                      >
                        Open Editor
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => setPanel('logs')}
                      >
                        View logs
                      </button>
                      {failed ? (
                        <button
                          type="button"
                          className="btn-secondary"
                          disabled={explainBusy}
                          onClick={() => void explainFailure()}
                        >
                          {explainBusy ? 'Creating…' : 'Explain / propose fix'}
                        </button>
                      ) : null}
                    </div>
                  </div>
                )
              }
              if (!succeeded) {
                // running / queued / paused — no promote
                return runModels.length > 0 ? (
                  <div className="rounded-2xl border border-ink-200/70 bg-white px-4 py-3">
                    <div className="text-[13px] font-semibold text-ink-950">Models from this run</div>
                    <ul className="mt-2 space-y-1.5">
                      {runModels.map((m) => {
                        const stages = m.stages || {}
                        const stageBits = Object.entries(stages)
                          .map(([k, v]) => `${k}${v?.slug ? `:${v.slug}` : ''}`)
                          .join(' · ')
                        return (
                          <li
                            key={m.name}
                            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-ink-200/80 bg-ink-50/50 px-2.5 py-1.5 text-[12px]"
                          >
                            <span className="font-medium text-ink-900">{m.name}</span>
                            <span className="font-mono text-[11px] text-ink-500">{stageBits || 'registered'}</span>
                          </li>
                        )
                      })}
                    </ul>
                  </div>
                ) : null
              }
              return (
                <div id="run-promote-panel" className="rounded-2xl border border-accent-200/70 bg-accent-50/40 px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 max-w-xl">
                      <div className="text-[13px] font-semibold text-ink-950">Promote & models</div>
                      <p className="mt-0.5 text-[12px] text-ink-600">
                        Promote this successful train run into the model registry (latest / staging / prod).
                        Model prod approval is API-only (<code className="text-[11px]">POST /models/.../request-prod</code> |{' '}
                        <code className="text-[11px]">approve-prod</code>).
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <label className="inline-flex items-center gap-1.5 text-[11px] text-ink-500">
                        <span className="sr-only">Promote alias</span>
                        <select
                          className="rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800"
                          value={promoteAlias}
                          onChange={(e) =>
                            setPromoteAlias(e.target.value as 'latest' | 'staging' | 'prod')
                          }
                        >
                          <option value="latest">latest</option>
                          <option value="staging">staging</option>
                          <option value="prod">prod</option>
                        </select>
                      </label>
                      <button type="button" className="btn-primary" onClick={() => void promote()}>
                        Promote
                      </button>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-accent-200/50 pt-3">
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
                      {registerBusy ? 'Registering…' : 'Register model'}
                    </button>
                  </div>
                  {runModels.length === 0 ? (
                    <p className="mt-2 text-[12px] text-ink-500">
                      No registry models linked yet. Promote with staging or register above.
                    </p>
                  ) : (
                    <ul className="mt-2 space-y-1.5">
                      {runModels.map((m) => {
                        const stages = m.stages || {}
                        const stageBits = Object.entries(stages)
                          .map(([k, v]) => `${k}${v?.slug ? `:${v.slug}` : ''}`)
                          .join(' · ')
                        return (
                          <li
                            key={m.name}
                            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-ink-200/80 bg-white px-2.5 py-1.5 text-[12px]"
                          >
                            <span className="font-medium text-ink-900">{m.name}</span>
                            <span className="font-mono text-[11px] text-ink-500">{stageBits || 'registered'}</span>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>
              )
            })()}

            <div className="flex flex-wrap gap-1 rounded-xl bg-ink-100/70 p-1">
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
            {panel === 'logs' && (
              <div className="space-y-2">
                <p className="text-xs text-ink-500">
                  Chronological execution log — what each step printed while the pipeline ran. Use Lineage for node order; Run outputs for downloads.
                </p>
                <div className="max-h-[28rem] overflow-auto rounded-2xl bg-ink-950 p-4 font-mono text-[11px] leading-5 text-ink-100 shadow-soft">
                  {logs.length === 0 ? (
                    <div className="text-ink-500">No logs recorded for this run.</div>
                  ) : (
                    formattedLogs.map(({ i, l, line }) => {
                      const failed = line.level === 'error' || String(l.level).toUpperCase() === 'ERROR'
                      const msg = line.text
                      const nodeHint = (() => {
                        const m = msg.match(/\bnode[_\s]?id[=: ]+([A-Za-z0-9_.-]+)/i)
                          || msg.match(/\b(?:executing|completed|failed)\s+([A-Za-z0-9_.-]+)/i)
                        return m ? m[1] : null
                      })()
                      return (
                        <div key={i} className={failed ? 'text-rose-300' : ''}>
                          {nodeHint ? (
                            <span className="mr-1.5 rounded bg-ink-800 px-1 text-[10px] text-accent-300">{humanNodeLabel(nodeHint)}</span>
                          ) : null}
                          {msg}
                        </div>
                      )
                    })
                  )}
                </div>
              </div>
            )}
            {panel === 'debug' && (
              <div className="space-y-3">
                <p className="text-xs text-ink-500">
                  Operator details: status, per-node stats, errors, and paths. Not a substitute for Logs or Lineage.
                </p>
                {!debug ? (
                  <div className="text-sm text-ink-500">No details report.</div>
                ) : (
                  <>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {(
                        [
                          ['Artifacts', debug.artifact_count],
                          ['Provenance', debug.provenance_count],
                          ['Checkpoints', debug.checkpoint_count],
                          ['Errors', debug.error_count],
                        ] as Array<[string, unknown]>
                      ).map(([label, val]) => (
                        <div key={label} className="rounded-xl border border-ink-100 bg-white px-3 py-2">
                          <div className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">{label}</div>
                          <div className="mt-0.5 text-lg font-semibold tabular-nums text-ink-900">{String(val ?? 0)}</div>
                        </div>
                      ))}
                    </div>
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
                          Nodes executed
                        </div>
                        <ul className="divide-y divide-ink-100">
                          {(debug.node_stats as Array<Record<string, unknown>>).map((n, i) => (
                            <li key={i} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                              <span className="font-medium text-ink-900">
                                {humanNodeLabel(String(n.node_type || n.node_id || `node-${i}`))}
                              </span>
                              <span className="font-mono text-[11px] text-ink-400">{String(n.node_id || '')}</span>
                              {n.duration_ms != null ? (
                                <span className="tabular-nums text-[11px] text-ink-500">{String(n.duration_ms)} ms</span>
                              ) : null}
                              {n.cache_hit ? (
                                <span className="rounded bg-amber-50 px-1.5 text-[10px] text-amber-800">cache</span>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <CollapsibleJson value={debug} label="Raw details JSON" />
                  </>
                )}
              </div>
            )}
            {panel === 'checkpoints' && (
              <div className="space-y-2">
                <p className="text-xs text-ink-500">
                  Optional per-node snapshots when the graph ran with checkpointing. Closest thing to port-level I/O samples.
                </p>
                {checkpoints.length === 0 ? (
                  <div className="text-sm text-ink-500">No checkpoints for this run.</div>
                ) : (
                  checkpoints.map((c) => (
                    <button
                      key={c}
                      type="button"
                      className="block w-full rounded-lg border border-ink-200 px-3 py-2 text-left text-sm hover:bg-ink-50"
                      onClick={() => void loadCheckpointSamples(c)}
                    >
                      {humanNodeLabel(c)}
                    </button>
                  ))
                )}
                {samples != null && <CollapsibleJson value={samples} label="Samples" />}
              </div>
            )}
            {panel === 'artifacts' && (
              <div className="space-y-3">
                <p className="text-xs text-ink-500">
                  Downloadable outputs for this run, grouped by producing node when known. Datasets → Outputs is the shared library — different from these per-run downloads.
                </p>
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
                    const g = guessNodeFromPath(f.path, runArtifacts)
                    const list = groups.get(g) || []
                    list.push(f)
                    groups.set(g, list)
                  }
                  const order: string[] = []
                  for (const a of runArtifacts) {
                    const nid = String(a.node_id || '').trim()
                    if (nid && !order.includes(nid) && groups.has(nid)) order.push(nid)
                  }
                  for (const k of groups.keys()) {
                    if (!order.includes(k)) order.push(k)
                  }
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
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {['succeeded', 'completed', 'success'].includes((runStatus || '').toLowerCase()) ? (
                            <>
                              <label className="inline-flex items-center gap-1.5 text-[11px] text-ink-500">
                                <span className="sr-only">Promote alias</span>
                                <select
                                  className="rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800"
                                  value={promoteAlias}
                                  onChange={(e) =>
                                    setPromoteAlias(e.target.value as 'latest' | 'staging' | 'prod')
                                  }
                                >
                                  <option value="latest">latest</option>
                                  <option value="staging">staging</option>
                                  <option value="prod">prod</option>
                                </select>
                              </label>
                              <button type="button" className="btn-secondary" onClick={() => void promote()}>
                                Promote
                              </button>
                            </>
                          ) : null}
                          {outputFiles.length > 0 && (
                            <button type="button" className="btn-secondary" onClick={() => void downloadZip()}>
                              <Download className="h-3.5 w-3.5" /> Download all
                            </button>
                          )}
                        </div>
                      </div>
                      {outputFiles.length === 0 ? (
                        <div className="text-sm text-ink-500">No downloadable files for this run.</div>
                      ) : (
                        <div className="space-y-4">
                          {order.map((group) => (
                            <div key={group}>
                              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                                {group === 'run' ? 'Run-level files' : humanNodeLabel(group)}
                              </div>
                              <ul className="space-y-2">
                                {(groups.get(group) || []).map((f) => {
                                  const key = `${f.path}-${f.name}`
                                  const open = expandedFile === key
                                  return (
                                    <li key={key} className="rounded-xl border border-ink-200 bg-white px-3 py-2">
                                      <div className="flex items-start justify-between gap-2">
                                        <button
                                          type="button"
                                          className="min-w-0 flex-1 text-left"
                                          onClick={() => setExpandedFile(open ? null : key)}
                                        >
                                          <div className="truncate text-sm font-medium text-ink-900">{f.name}</div>
                                          <div className="truncate font-mono text-[10px] text-ink-400">{f.path}</div>
                                          <div className="text-[11px] text-ink-500">
                                            {f.kind} · {formatBytes(f.size)}
                                            {isPreviewJson(f) ? ' · JSON' : ''}
                                            {isPreviewImage(f) ? ' · image' : ''}
                                          </div>
                                        </button>
                                        {f.kind !== 'dir' && (
                                          <button type="button" className="btn-primary shrink-0" onClick={() => void downloadFile(f)}>
                                            <Download className="h-3.5 w-3.5" /> Download
                                          </button>
                                        )}
                                      </div>
                                      {(open || previewUrls[f.path] || jsonPreviews[f.path]) && (
                                        <div className="mt-2">
                                          {previewUrls[f.path] ? (
                                            <img
                                              src={previewUrls[f.path]}
                                              alt={f.name}
                                              className="max-h-64 w-full rounded-lg border border-ink-100 object-contain bg-ink-50"
                                            />
                                          ) : null}
                                          {jsonPreviews[f.path] ? (
                                            <pre className="max-h-48 overflow-auto rounded-lg bg-ink-950 p-3 font-mono text-[10px] text-ink-100">
                                              {jsonPreviews[f.path]}
                                            </pre>
                                          ) : null}
                                          {!previewUrls[f.path] && !jsonPreviews[f.path] && open ? (
                                            <p className="text-[12px] text-ink-500">No inline preview for this type — download to open.</p>
                                          ) : null}
                                        </div>
                                      )}
                                    </li>
                                  )
                                })}
                              </ul>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )
                })()}
              </div>
            )}
            {panel === 'lineage' && selected ? (
              <RunLineagePanel
                runId={selected}
                runMeta={
                  (detail?.meta && typeof detail.meta === 'object'
                    ? (detail.meta as Record<string, unknown>)
                    : null) ||
                  (detail as Record<string, unknown> | null)
                }
              />
            ) : null}
          </>
        )}
      </div>
    </div>
  )
}
