import React from 'react'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  MarkerType,
  ConnectionLineType,
  getRectOfNodes,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { MINIMAP_MARGIN, minimapLayout } from './canvasMinimap'
import { logBarSummary, prettyCategory } from './editorChrome'
import {
  catalogLoadState,
  catalogPrefKey,
  catalogRetryDelay,
  catalogShouldOpen,
  helpNeedsMore,
  inspectorModeFor,
  isSignificantResize,
  leftAnchoredViewport,
  planFit,
  stepSettingsState,
  toolbarCompact,
} from './editorLayout'
import { learningRateLinks, learningRateNote } from './learningRate'
import { useViewport, viewportSizeFor } from '../../lib/viewport'
import { PipelineSwitcher } from './PipelineSwitcher'
import {
  Play,
  CheckCircle2,
  Trash2,
  Download,
  Upload,
  Square,
  Save,
  MoreHorizontal,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  ExternalLink,
  X,
  Clock,
  Sparkles,
  Undo2,
  Redo2,
  SlidersHorizontal,
} from 'lucide-react'
import { apiFetch, apiJson, ApiError, getApiToken, parseError } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { goView } from '../../routes/nav'
import {
  exportLayerSpecs,
  loadPresetIntoConfig,
  type ModelBuilderPreset,
} from './modelBuilderPresets'
import { stampProjectOnGraph } from '../../lib/projectStamp'
import { normalizeRunStatus } from '../../lib/runStatus'
import {
  ConfirmButton,
  EmptyState,
  ErrorBanner,
  NeedProjectPrompt,
  SegmentedTabs,
  StatusBadge,
} from '../../components/ui'
import { formatExecutionLine, formatValidationErrors, humanNodeLabel, isIsolatedRuntime, schemaFieldHint, schemaFieldLabel, shortRunId, skipConsecutiveByText } from '../../lib/format'
import {
  buildGraphFromCanvas,
  type NodePlacement,
  catalogPorts,
  type GraphIR,
  type NodeCatalogEntry,
  canonicalPort,
} from '../../types/graph'
import GraphynNode, { ConfigFieldEditor, categoryLook, normalizeExecStatus, type CredentialOption, type GraphynNodeData, type NodeExecStatus } from './GraphynNode'
import DeletableEdge from './DeletableEdge'
import TriggersDock from './TriggersDock'
import RunInputsDialog from './RunInputsDialog'
import { ErrorHandlingEditor, EdgeConditionEditor } from './WorkflowInspector'
import {
  SELECT_EDGE_EVENT,
  errorPortOf,
  needsRunDialog,
  onErrorFromIr,
  retryFromIr,
  runInputsSpec,
  type RunInputsSpec,
} from './workflowIr'

type RunExtras = { inputs?: Record<string, Record<string, unknown>>; parameters?: Record<string, unknown> }
import AgentDrawer from './AgentDrawer'
import {
  badgeFromServerStatus,
  decorateNodeData,
  portsNeedResync,
  defaultsFromSchema,
  isolateNodeWriteConfig,
  rebindNodeWriteConfig,
  uniquifyWriteConfigsAmongNodes,
  isTerminalBadge,
  reconcileNodeStatuses,
  rememberRunOutcome,
  rememberedRunOutcome,
  runStartErrorMessage,
  runStartErrorTitle,
  type ExecBadgeStatus,
  type KnownRunOutcome,
} from './builderRunState'
import { openModeExplainer } from '../../lib/menus'
import { registerNavigationGuard } from '../../lib/navigationGuard'
import {
  changeKey,
  createHistory,
  editorSnapshot,
  historyShortcut,
  pushHistory,
  redoHistory,
  snapshotSignature,
  undoHistory,
  type EditorSnapshot,
  type History,
} from './graphHistory'
import {
  formatConfigIssues,
  isFieldVisible,
  validateNodeConfigs,
  type ConfigIssue,
} from './configValidation'
import { countErrorRows, dedupeErrorRows, isErrorRow } from './logDedupe'
import { canvasPathView } from './canvasPaths'
import { journalToLogEntries, relabelLine } from './journalLog'
import {
  collapseProgressRows,
  finishedNodeIds,
  formatProgressLine,
  latestProgressByNode,
  parseProgress,
  type NodeProgress,
} from '../runs/runProgress'
import { ProgressLogLine } from '../runs/RunResults'
import { fetchRunGraph } from '../../lib/runGraph'
import { runTitle } from '../runs/runResults'
import { diffGraphs, parsePipelineDrift, unscopeRunPaths } from './graphDrift'
import { RunDriftBanner } from './RunDriftBanner'
import { compactNodeLabel } from '../runs/runRecord'

const nodeTypes = { graphyn: GraphynNode }
/**
 * Fit the whole graph on load / pipeline switch so no node is cut off: zoom
 * out as far as the canvas allows (same floor as manual zoom), never above 1.
 */
const FIT_VIEW_OPTIONS = { padding: 0.12, minZoom: 0.15, maxZoom: 1 }
const edgeTypes = { default: DeletableEdge }

const EDGE_STYLE = { stroke: '#555555', strokeWidth: 2.75 }
const EDGE_MARKER = { type: MarkerType.ArrowClosed, width: 14, height: 14, color: '#555555' }
const defaultEdgeOptions = {
  type: 'default' as const,
  style: EDGE_STYLE,
  markerEnd: EDGE_MARKER,
}

// Catalog open state is stored per viewport size class (`catalogPrefKey`, editorLayout.ts).
const MINIMAP_OPEN_KEY = 'graphyn.builder.minimapOpen'
/**
 * v2: only a *manual* expand/collapse is stored (v1 also stored the automatic
 * expand on Run, so an empty log stayed open at ~40% of the height forever).
 */
const LOG_COLLAPSED_KEY = 'graphyn.builder.logCollapsed.v2'
const CONNECT_TIP_DISMISSED_KEY = 'graphyn.builder.connectTipDismissed'
/** Catalog → canvas HTML5 drag payload (node_type string). */
const CATALOG_DND_MIME = 'application/graphyn-node'

function readStoredBool(key: string): boolean | null {
  try {
    const v = localStorage.getItem(key)
    if (v === null) return null
    return v === '1' || v === 'true'
  } catch {
    return null
  }
}

function readBoolPref(key: string, defaultValue: boolean): boolean {
  return readStoredBool(key) ?? defaultValue
}

function writeBoolPref(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* ignore */
  }
}

/** Light pre-run check: DatasetIngest / path-like nodes with empty path config. */
function findMissingInputPaths(
  nodes: Array<{ id: string; data: { nodeType: string; label?: string; config?: Record<string, unknown> } }>,
): Array<{ id: string; label: string; nodeType: string }> {
  const out: Array<{ id: string; label: string; nodeType: string }> = []
  for (const n of nodes) {
    const t = n.data.nodeType || ''
    const bare = t.replace(/^Isolated_/, '')
    const isPathNode =
      /DatasetIngest/i.test(bare) ||
      /^(LocalFile|FileInput|AudioInput|LoadDataset|DatasetLoader)/i.test(bare)
    if (!isPathNode) continue
    const cfg = n.data.config ?? {}
    const pathKeys = ['path', 'input_path', 'dataset_path', 'manifest_path', 'audio_path', 'source_path']
    const hasAnyKey = pathKeys.some((k) => k in cfg)
    // DatasetIngest always expects a path; others only when a path-like key exists.
    if (!/DatasetIngest/i.test(bare) && !hasAnyKey) continue
    const values = pathKeys.map((k) => String(cfg[k] ?? '').trim()).filter(Boolean)
    // HuggingFace / remote ids are fine non-empty strings; empty is the problem.
    if (values.length === 0) {
      out.push({
        id: n.id,
        label: n.data.label || humanNodeLabel(t),
        nodeType: t,
      })
    }
  }
  return out
}


function layoutLeftToRight<T extends { id: string; position: { x: number; y: number } }>(
  nodes: T[],
  edges: Array<{ source: string; target: string }>,
  force = false,
): T[] {
  if (nodes.length === 0) return nodes
  const xs = nodes.map((n) => n.position.x)
  const ys = nodes.map((n) => n.position.y)
  const wide = Math.max(...xs) - Math.min(...xs)
  const tall = Math.max(...ys) - Math.min(...ys)
  if (!force && wide >= tall && wide > 80) return nodes
  const ids = nodes.map((n) => n.id)
  const outgoing = new Map(ids.map((id) => [id, [] as string[]]))
  const incoming = new Map(ids.map((id) => [id, 0]))
  for (const e of edges) {
    outgoing.get(e.source)?.push(e.target)
    incoming.set(e.target, (incoming.get(e.target) ?? 0) + 1)
  }
  const rank = new Map<string, number>()
  const visit = (id: string, r: number) => {
    if ((rank.get(id) ?? -1) >= r) return
    rank.set(id, r)
    for (const t of outgoing.get(id) ?? []) visit(t, r + 1)
  }
  for (const id of ids) {
    if ((incoming.get(id) ?? 0) === 0) visit(id, 0)
  }
  for (const id of ids) if (!rank.has(id)) rank.set(id, 0)
  const byRank = new Map<number, string[]>()
  for (const id of ids) {
    const r = rank.get(id) ?? 0
    const arr = byRank.get(r) ?? []
    arr.push(id)
    byRank.set(r, arr)
  }
  // Node cards are ~272 px wide and up to ~90 px tall (two-line labels).
  const COL = 340
  const ROW = 130
  return nodes.map((n) => {
    const r = rank.get(n.id) ?? 0
    const col = byRank.get(r) ?? []
    const i = col.indexOf(n.id)
    return { ...n, position: { x: 48 + r * COL, y: 48 + i * ROW } }
  })
}

function slugifyName(raw: string): string {
  const s = raw.trim().replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '')
  return s || 'pipeline'
}

/**
 * Inspector field help: full text, wrapped (never cut with "…"); text longer
 * than ~3 lines is clamped behind a "more" toggle. The toggle is a span (not a
 * <button>) so it never becomes the enclosing <label>'s control.
 */
function FieldHelp({ text }: { text: string }) {
  const [open, setOpen] = React.useState(false)
  const long = helpNeedsMore(text)
  const toggle = (e: React.SyntheticEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setOpen((v) => !v)
  }
  return (
    <span className="mt-0.5 block text-[11px] leading-snug text-ink-400">
      <span className={`block whitespace-pre-line break-words ${long && !open ? 'line-clamp-3' : ''}`}>{text}</span>
      {long ? (
        <span
          role="button"
          tabIndex={0}
          aria-expanded={open}
          className="cursor-pointer font-medium text-accent-700 hover:underline"
          onClick={toggle}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') toggle(e)
          }}
        >
          {open ? 'less' : 'more'}
        </span>
      ) : null}
    </span>
  )
}

function BuilderInner() {
  const catalog = useAppStore((s) => s.catalog)
  const bootStatus = useAppStore((s) => s.bootStatus)
  const bootError = useAppStore((s) => s.bootError)
  const refreshCatalog = useAppStore((s) => s.refreshCatalog)
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const seed = useAppStore((s) => s.seed)
  const setSeed = useAppStore((s) => s.setSeed)
  const isRunning = useAppStore((s) => s.isRunning)
  const setIsRunning = useAppStore((s) => s.setIsRunning)
  const addLog = useAppStore((s) => s.addLog)
  const clearLogs = useAppStore((s) => s.clearLogs)
  const logs = useAppStore((s) => s.logs)
  const lastRunId = useAppStore((s) => s.lastRunId)
  const setLastRunId = useAppStore((s) => s.setLastRunId)
  const setStatusMessage = useAppStore((s) => s.setStatusMessage)
  const setRunOutcome = useAppStore((s) => s.setRunOutcome)
  const runOutcome = useAppStore((s) => s.runOutcome)
  const pushToast = useAppStore((s) => s.pushToast)
  const pendingProposalCount = useAppStore((s) => s.pendingProposalCount)
  const openProposals = useAppStore((s) => s.openProposals)
  const openRun = useAppStore((s) => s.openRun)
  const openData = useAppStore((s) => s.openData)
  const openProjects = useAppStore((s) => s.openProjects)
  const builderDataset = useAppStore((s) => s.builderDataset)
  const activeProject = useAppStore((s) => s.activeProject)
  const setBuilderDataset = useAppStore((s) => s.setBuilderDataset)
  const setGetCanvasGraph = useAppStore((s) => s.setGetCanvasGraph)
  const backendMode = useAppStore((s) => s.backendMode)

  const [nodes, setNodes, onNodesChange] = useNodesState<GraphynNodeData>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const { screenToFlowPosition, fitView, getNodes, setViewport } = useReactFlow()
  /** True while the viewport is the automatic fit (no user pan/zoom since) — panel / resize changes re-fit. */
  const autoFitRef = React.useRef(false)
  /** Canvas size at the last automatic fit (re-fit only on a significant change). */
  const lastFitBoxRef = React.useRef({ w: 0, h: 0 })
  /** Graph shown at the readable minimum zoom (not all of it) → show "Fit all". */
  const [partialView, setPartialView] = React.useState(false)
  /** Latest node_progress per running node (canvas bar + log line); view-only. */
  const [nodeProgress, setNodeProgress] = React.useState<Record<string, NodeProgress>>({})
  /** Run id whose journal currently fills the execution log (hydrated, not streamed). */
  const hydratedRunRef = React.useRef<string | null>(null)
  /** Set by loadGraph: the next linked-run hydrate may replace the log. */
  const allowHydrateRef = React.useRef(false)
  /** Bumped by loadGraph → fit view + re-check the linked run. */
  const [loadGen, setLoadGen] = React.useState(0)
  const [filter, setFilter] = React.useState('')
  const [categoryFilter, setCategoryFilter] = React.useState('all')
  const [templateName, setTemplateName] = React.useState('')
  const [graphName, setGraphName] = React.useState('pipeline')
  const [moreOpen, setMoreOpen] = React.useState(false)
  const [showRawLogs, setShowRawLogs] = React.useState(false)
  const [logHeight, setLogHeight] = React.useState(148)
  const { width: viewportWidth } = useViewport()
  const sizeClass = viewportSizeFor(viewportWidth)
  /** docked (≥1280, shrinks the canvas) · drawer (overlay) · sheet (<768, bottom). */
  const inspectorMode = inspectorModeFor(viewportWidth)
  // Canvas first: the catalog opens only when the canvas keeps ≥700px; a manual
  // toggle is remembered per viewport size class (catalogPrefKey).
  const [catalogOpen, setCatalogOpen] = React.useState(() => {
    const w = typeof window === 'undefined' ? 0 : window.innerWidth
    // Before measuring, estimate the Editor area as the viewport minus the app nav.
    return catalogShouldOpen({ areaWidth: w - (w >= 1280 ? 240 : 56), stored: readStoredBool(catalogPrefKey(w)) })
  })
  const toggleCatalog = () =>
    setCatalogOpen((v) => {
      writeBoolPref(catalogPrefKey(window.innerWidth), !v)
      return !v
    })
  /** Editor area (catalog + canvas + docked inspector) and toolbar column widths. */
  const [areaWidth, setAreaWidth] = React.useState(0)
  const [mainColWidth, setMainColWidth] = React.useState(0)
  const widthObservers = React.useRef(new Map<string, ResizeObserver>())
  const observeWidth = React.useCallback(
    (key: string, set: (w: number) => void) => (el: HTMLDivElement | null) => {
      widthObservers.current.get(key)?.disconnect()
      widthObservers.current.delete(key)
      if (!el || typeof ResizeObserver === 'undefined') return
      const measure = () => set(Math.round(el.clientWidth))
      measure()
      const ro = new ResizeObserver(measure)
      ro.observe(el)
      widthObservers.current.set(key, ro)
    },
    [],
  )
  const areaRef = React.useMemo(() => observeWidth('area', setAreaWidth), [observeWidth])
  const mainColRef = React.useMemo(() => observeWidth('main', setMainColWidth), [observeWidth])
  const compactToolbar = toolbarCompact(mainColWidth)
  /** Inspector shows only for a selection, Graph settings, or the Agent drawer. */
  const [graphSettingsOpen, setGraphSettingsOpen] = React.useState(false)
  const [minimapOpen, setMinimapOpen] = React.useState(() => readBoolPref(MINIMAP_OPEN_KEY, true))
  /** Canvas box size → minimap size / visibility (hidden below the breakpoint). */
  const [canvasBox, setCanvasBox] = React.useState({ w: 0, h: 0 })
  const canvasRoRef = React.useRef<ResizeObserver | null>(null)
  // Callback ref: (re)attaches whenever the canvas box mounts/unmounts.
  const canvasElRef = React.useRef<HTMLDivElement | null>(null)
  const canvasBoxRef = React.useCallback((el: HTMLDivElement | null) => {
    canvasElRef.current = el
    canvasRoRef.current?.disconnect()
    canvasRoRef.current = null
    if (!el || typeof ResizeObserver === 'undefined') return
    const measure = () =>
      setCanvasBox((prev) =>
        prev.w === el.clientWidth && prev.h === el.clientHeight ? prev : { w: el.clientWidth, h: el.clientHeight },
      )
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    canvasRoRef.current = ro
  }, [])
  const minimap = minimapLayout(canvasBox.w, canvasBox.h)
  const [logCollapsed, setLogCollapsed] = React.useState(() => readBoolPref(LOG_COLLAPSED_KEY, true))
  const [connectTipDismissed, setConnectTipDismissed] = React.useState(() =>
    readBoolPref(CONNECT_TIP_DISMISSED_KEY, false),
  )
  const [runHadErrors, setRunHadErrors] = React.useState(false)
  // Authoritative outcome for `lastRunId` (server status, or this session's own
  // terminal event for that exact run id). Never defaults to succeeded.
  const [serverBadge, setServerBadge] = React.useState<{ runId: string; status: ExecBadgeStatus } | null>(null)
  const toastCount = useAppStore((s) => s.toasts.length)
  const [inspectorId, setInspectorId] = React.useState<string | null>(null)
  const [advancedOpen, setAdvancedOpen] = React.useState(false)
  const [loadPresetArch, setLoadPresetArch] = React.useState<ModelBuilderPreset>('ds_cnn')
  const [projectPipelineList, setProjectPipelineList] = React.useState<
    Array<{
      name: string
      environments?: {
        draft?: string | null
        staging?: string | null
        prod?: string | null
        pending_prod?: { version?: string } | null
      }
    }>
  >([])
  const [pipelinePick, setPipelinePick] = React.useState('')
  const [pipelineEnv, setPipelineEnv] = React.useState<'draft' | 'staging' | 'prod'>('draft')
  const [triggersOpen, setTriggersOpen] = React.useState(false)
  const [runDialog, setRunDialog] = React.useState<{ spec: RunInputsSpec; mode: 'stream' | 'async' } | null>(null)
  const [agentOpen, setAgentOpen] = React.useState(false)
  const [credentialsList, setCredentialsList] = React.useState<CredentialOption[]>([])

  React.useEffect(() => {
    setAdvancedOpen(false)
    setLoadPresetArch('ds_cnn')
  }, [inspectorId])

  React.useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const creds = await apiJson<{ items?: CredentialOption[] }>('/credentials')
        if (!cancelled) {
          setCredentialsList(
            Array.isArray(creds.items)
              ? creds.items.map((c) => ({
                  id: c.id,
                  name: c.name,
                  kind: c.kind,
                  is_default: c.is_default,
                }))
              : [],
          )
        }
      } catch {
        if (!cancelled) setCredentialsList([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Fetch project pipelines for env chips

  React.useEffect(() => {
    if (!activeProject) {
      setProjectPipelineList([])
      setPipelinePick('')
      return
    }
    let cancelled = false
    // Captured synchronously, before the async fetch below — a proposal
    // "Accept -> Editor" (or an agent-generated graph) sets this in the store
    // before BuilderView ever mounts, so it's already true here at effect-run
    // time regardless of how long our own fetch takes. Reading it only AFTER
    // the fetch resolves would race: the other effect that consumes
    // pendingGraph can finish first (clearing it back to null) and we'd see
    // a false "nothing claimed it yet" and clobber the just-accepted graph
    // with this project's default pipeline. This really happened: accepting
    // an empty-stub proposal into the Editor showed the project's saved
    // pipeline instead of the stub the user just accepted.
    const hadPendingGraphAtMount = Boolean(useAppStore.getState().pendingGraph)
    void (async () => {
      try {
        const pipes = await apiJson<
          Array<{
            name: string
            environments?: {
              draft?: string | null
              staging?: string | null
              prod?: string | null
              pending_prod?: { version?: string } | null
            }
          }>
        >(`/projects/${encodeURIComponent(activeProject)}/pipelines`)
        if (cancelled) return
        const list = Array.isArray(pipes) ? pipes : []
        setProjectPipelineList(list)
        const autoPick = list[0]?.name
        // Same race as below: a pendingGraph already claimed (or is about to
        // claim) the canvas, so don't default the picker to "the project's
        // first saved pipeline" here either — that's exactly as misleading
        // as auto-loading it (see the comment below), just via the label
        // instead of the canvas.
        if (!hadPendingGraphAtMount && !useAppStore.getState().pendingGraph) {
          setPipelinePick((prev) => prev || autoPick || templateName || graphName || '')
        }
        // The line above can select a pipeline name in the toolbar's picker
        // purely because it's the project's only/first saved pipeline — with
        // nothing yet telling the canvas to actually load it. That left the
        // toolbar showing e.g. "basic-wakeword" selected while the canvas was
        // still blank ("pipeline", 0 nodes): Save uses `templateName` (not
        // this picker), so a Save in that state silently created a second,
        // confusingly-named "pipeline" entry instead of touching the one the
        // toolbar implied was open. Auto-load it for real, but only when
        // nothing has claimed the canvas yet (no explicit template/pipeline
        // chosen, no nodes placed) — never override an in-progress edit.
        if (
          !pipelinePick &&
          !templateName &&
          autoPick &&
          nodesRef.current.length === 0 &&
          !hadPendingGraphAtMount &&
          !useAppStore.getState().pendingGraph
        ) {
          void openPipelineEnv(autoPick, undefined, { confirm: false })
        }
      } catch {
        if (!cancelled) setProjectPipelineList([])
      }
    })()
    return () => {
      cancelled = true
    }
    // Intentionally project-only: re-checking templateName/pipelinePick/graphName
    // on every keystroke would re-fire this fetch and could re-trigger the
    // auto-load guard mid-edit. It only needs to run once per project.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProject])
  const [selectedEdgeId, setSelectedEdgeId] = React.useState<string | null>(null)
  // Condition chips live in the edge-label layer (outside the edge hit area).
  React.useEffect(() => {
    const onSelect = (e: Event) => {
      const id = (e as CustomEvent<string>).detail
      if (!id) return
      setSelectedEdgeId(id)
      setInspectorId(null)
    }
    window.addEventListener(SELECT_EDGE_EVENT, onSelect)
    return () => window.removeEventListener(SELECT_EDGE_EVENT, onSelect)
  }, [])
  const [actionError, setActionError] = React.useState<{ title: string; message: string; detail?: string } | null>(null)
  const moreRef = React.useRef<HTMLDivElement | null>(null)
  const abortRef = React.useRef<AbortController | null>(null)
  // Backend run id for the in-flight stream, kept in sync with the local
  // `runId` var inside handleRun so Cancel can reach the actual run even
  // though the global store's lastRunId may lag or belong to a prior run.
  const runIdRef = React.useRef<string | null>(null)
  const nodesRef = React.useRef(nodes)
  const edgesRef = React.useRef(edges)
  // Graph-level `parameters` from the loaded IR — the Builder has no editor for
  // these yet, so preserve verbatim through save rather than dropping them.
  const graphParametersRef = React.useRef<Record<string, unknown>>({})
  const logBodyRef = React.useRef<HTMLDivElement | null>(null)
  const stickToBottomRef = React.useRef(true)
  nodesRef.current = nodes
  edgesRef.current = edges
  const graphNameRef = React.useRef(graphName)
  graphNameRef.current = graphName

  React.useEffect(() => {
    if (isRunning) setLogCollapsed(false)
  }, [isRunning])

  /** Manual expand/collapse — the only log state that is remembered. */
  const setLogCollapsedByUser = (next: boolean) => {
    setLogCollapsed(next)
    writeBoolPref(LOG_COLLAPSED_KEY, next)
  }

  // A selection replaces Graph settings (deselecting then closes the inspector).
  React.useEffect(() => {
    if (inspectorId || selectedEdgeId) setGraphSettingsOpen(false)
  }, [inspectorId, selectedEdgeId])
  const inspectorVisible = Boolean(inspectorId || selectedEdgeId || graphSettingsOpen || agentOpen)
  const closeInspector = React.useCallback(() => {
    setInspectorId(null)
    setSelectedEdgeId(null)
    setGraphSettingsOpen(false)
    setAgentOpen(false)
  }, [])
  // Escape closes the inspector (not while typing in a field).
  React.useEffect(() => {
    if (!inspectorVisible || moreOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      const t = e.target as HTMLElement | null
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return
      closeInspector()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [inspectorVisible, moreOpen, closeInspector])

  React.useEffect(() => {
    if (!moreOpen) return
    const onDoc = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as HTMLElement)) setMoreOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMoreOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      window.removeEventListener('keydown', onKey)
    }
  }, [moreOpen])

  const attachHandlersRef = React.useRef<
    (node: Node<GraphynNodeData>) => Node<GraphynNodeData>
  >((n) => n)

  const attachHandlers = React.useCallback(
    (node: Node<GraphynNodeData>): Node<GraphynNodeData> => ({
      ...node,
      data: {
        ...node.data,
        onChangeConfig: (key, value) => {
          setNodes((nds) =>
            nds.map((n) =>
              n.id === node.id
                ? { ...n, data: { ...n.data, config: { ...n.data.config, [key]: value } } }
                : n,
            ),
          )
        },
        onChangePlacement: (next) => {
          setNodes((nds) =>
            nds.map((n) =>
              n.id === node.id ? { ...n, data: { ...n.data, placement: next } } : n,
            ),
          )
        },
        onChangeErrorPolicy: ({ onError, retry }) => {
          const current = nodesRef.current.find((n) => n.id === node.id)
          const prevPort = errorPortOf(current?.data.onError)
          const nextPort = errorPortOf(onError)
          setNodes((nds) =>
            nds.map((n) => (n.id === node.id ? { ...n, data: { ...n.data, onError, retry } } : n)),
          )
          // Leaving Route mode (or renaming the port) orphans wires from the old
          // error port — the server rejects them, so drop them here.
          if (prevPort && prevPort !== nextPort) {
            const catalogHasPort = (current?.data.outputs ?? []).some((p) => p.name === prevPort)
            if (!catalogHasPort) {
              const dropped = edgesRef.current.filter(
                (e) => e.source === node.id && canonicalPort(e.sourceHandle, 'output') === prevPort,
              ).length
              if (dropped > 0) {
                setEdges((eds) =>
                  eds.filter((e) => !(e.source === node.id && canonicalPort(e.sourceHandle, 'output') === prevPort)),
                )
                pushToast(`Removed ${dropped} error-branch connection${dropped === 1 ? '' : 's'}`, 'info')
              }
            }
          }
        },
        onDelete: () => {
          setNodes((nds) => nds.filter((n) => n.id !== node.id))
          setEdges((eds) => eds.filter((e) => e.source !== node.id && e.target !== node.id))
          setInspectorId((id) => (id === node.id ? null : id))
        },
        onDuplicate: () => {
          const source = nodesRef.current.find((n) => n.id === node.id) || node
          const newId = `${source.data.nodeType}_${crypto.randomUUID().slice(0, 8)}`
          const clone = attachHandlersRef.current({
            ...source,
            id: newId,
            position: {
              x: source.position.x + 40,
              y: source.position.y + 40,
            },
            selected: false,
            data: {
              ...source.data,
              // Drop transient run chrome; keep type/ports/config/placement.
              status: 'idle',
              lastError: undefined,
              configIssues: undefined,
              label: source.data.label,
              config: rebindNodeWriteConfig({ ...(source.data.config ?? {}) }, source.id, newId),
              inputs: [...(source.data.inputs ?? [])],
              outputs: [...(source.data.outputs ?? [])],
              catalogDecorated: source.data.catalogDecorated,
            },
          })
          setNodes((nds) => [...nds.map((n) => ({ ...n, selected: false })), { ...clone, selected: true }])
          setInspectorId(newId)
        },
        onOpenInspector: () => setInspectorId(node.id),
        onValidateConfig: () => {
          void (async () => {
            try {
              const current = nodesRef.current.find((n) => n.id === node.id)
              const res = await apiJson<{ valid: boolean; errors?: unknown }>(
                `/nodes/${encodeURIComponent(node.data.nodeType)}/validate-config`,
                {
                  method: 'POST',
                  body: JSON.stringify({ config: current?.data.config ?? node.data.config }),
                },
              )
              if (res.valid) pushToast(`${node.data.nodeType} config valid`, 'success')
              else pushToast(`Invalid config: ${formatValidationErrors(res.errors)}`, 'error')
            } catch (err) {
              pushToast(err instanceof Error ? err.message : String(err), 'error')
            }
          })()
        },
      },
    }),
    [setNodes, setEdges, pushToast],
  )
  attachHandlersRef.current = attachHandlers


  /**
   * Backend `node_index` is the index in the planner's execution order, NOT
   * the canvas array index. Approximate that order client-side (stable Kahn
   * topological sort over the canvas edges, ties broken by canvas order) so
   * the rare event lacking `node_id` can still be mapped. Returns null when
   * the graph has a cycle (no reliable order).
   */
  const executionOrderIds = React.useCallback((): string[] | null => {
    const ns = nodesRef.current
    const es = edgesRef.current
    const indeg = new Map<string, number>()
    const out = new Map<string, string[]>()
    for (const n of ns) {
      indeg.set(n.id, 0)
      out.set(n.id, [])
    }
    for (const e of es) {
      if (!indeg.has(e.source) || !indeg.has(e.target)) continue
      indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1)
      out.get(e.source)!.push(e.target)
    }
    const order: string[] = []
    const done = new Set<string>()
    while (order.length < ns.length) {
      const next = ns.find((n) => !done.has(n.id) && (indeg.get(n.id) ?? 0) === 0)
      if (!next) return null
      done.add(next.id)
      order.push(next.id)
      for (const t of out.get(next.id) ?? []) indeg.set(t, (indeg.get(t) ?? 0) - 1)
    }
    return order
  }, [])

  const setNodeExecStatus = React.useCallback(
    (
      matcher: { index?: number; nodeId?: string; nodeType?: string },
      status: NodeExecStatus,
      extra?: { lastError?: string },
    ) => {
      const norm = normalizeExecStatus(status)
      // Match by node_id only. Fall back to the execution-order index only
      // when the event carries no node_id at all.
      let targetId: string | undefined = matcher.nodeId
      if (!targetId && matcher.index != null && !Number.isNaN(matcher.index)) {
        targetId = executionOrderIds()?.[matcher.index]
      }
      setNodes((nds) =>
        nds.map((n) => {
          const patch = (data: typeof n.data) => ({
            ...n,
            data: {
              ...data,
              status: norm,
              lastError: extra?.lastError !== undefined ? extra.lastError : (norm === 'failed' ? data.lastError : undefined),
            },
          })
          if (targetId) return n.id === targetId ? patch(n.data) : n
          // Last resort: first pending match by type only when neither id nor index given
          if (
            matcher.nodeType &&
            (matcher.index == null || Number.isNaN(matcher.index)) &&
            n.data.nodeType === matcher.nodeType &&
            normalizeExecStatus(n.data.status) === 'pending'
          ) {
            return patch(n.data)
          }
          return n
        }),
      )
    },
    [setNodes, executionOrderIds],
  )

  /**
   * Paint authoritative per-node statuses from journal events. `runStatus` is
   * the server's run status: nodes with a terminal event keep it; nodes
   * without one are only marked when the run status justifies it (see
   * reconcileNodeStatuses) — e.g. a node the journal says completed is never
   * shown cancelled just because the user pressed Cancel afterwards.
   */
  const applyStatusesFromEvents = React.useCallback(
    (events: Array<Record<string, unknown>>, runStatus: ExecBadgeStatus = 'unknown') => {
      const ids = nodesRef.current.map((n) => n.id)
      const byId = reconcileNodeStatuses(ids, events, executionOrderIds(), runStatus)
      // Node failure text lives in the event's error / error_message field.
      const errors = new Map<string, string>()
      for (const ev of events) {
        if (String(ev.type ?? ev.event ?? '') !== 'node_error' || typeof ev.node_id !== 'string') continue
        const msg = String(ev.error_message ?? ev.error ?? ev.message ?? '').trim()
        if (msg) errors.set(ev.node_id, msg)
      }
      setNodes((nds) =>
        nds.map((n) => {
          const st = byId.get(n.id)
          const err = st === 'failed' ? n.data.lastError || errors.get(n.id) : undefined
          if (!st || (st === n.data.status && err === n.data.lastError)) return n
          return { ...n, data: { ...n.data, status: st, lastError: err } }
        }),
      )
    },
    [setNodes, executionOrderIds],
  )

  /**
   * Fill the execution log from the linked run's journal (opening a graph whose
   * run already happened). Only replaces an empty log, a log this hydrate wrote
   * for the same run (live refresh), or the log right after a graph load.
   */
  const labelOfRef = React.useRef<Map<string, string>>(new Map())
  const hydrateLogFromJournal = (runId: string, events: Array<Record<string, unknown>>, badge: ExecBadgeStatus) => {
    const st = useAppStore.getState()
    if (st.isRunning) return
    const mayReplace = st.logs.length === 0 || hydratedRunRef.current === runId || allowHydrateRef.current
    if (!mayReplace || events.length === 0) return
    allowHydrateRef.current = false
    hydratedRunRef.current = runId
    const entries = journalToLogEntries(events, { labelFor: (id) => labelOfRef.current.get(id) })
    useAppStore.setState({
      logs: [
        { message: `Log of run ${shortRunId(runId)}`, level: 'info', ts: new Date().toISOString() },
        ...entries,
      ].slice(-500),
    })
    if (badge === 'running') {
      const latest = latestProgressByNode(events)
      for (const id of finishedNodeIds(events)) latest.delete(id)
      setNodeProgress(Object.fromEntries(latest))
    } else {
      setNodeProgress({})
    }
  }

  /** Record a terminal outcome for a specific run id (survives Editor remounts). */
  const finishOutcome = React.useCallback(
    (runId: string | null, outcome: KnownRunOutcome) => {
      rememberRunOutcome(runId, outcome)
      setRunOutcome(outcome)
      if (runId) setServerBadge({ runId, status: outcome })
    },
    [setRunOutcome],
  )

  /**
   * Fetch `/runs/{id}/status` (optionally waiting up to `waitTerminalMs` for a
   * terminal state) and `/runs/{id}` journal, then paint node statuses.
   * `guardCanvas` skips painting when the run belongs to a different graph
   * than the one on the canvas (mount hydrate of an arbitrary lastRunId).
   */
  const reconcileRunFromServer = React.useCallback(
    async (
      runId: string,
      opts: { waitTerminalMs?: number; guardCanvas?: boolean; isStale?: () => boolean; hydrateLog?: boolean } = {},
    ): Promise<ExecBadgeStatus> => {
      const stale = opts.isStale ?? (() => false)
      const deadline = Date.now() + (opts.waitTerminalMs ?? 0)
      let badge: ExecBadgeStatus = 'unknown'
      for (;;) {
        try {
          const st = await apiJson<{ status?: string }>(`/runs/${encodeURIComponent(runId)}/status`, {
            retries: 0,
          })
          badge = badgeFromServerStatus(st?.status)
        } catch (err) {
          badge = err instanceof ApiError && err.status === 404 ? 'missing' : 'unknown'
        }
        if (stale()) return badge
        if (isTerminalBadge(badge) || badge === 'missing' || Date.now() >= deadline) break
        await new Promise((r) => setTimeout(r, 1000))
        if (stale()) return badge
      }
      if (badge === 'missing') return badge
      try {
        const detail = await apiJson<{
          logs?: Array<Record<string, unknown>>
          meta?: { graph_name?: unknown }
        }>(`/runs/${encodeURIComponent(runId)}`)
        if (stale() || !Array.isArray(detail.logs)) return badge
        const events = detail.logs.filter((l) => l && typeof l === 'object') as Array<Record<string, unknown>>
        if (opts.guardCanvas) {
          // Only paint statuses when this run belongs to the graph on the canvas:
          // graph name must match (when recorded) and every node_id referenced
          // by the run must exist on the canvas.
          const runGraphName = typeof detail.meta?.graph_name === 'string' ? detail.meta.graph_name.trim() : ''
          const canvasGraphName = graphNameRef.current.trim()
          if (runGraphName && canvasGraphName && runGraphName !== canvasGraphName) return badge
          const canvasIds = new Set(nodesRef.current.map((n) => n.id))
          const runIds = events
            .map((e) => (typeof e.node_id === 'string' ? e.node_id : null))
            .filter((x): x is string => Boolean(x))
          if (runIds.length === 0 || runIds.some((id) => !canvasIds.has(id))) return badge
        }
        applyStatusesFromEvents(events, badge)
        if (opts.hydrateLog) hydrateLogFromJournal(runId, events, badge)
      } catch {
        /* best-effort: badge still reflects the server status */
      }
      return badge
    },
    // hydrateLogFromJournal only touches refs / the store.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [applyStatusesFromEvents],
  )

  const currentGraph = React.useCallback(
    () =>
      buildGraphFromCanvas(
        nodesRef.current.map((n) => ({ id: n.id, position: n.position, data: n.data })),
        edgesRef.current,
        seed,
        graphName,
        graphParametersRef.current,
      ),
    [seed, graphName],
  )

  React.useEffect(() => {
    setGetCanvasGraph(() => currentGraph)
    return () => setGetCanvasGraph(null)
  }, [currentGraph, setGetCanvasGraph])

  // ── Unsaved changes + undo/redo ────────────────────────────────────────
  // The document snapshot excludes run status / selection / handlers, so a
  // run painting node statuses never marks the graph dirty or adds history.
  const snapshot = React.useMemo(
    () => editorSnapshot(nodes, edges, graphName, seed),
    [nodes, edges, graphName, seed],
  )
  const snapshotSig = React.useMemo(() => snapshotSignature(snapshot), [snapshot])
  const snapshotSigRef = React.useRef(snapshotSig)
  snapshotSigRef.current = snapshotSig
  /** Signature of the last loaded / saved document (null until the first settle). */
  const [baselineSig, setBaselineSig] = React.useState<string | null>(null)
  const baselineSigRef = React.useRef<string | null>(null)
  baselineSigRef.current = baselineSig
  const historyRef = React.useRef<History<EditorSnapshot> | null>(null)
  const [historyFlags, setHistoryFlags] = React.useState({ canUndo: false, canRedo: false })
  const lastChangeRef = React.useRef<{ key: string | null; at: number }>({ key: null, at: 0 })
  /** Bumped on undo/redo/load so uncontrolled inspector inputs (JSON textareas) remount. */
  const [historyGen, setHistoryGen] = React.useState(0)
  /**
   * A load (reset) or undo/redo (restore) sets several pieces of state (nodes,
   * edges, name, seed in the store). Wait until the canvas matches the
   * expected signature (or a short timeout) before recording, so a partially
   * applied update never becomes its own history step.
   */
  const awaitRef = React.useRef<{ mode: 'reset' | 'restore'; sig: string | null; until: number } | null>({
    mode: 'reset',
    sig: null,
    until: 0,
  })
  /** Catalog re-decoration merged schema defaults — not a user edit. */
  const rebaseRef = React.useRef(false)
  const dragging = nodes.some((n) => n.dragging)

  const syncHistoryFlags = React.useCallback(() => {
    const h = historyRef.current
    const next = { canUndo: Boolean(h && h.past.length), canRedo: Boolean(h && h.future.length) }
    setHistoryFlags((prev) => (prev.canUndo === next.canUndo && prev.canRedo === next.canRedo ? prev : next))
  }, [])

  React.useEffect(() => {
    if (dragging) return // record the move once, on drag end
    const pending = awaitRef.current
    if (pending) {
      if (pending.sig && pending.sig !== snapshotSig && Date.now() < pending.until) return
      awaitRef.current = null
      rebaseRef.current = false
      if (pending.mode === 'reset') {
        historyRef.current = createHistory(snapshot)
        lastChangeRef.current = { key: null, at: 0 }
        setBaselineSig(snapshotSig)
      } else if (historyRef.current) {
        historyRef.current = { ...historyRef.current, present: snapshot }
      }
      syncHistoryFlags()
      return
    }
    const h = historyRef.current
    if (!h) {
      historyRef.current = createHistory(snapshot)
      syncHistoryFlags()
      return
    }
    const prevSig = snapshotSignature(h.present)
    if (rebaseRef.current) {
      rebaseRef.current = false
      const wasClean = baselineSigRef.current === prevSig
      historyRef.current = { ...h, present: snapshot }
      if (wasClean) setBaselineSig(snapshotSig)
      return
    }
    if (prevSig === snapshotSig) {
      historyRef.current = { ...h, present: snapshot }
      return
    }
    const key = changeKey(h.present, snapshot)
    const now = Date.now()
    const coalesce = key !== null && key === lastChangeRef.current.key && now - lastChangeRef.current.at < 1500
    historyRef.current = pushHistory(h, snapshot, { coalesce })
    lastChangeRef.current = { key, at: now }
    syncHistoryFlags()
  }, [snapshot, snapshotSig, dragging, syncHistoryFlags])

  /** Call right before a load replaces the canvas: the loaded graph becomes the clean baseline. */
  const beginBaseline = React.useCallback((expectedSig: string | null) => {
    awaitRef.current = { mode: 'reset', sig: expectedSig, until: Date.now() + 1500 }
    setHistoryGen((g) => g + 1)
  }, [])

  const dirty = baselineSig !== null && snapshotSig !== baselineSig
  const dirtyRef = React.useRef(dirty)
  dirtyRef.current = dirty

  const restoreSnapshot = React.useCallback(
    (snap: EditorSnapshot) => {
      awaitRef.current = { mode: 'restore', sig: snapshotSignature(snap), until: Date.now() + 1500 }
      const byId = new Map(nodesRef.current.map((n) => [n.id, n]))
      setNodes(
        snap.nodes.map((sn) => {
          const cur = byId.get(sn.id)
          return attachHandlers({
            ...(cur ?? {}),
            id: sn.id,
            type: 'graphyn',
            position: { ...sn.position },
            data: {
              ...(sn.data as unknown as GraphynNodeData),
              status: cur?.data.status ?? 'idle',
              lastError: cur?.data.lastError,
            },
          })
        }),
      )
      setEdges(
        snap.edges.map((e) => ({
          ...e,
          sourceHandle: e.sourceHandle ?? undefined,
          targetHandle: e.targetHandle ?? undefined,
          ...defaultEdgeOptions,
        })),
      )
      setGraphName(snap.graphName)
      setTemplateName(snap.graphName)
      setSeed(snap.seed)
      setInspectorId((id) => (id && snap.nodes.some((n) => n.id === id) ? id : null))
      setSelectedEdgeId((id) => (id && snap.edges.some((e) => e.id === id) ? id : null))
      setHistoryGen((g) => g + 1)
    },
    [attachHandlers, setNodes, setEdges, setSeed],
  )

  const undo = React.useCallback(() => {
    const h = historyRef.current
    if (!h || h.past.length === 0) return
    const next = undoHistory(h)
    historyRef.current = next
    lastChangeRef.current = { key: null, at: 0 }
    restoreSnapshot(next.present)
    syncHistoryFlags()
  }, [restoreSnapshot, syncHistoryFlags])

  const redo = React.useCallback(() => {
    const h = historyRef.current
    if (!h || h.future.length === 0) return
    const next = redoHistory(h)
    historyRef.current = next
    lastChangeRef.current = { key: null, at: 0 }
    restoreSnapshot(next.present)
    syncHistoryFlags()
  }, [restoreSnapshot, syncHistoryFlags])

  // Ctrl/Cmd+Z undo · Shift+Ctrl/Cmd+Z or Ctrl+Y redo. Never while typing in a
  // field (the browser's own text undo wins there) — use the toolbar buttons.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const action = historyShortcut(e)
      if (!action) return
      e.preventDefault()
      if (action === 'undo') undo()
      else redo()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undo, redo])

  const unsavedMessage = React.useCallback(
    () => `You have unsaved changes to “${graphNameRef.current || 'pipeline'}” in the Editor — leave and discard them?`,
    [],
  )

  // Browser reload / tab close.
  React.useEffect(() => {
    if (!dirty) return
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  // In-app navigation (sidebar, command palette, goView, workspace switch).
  React.useEffect(
    () => registerNavigationGuard(() => (dirtyRef.current ? unsavedMessage() : false)),
    [unsavedMessage],
  )

  /** Confirm before an in-Editor action replaces the canvas (open pipeline/env, import, external load). */
  const confirmDiscard = React.useCallback(
    (what: string) => {
      if (!dirtyRef.current) return true
      return window.confirm(
        `${what} will replace the graph on the canvas. Your unsaved changes to “${graphNameRef.current || 'pipeline'}” will be lost. Continue?`,
      )
    },
    [],
  )

  // ── Config validation (JSON-schema bounds / enum / pattern …) ───────────
  const configIssues = React.useMemo(() => validateNodeConfigs(nodes, schemaFieldLabel), [nodes])
  const issuesByNode = React.useMemo(() => {
    const m = new Map<string, Map<string, ConfigIssue[]>>()
    for (const i of configIssues) {
      const byField = m.get(i.nodeId) ?? new Map<string, ConfigIssue[]>()
      byField.set(i.field, [...(byField.get(i.field) ?? []), i])
      m.set(i.nodeId, byField)
    }
    return m
  }, [configIssues])
  // Parallel branches (Path A / Path B) + path-disambiguated labels. Keyed on
  // structure only, so dragging a node does not recompute it.
  const pathStructureKey = nodes
    .map((n) => {
      const c = n.data.config ?? {}
      return `${n.id}:${n.data.nodeType}:${n.data.label ?? ''}:${String(c.architecture ?? '')}:${String(c.epochs ?? '')}:${String(c.learning_rate ?? '')}`
    })
    .join('|') + '#' + edges.map((e) => `${e.source}>${e.target}`).join('|')
  const pathView = React.useMemo(
    () => canvasPathView(nodesRef.current, edgesRef.current),
    // pathStructureKey captures ids / labels / arch / epochs / lr / edges
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pathStructureKey],
  )
  /** Model builder ↔ Trainer learning-rate pairing (a set Trainer value wins — learningRate.ts). */
  const lrLinks = React.useMemo(
    () => learningRateLinks(nodesRef.current, edgesRef.current),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pathStructureKey],
  )
  labelOfRef.current = pathView.labelOf
  React.useEffect(() => {
    if (!isRunning && hydratedRunRef.current == null) setNodeProgress({})
  }, [isRunning])
  const displayNodes = React.useMemo(() => {
    const hasProgress = Object.keys(nodeProgress).length > 0
    if (issuesByNode.size === 0 && pathView.pathOf.size === 0 && pathView.titleOf.size === 0 && !hasProgress && lrLinks.size === 0) return nodes
    return nodes.map((n) => {
      const count = issuesByNode.get(n.id)?.size ?? 0
      const path = pathView.pathOf.get(n.id) ?? null
      const progress = nodeProgress[n.id] ?? null
      // A Model builder whose Trainer overrides the LR summarises the LR training uses.
      const lr = lrLinks.get(n.id)
      const effectiveLr = lr?.role === 'builder' && lr.source === 'trainer' ? lr.effective : null
      const titled = pathView.titleOf.get(n.id) ?? null
      if (!count && !path && !progress && effectiveLr == null && !titled) return n
      return {
        ...n,
        data: {
          ...n.data,
          ...(count ? { configIssues: count } : {}),
          pathBadge: path,
          displayLabel: pathView.labelOf.get(n.id),
          displayTitle: titled?.title,
          displaySubtitle: titled?.subtitle,
          progress,
          effectiveLr,
        },
      }
    })
  }, [nodes, issuesByNode, pathView, nodeProgress, lrLinks])

  /** True (and shows a banner listing node › field › rule) when config is invalid. */
  const blockOnInvalidConfig = (verb: 'run' | 'save') => {
    if (configIssues.length === 0) return false
    const nodeCount = new Set(configIssues.map((i) => i.nodeId)).size
    const title = `Cannot ${verb} — invalid config`
    const message = `${configIssues.length} invalid field${configIssues.length === 1 ? '' : 's'} on ${nodeCount} node${nodeCount === 1 ? '' : 's'}:\n${formatConfigIssues(configIssues)}`
    setActionError({ title, message, detail: formatConfigIssues(configIssues, 200) })
    setStatusMessage(title)
    pushToast(`${title}: ${configIssues.length} field${configIssues.length === 1 ? '' : 's'} out of range — see the banner`, 'error')
    const first = configIssues[0]
    if (first) {
      setInspectorId(first.nodeId)
      setSelectedEdgeId(null)
    }
    return true
  }

  const onConnect = React.useCallback(
    async (connection: Connection) => {
      if (!connection.source || !connection.target) return
      const sourceNode = nodesRef.current.find((n) => n.id === connection.source)
      const targetNode = nodesRef.current.find((n) => n.id === connection.target)
      const outPort = canonicalPort(connection.sourceHandle, 'output')
      const inPort = canonicalPort(connection.targetHandle, 'input')
      const sourceType = sourceNode?.data.outputs?.find((p) => p.name === outPort)?.data_type
      if (sourceType) {
        try {
          const compatible = await apiJson<Array<{ node_type?: string } | string>>(
            '/nodes/compatible',
            { query: { output_type: sourceType, direction: 'input' } },
          )
          const types = compatible.map((c) => (typeof c === 'string' ? c : c.node_type))
          if (targetNode && types.length > 0 && !types.includes(targetNode.data.nodeType)) {
            pushToast(
              `Port type may be incompatible: ${sourceType} → ${targetNode.data.nodeType}.${inPort}`,
              'info',
            )
          }
        } catch {
          /* soft check */
        }
      }
      setEdges((eds) => addEdge({ ...connection, id: `${connection.source}-${outPort}->${connection.target}-${inPort}`, ...defaultEdgeOptions }, eds))
    },
    [setEdges, pushToast],
  )

  const addNode = (entry: NodeCatalogEntry, position?: { x: number; y: number }) => {
    const id = `${entry.node_type}_${crypto.randomUUID().slice(0, 8)}`
    const ports = catalogPorts(entry)
    const node: Node<GraphynNodeData> = attachHandlers({
      id,
      type: 'graphyn',
      position: position ?? {
        x: nodes.reduce((m, n) => Math.max(m, n.position.x), -40) + 300,
        y: nodes.find((n) => n.id === inspectorId)?.position.y ?? 80,
      },
      data: {
        nodeType: entry.node_type,
        label: entry.label || humanNodeLabel(entry.node_type),
        category: entry.category,
        runtime: entry.runtime,
        config: isolateNodeWriteConfig(defaultsFromSchema(entry), id),
        schemaProps: entry.config_schema?.properties ?? {},
        inputs: ports.inputs,
        outputs: ports.outputs,
        status: 'idle',
        catalogDecorated: true,
      },
    })
    setNodes((nds) => [...nds, node])
    setInspectorId(id)
    setSelectedEdgeId(null)
  }

  const onCatalogDragStart = (event: React.DragEvent, entry: NodeCatalogEntry) => {
    event.dataTransfer.setData(CATALOG_DND_MIME, entry.node_type)
    event.dataTransfer.setData('text/plain', entry.node_type)
    event.dataTransfer.effectAllowed = 'copy'
  }

  const onCanvasDragOver = (event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
  }

  const onCanvasDrop = (event: React.DragEvent) => {
    event.preventDefault()
    const nodeType =
      event.dataTransfer.getData(CATALOG_DND_MIME) || event.dataTransfer.getData('text/plain')
    if (!nodeType) return
    const entry = catalog.find((c) => c.node_type === nodeType)
    if (!entry) {
      pushToast(`Unknown node type: ${nodeType}`, 'error')
      return
    }
    const position = screenToFlowPosition({ x: event.clientX, y: event.clientY })
    addNode(entry, position)
  }

  const pendingGraph = useAppStore((s) => s.pendingGraph)

  const loadGraph = (graph: GraphIR) => {
    // Clear the saved-pipeline picker — a freshly loaded graph (from an
    // artifact, proposal, run, or edge wizard) isn't necessarily the pipeline
    // it was last pointed at, and leaving the old selection in place shows a
    // pipeline name in the toolbar that doesn't match what's on the canvas.
    // openPipelineEnv() (the one caller that DOES load a real saved pipeline)
    // re-sets this right after calling loadGraph(), so that path is unaffected.
    setPipelinePick('')
    const loadedName = slugifyName(graph.metadata?.name || '')
    setGraphName(loadedName)
    if (/^[A-Za-z0-9_-]+$/.test(loadedName)) setTemplateName(loadedName)
    if (typeof graph.metadata?.seed === 'number') setSeed(graph.metadata.seed)
    // Preserve graph-level parameters (and the legacy parameters.ui shim's
    // sibling data) verbatim through the next save — the Builder doesn't
    // expose an editor for these yet.
    graphParametersRef.current = { ...(graph.parameters ?? {}) }
    const byType = new Map(catalog.map((c) => [c.node_type, c]))
    const ui = graph.ui?.positions
      ? graph.ui
      : (graph.parameters?.ui as { positions?: Record<string, { x: number; y: number }> } | undefined)
    const positions = ui?.positions ?? {}
    const nextNodes = graph.nodes.map((n, i) => {
      const entry = byType.get(n.node_type)
      const ports = catalogPorts(entry)
      const namedIn = graph.edges.filter((e) => e.dst_id === n.id).map((e) => canonicalPort(e.dst_port, 'input'))
      const namedOut = graph.edges.filter((e) => e.src_id === n.id).map((e) => canonicalPort(e.src_port, 'output'))
      for (const name of namedIn) {
        if (!ports.inputs.some((p) => p.name === name)) ports.inputs.push({ name })
      }
      const onError = onErrorFromIr(n.on_error)
      const routedPort = errorPortOf(onError)
      for (const name of namedOut) {
        // The routed error port is drawn from on_error, not as a catalog output.
        if (name === routedPort) continue
        if (!ports.outputs.some((p) => p.name === name)) ports.outputs.push({ name })
      }
      return attachHandlers({
        id: n.id,
        type: 'graphyn',
        position: positions[n.id] ?? { x: 60 + (i % 3) * 380, y: 40 + Math.floor(i / 3) * 300 },
        data: {
          nodeType: n.node_type,
          // Explicit saved label wins — only fall back to a catalog/humanized
          // default when the graph never set one (was previously reversed,
          // which silently discarded every custom label on the next save).
          label: n.label || entry?.label || humanNodeLabel(n.node_type),
          category: entry?.category,
          runtime: entry?.runtime,
          config: { ...defaultsFromSchema(entry), ...(n.config ?? {}) },
          schemaProps: entry?.config_schema?.properties ?? {},
          placement: (n.placement as NodePlacement | null | undefined) ?? null,
          onError,
          retry: retryFromIr(n.retry),
          // Opaque IR fields with no Builder editor yet — preserve verbatim.
          capabilityMetadata: n.capability_metadata ?? null,
          eventTrigger: n.event_trigger ?? null,
          inputs: ports.inputs,
          outputs: ports.outputs,
          status: 'idle',
          // false → re-decorated by the catalog effect below once it loads.
          catalogDecorated: Boolean(entry),
        },
      })
    })
    const nextEdges: Edge[] = graph.edges.map((e) => ({
      id: `${e.src_id}-${e.src_port}->${e.dst_id}-${e.dst_port}`,
      source: e.src_id,
      target: e.dst_id,
      sourceHandle: e.src_port,
      targetHandle: e.dst_port,
      data: { condition: e.condition ?? null },
      ...defaultEdgeOptions,
    }))
    const laidOut = layoutLeftToRight(
      uniquifyWriteConfigsAmongNodes(nextNodes),
      nextEdges,
      Object.keys(positions).length === 0,
    )
    const seedVal = typeof graph.metadata?.seed === 'number' ? graph.metadata.seed : seed
    // The loaded graph is the new clean baseline; history restarts here.
    beginBaseline(snapshotSignature(editorSnapshot(laidOut, nextEdges, loadedName, seedVal)))
    setNodes(laidOut)
    setEdges(nextEdges)
    setRunHadErrors(false)
    setNodeProgress({})
    // A hydrated log belongs to the previous canvas — let the linked run refill it.
    if (!useAppStore.getState().isRunning) allowHydrateRef.current = true
    setLoadGen((g) => g + 1)
  }

  const catalogOpenRef = React.useRef(catalogOpen)
  catalogOpenRef.current = catalogOpen
  /**
   * Fit with a readable minimum zoom (editorLayout.planFit): whole graph when it
   * fits at ≥0.6; else collapse the catalog first (the resulting resize re-fits);
   * else show the leftmost nodes at 0.6 and offer "Fit all".
   */
  const applyFit = React.useCallback(
    (allowCollapse: boolean) => {
      const rfNodes = getNodes()
      const el = canvasElRef.current
      if (rfNodes.length === 0) return
      const w = el?.clientWidth ?? 0
      const h = el?.clientHeight ?? 0
      if (!w || !h) {
        fitView(FIT_VIEW_OPTIONS)
        return
      }
      const bounds = getRectOfNodes(rfNodes)
      const plan = planFit({
        bounds,
        canvasW: w,
        canvasH: h,
        catalogOpen: allowCollapse && catalogOpenRef.current,
        padding: FIT_VIEW_OPTIONS.padding,
      })
      autoFitRef.current = true
      if (plan.collapseCatalog) {
        // Not stored as a preference; the canvas resize re-runs this fit.
        setCatalogOpen(false)
        lastFitBoxRef.current = { w: 0, h: 0 }
        return
      }
      lastFitBoxRef.current = { w, h }
      if (plan.mode === 'fit') {
        fitView(FIT_VIEW_OPTIONS)
        setPartialView(false)
      } else {
        setViewport(leftAnchoredViewport(bounds, h, plan.zoom))
        setPartialView(true)
      }
    },
    [fitView, getNodes, setViewport],
  )
  const fitAll = () => {
    autoFitRef.current = false
    setPartialView(false)
    fitView({ ...FIT_VIEW_OPTIONS, duration: 200 })
  }

  // Fit the freshly loaded graph.
  // Only on load / pipeline switch (loadGen) — never on ordinary edits. Waits
  // until React Flow has measured every loaded node, so the bounds are real
  // (a fit against unmeasured nodes is what used to cut nodes off).
  React.useEffect(() => {
    if (loadGen === 0) return
    let frames = 0
    let raf = 0
    const tryFit = () => {
      const want = nodesRef.current
      const have = getNodes()
      const wantIds = new Set(want.map((n) => n.id))
      const measured =
        want.length > 0 &&
        have.length === want.length &&
        have.every((n) => wantIds.has(n.id) && Boolean(n.width) && Boolean(n.height))
      if (measured || frames++ > 60) {
        if (want.length > 0) applyFit(true)
        return
      }
      raf = window.requestAnimationFrame(tryFit)
    }
    raf = window.requestAnimationFrame(tryFit)
    return () => window.cancelAnimationFrame(raf)
  }, [loadGen, applyFit, getNodes])

  // Canvas first on resize / size-class change: the catalog follows this size
  // class's stored choice, else opens only when the canvas keeps ≥700px.
  React.useEffect(() => {
    if (areaWidth <= 0) return
    const want = catalogShouldOpen({ areaWidth, stored: readStoredBool(catalogPrefKey(window.innerWidth)) })
    setCatalogOpen((prev) => (prev === want ? prev : want))
  }, [areaWidth, sizeClass])

  // Panels opening/closing (catalog, docked inspector) or a window resize change
  // the canvas: re-fit while the view is still the automatic fit — never on
  // ordinary edits, never after the user panned/zoomed.
  React.useEffect(() => {
    if (!autoFitRef.current || nodesRef.current.length === 0 || canvasBox.w === 0) return
    if (!isSignificantResize(lastFitBoxRef.current, canvasBox)) return
    const t = window.setTimeout(() => applyFit(false), 120)
    return () => window.clearTimeout(t)
  }, [canvasBox, applyFit])

  React.useEffect(() => {
    if (!pendingGraph) return
    const graph = useAppStore.getState().consumePendingGraph()
    if (!graph) return
    if (!confirmDiscard('Opening this graph')) {
      pushToast('Kept your unsaved Editor changes', 'info')
      return
    }
    loadGraph(graph)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingGraph, catalog])

  /**
   * Re-decorate nodes that landed before the catalog loaded, and fix ports when
   * the catalog now has real named ports (isolated stubs used to advertise only
   * a bare ``input``/``output`` fallback — template edges hid that; catalog add
   * did not).
   */
  React.useEffect(() => {
    if (catalog.length === 0) return
    const byType = new Map(catalog.map((c) => [c.node_type, c]))
    setNodes((nds) => {
      let changed = false
      const next = nds.map((n) => {
        const entry = byType.get(n.data.nodeType)
        if (!entry) return n
        const needsDecorate = !n.data.catalogDecorated || portsNeedResync(n.data, entry)
        if (!needsDecorate) return n
        const es = edgesRef.current
        const usedIn = new Set(
          es.filter((e) => e.target === n.id).map((e) => canonicalPort(e.targetHandle, 'input')),
        )
        const usedOut = new Set(
          es.filter((e) => e.source === n.id).map((e) => canonicalPort(e.sourceHandle, 'output')),
        )
        changed = true
        return { ...n, data: decorateNodeData(n.data, entry, usedIn, usedOut) }
      })
      // Schema defaults merged in by decoration are not a user edit.
      if (changed) rebaseRef.current = true
      return changed ? next : nds
    })
  }, [catalog, setNodes])

  // ── Catalog load state (inspector "step settings") ─────────────────────────
  // A failed / partial `/nodes` load used to leave every node grey with
  // "No config fields". Track it, auto-retry with backoff (2s, 5s, 10s, 30s…)
  // and on window focus; never while signed out (that opens Settings).
  const [catalogRefreshing, setCatalogRefreshing] = React.useState(false)
  const [catalogChecked, setCatalogChecked] = React.useState(() => useAppStore.getState().catalog.length > 0)
  const [catalogAttempt, setCatalogAttempt] = React.useState(0)
  const retryCatalog = React.useCallback(async () => {
    const fn = useAppStore.getState().refreshCatalog
    if (!fn) return
    setCatalogRefreshing(true)
    try {
      await fn()
    } finally {
      setCatalogRefreshing(false)
      setCatalogChecked(true)
    }
  }, [])
  const catalogTypes = React.useMemo(() => new Set(catalog.map((c) => c.node_type)), [catalog])
  const catalogState = catalogLoadState({
    count: catalog.length,
    error: bootError,
    refreshing: catalogRefreshing,
    checked: catalogChecked || Boolean(bootError),
  })
  const missingCatalogTypes =
    catalog.length > 0 ? new Set(nodes.map((n) => n.data.nodeType).filter((t) => !catalogTypes.has(t))).size : 0
  const signedOut = bootStatus === 401
  // App loads the catalog at boot; an empty, error-free catalog is only "empty" once a load finished.
  React.useEffect(() => {
    if (refreshCatalog && !catalogChecked && catalog.length === 0 && !bootError) void retryCatalog()
  }, [refreshCatalog, catalogChecked, catalog.length, bootError, retryCatalog])
  const catalogFailing =
    !signedOut &&
    (catalogState === 'failed' || (catalogState === 'ready' && missingCatalogTypes > 0 && catalogAttempt < 3))
  React.useEffect(() => {
    if (!catalogFailing) {
      if (catalogState === 'ready' && missingCatalogTypes === 0 && catalogAttempt > 0) setCatalogAttempt(0)
      return
    }
    if (catalogRefreshing) return
    const t = window.setTimeout(() => {
      setCatalogAttempt((a) => a + 1)
      void retryCatalog()
    }, catalogRetryDelay(catalogAttempt))
    return () => window.clearTimeout(t)
  }, [catalogFailing, catalogState, missingCatalogTypes, catalogAttempt, catalogRefreshing, retryCatalog])
  React.useEffect(() => {
    if (!catalogFailing) return
    const onFocus = () => {
      if (!useAppStore.getState().catalog.length || missingCatalogTypes > 0) void retryCatalog()
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [catalogFailing, missingCatalogTypes, retryCatalog])

  React.useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<GraphIR>).detail
      if (detail && confirmDiscard('Loading this graph')) loadGraph(detail)
    }
    window.addEventListener('graphyn:load-graph', handler)
    return () => window.removeEventListener('graphyn:load-graph', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog])

  const handleValidate = async () => {
    try {
      const graph = currentGraph()
      const result = await apiJson<{ valid: boolean; error?: string; node_count?: number }>(
        '/pipelines/validate',
        { method: 'POST', body: JSON.stringify(graph) },
      )
      if (result.valid) {
        setActionError(null)
        setStatusMessage(`Valid graph (${result.node_count ?? graph.nodes.length} nodes)`)
        pushToast('Validation passed', 'success')
        addLog('Validation passed', 'success')
      } else {
        const msg = result.error ?? 'Validation failed'
        setStatusMessage(msg)
        setActionError({ title: 'Validation failed', message: msg, detail: msg })
        addLog(msg, 'error')
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setStatusMessage(msg)
      setActionError({ title: 'Validation failed', message: msg, detail: msg })
    }
  }

  /**
   * Run reached a terminal state: a node that was mid-flight gets `inFlight`
   * (cancelled / failed); one that never started is "skipped" (not run) —
   * never left blank/idle or pending.
   */
  const settleUnfinishedNodes = React.useCallback(
    (inFlight: 'cancelled' | 'failed') => {
      setNodes((nds) =>
        nds.map((n) => {
          const st = normalizeExecStatus(n.data.status)
          if (st === 'running') return { ...n, data: { ...n.data, status: inFlight } }
          if (st === 'pending') return { ...n, data: { ...n.data, status: 'skipped' } }
          return n
        }),
      )
    },
    [setNodes],
  )
  const markUnfinishedCancelled = React.useCallback(() => settleUnfinishedNodes('cancelled'), [settleUnfinishedNodes])

  /**
   * After a cancel request / aborted stream: read the run's real outcome from
   * the server instead of assuming "cancelled". A cancel that 404s
   * (run_not_active) means the run already finished — possibly succeeded.
   */
  const settleAfterCancel = async (runId: string | null, opts: { cancelAccepted: boolean }) => {
    if (!runId) {
      // No run id was ever received — nothing on the server to ask.
      markUnfinishedCancelled()
      finishOutcome(null, 'cancelled')
      setStatusMessage('Run cancelled')
      addLog('Run cancelled before the server assigned a run id', 'warning')
      return
    }
    setStatusMessage('Cancelling — checking run status…')
    const badge = await reconcileRunFromServer(runId, {
      // Give the server a few seconds to stop the in-flight node.
      waitTerminalMs: opts.cancelAccepted ? 8000 : 2000,
      // A newer run started meanwhile owns the canvas.
      isStale: () => abortRef.current !== null,
    })
    if (abortRef.current !== null) return
    if (isTerminalBadge(badge)) {
      finishOutcome(runId, badge)
      const msg =
        badge === 'cancelled'
          ? 'Run cancelled'
          : badge === 'succeeded'
            ? 'Run had already finished (succeeded) before the cancel arrived'
            : 'Run had already finished (failed) before the cancel arrived'
      setStatusMessage(msg)
      addLog(msg, badge === 'succeeded' ? 'success' : 'warning')
      if (badge === 'failed') setRunHadErrors(true)
    } else {
      setServerBadge({ runId, status: badge === 'missing' ? 'missing' : badge === 'running' ? 'running' : 'unknown' })
      const msg =
        badge === 'running'
          ? 'Cancel requested — the server is still stopping the run'
          : 'Cancel requested — could not confirm the final run status'
      setStatusMessage(msg)
      addLog(msg, 'warning')
    }
  }

  const handleCancel = async () => {
    const runId = runIdRef.current
    let cancelAccepted = false
    if (runId) {
      try {
        await apiJson(`/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' })
        cancelAccepted = true
      } catch (err) {
        // run_not_active/run_not_found (404) means it already finished server-side —
        // settleAfterCancel reads the real final status. Anything else
        // (e.g. 503 run_active_on_another_worker) is surfaced so the user knows
        // the backend run may still be executing.
        const status = err instanceof ApiError ? err.status : null
        if (status !== 404) {
          pushToast(
            `Could not cancel run on the server: ${err instanceof Error ? err.message : String(err)}`,
            'error',
          )
        }
      }
    }
    abortRef.current?.abort()
    abortRef.current = null
    setIsRunning(false)
    setRunHadErrors(false)
    addLog(cancelAccepted ? 'Cancel requested by user' : 'Cancel requested — run may have already finished', 'warning')
    await settleAfterCancel(runId, { cancelAccepted })
  }

  // Abort any in-flight run stream on unmount so a stale stream's callbacks
  // (which write to the global Zustand store) can never fire after the
  // Builder tab has moved on to a different graph or run.
  // The server keeps executing after the stream closes (the producer thread is
  // detached), so clear the in-flight flag: on return the Execution badge
  // polls /runs/{id}/status for the real outcome instead of a stuck "running".
  React.useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort()
        abortRef.current = null
        useAppStore.getState().setIsRunning(false)
      }
    }
  }, [])

  const graphForRun = React.useCallback(() => {
    const base = currentGraph()
    const project = (activeProject || builderDataset?.project || '').trim()
    if (!project) return base
    return stampProjectOnGraph(base, project, builderDataset?.version)
  }, [currentGraph, activeProject, builderDataset])

  /**
   * POST /pipelines/run{,-async} body: the `{graph, …}` wrapper (accepted by
   * every API version) so the audit record gets `trigger: "ui"` and, when the
   * canvas was opened from a saved pipeline, the declared pipeline + env.
   */
  const runRequestBody = (graph: GraphIR, extras?: RunExtras) =>
    JSON.stringify({
      graph,
      trigger: 'ui',
      ...(pipelinePick ? { pipeline: pipelinePick, pipeline_env: pipelineEnv } : {}),
      // G3: webhook_trigger bodies + IR parameter overrides (only when given,
      // so older APIs that do not know these keys never see them).
      ...(extras?.inputs ? { inputs: extras.inputs } : {}),
      ...(extras?.parameters ? { parameters: extras.parameters } : {}),
    })

  /**
   * Run entry point: graphs with a webhook_trigger node or declared IR
   * parameters open the Run-with-inputs dialog; everything else stays one click.
   */
  const requestRun = (mode: 'stream' | 'async') => {
    if (blockOnInvalidConfig('run')) return
    const spec = runInputsSpec(currentGraph())
    if (needsRunDialog(spec)) {
      setRunDialog({ spec, mode })
      return
    }
    if (mode === 'async') void handleRunAsync()
    else void handleRun()
  }

  const handleRun = async (extras?: RunExtras) => {
    if (blockOnInvalidConfig('run')) return
    // Light pre-run path check (empty DatasetIngest / input paths)
    const missingPaths = findMissingInputPaths(nodesRef.current)
    if (missingPaths.length > 0) {
      const names = missingPaths.map((m) => m.label).join(', ')
      const msg = `Missing path on: ${names}. Set a dataset/input path before Run (or Validate).`
      setActionError({ title: 'Cannot run — missing path', message: msg, detail: msg })
      setStatusMessage(msg)
      // No run was started: don't touch runOutcome (it belongs to lastRunId).
      setRunHadErrors(true)
      pushToast(msg, 'error')
      addLog(msg, 'error')
      return
    }

    clearLogs()
    hydratedRunRef.current = null
    allowHydrateRef.current = false
    setNodeProgress({})
    setRunHadErrors(false)
    setActionError(null)
    setLogCollapsed(false)
    setIsRunning(true)
    setRunOutcome('running')
    setStatusMessage('Running…')
    setNodes((nds) => nds.map((n) => ({ ...n, data: { ...n.data, status: 'pending' } })))
    const controller = new AbortController()
    abortRef.current = controller
    runIdRef.current = null
    let streamCancelled = false
    let startError: { status: number; message: string } | null = null
    // A newer run (or Cancel / unmount) replaces abortRef.current; from then
    // on this invocation must not write run state, or it clobbers the new run.
    const isCurrent = () => abortRef.current === controller
    try {
      const graph = graphForRun()
      const res = await apiFetch('/pipelines/run', {
        method: 'POST',
        body: runRequestBody(graph, extras),
        signal: controller.signal,
        timeoutMs: 30 * 60 * 1000,
        headers: { 'Content-Type': 'application/json' },
      })
      if (!res.ok) {
        // e.g. 503 draining / concurrency limit, 422 invalid graph. Nothing ran.
        const apiErr = await parseError(res, '/pipelines/run')
        startError = {
          status: res.status,
          message: runStartErrorMessage(apiErr.body, apiErr.message || `HTTP ${res.status}`),
        }
        throw apiErr
      }
      const headerRunId = res.headers.get('X-Run-Id') || res.headers.get('x-run-id')
      if (headerRunId?.trim()) {
        setLastRunId(headerRunId.trim())
        runIdRef.current = headerRunId.trim()
      }
      if (!res.body) throw new Error('No response body')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let hadError = false
      let wasCancelled = false
      let lastErrorDetail = ''
      // Pipeline-level terminal events: backend sends type=done on success and
      // type=error on failure. A stream that ends without either was cut off.
      let sawDone = false
      let sawError = false
      let runId: string | null = headerRunId?.trim() || null
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        if (!isCurrent()) {
          void reader.cancel().catch(() => {})
          return
        }
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          try {
            const ev = JSON.parse(trimmed) as Record<string, unknown>
            if (typeof ev.run_id === 'string') {
              runId = ev.run_id
              runIdRef.current = ev.run_id
              setLastRunId(ev.run_id)
            }
            const t = String(ev.type ?? ev.event ?? '')
            const idx = Number(ev.node_index)
            const nodeId = typeof ev.node_id === 'string' ? ev.node_id : undefined
            if (t === 'pipeline_start') {
              setNodes((nds) => nds.map((n) => ({ ...n, data: { ...n.data, status: 'pending' } })))
            }
            if (t === 'node_start') {
              setNodeExecStatus({ index: idx, nodeId, nodeType: typeof ev.node_type === 'string' ? ev.node_type : undefined }, 'running')
            }
            if (t === 'node_end' || t === 'node_complete') {
              setNodeExecStatus({ index: idx, nodeId }, 'succeeded')
            }
            if (t === 'node_skip') {
              setNodeExecStatus({ index: idx, nodeId, nodeType: typeof ev.node_type === 'string' ? ev.node_type : undefined }, 'skipped')
            }
            if (t === 'node_progress') {
              const prog = parseProgress(ev)
              if (prog) {
                setNodeProgress((prev) => ({ ...prev, [prog.nodeId]: prog }))
                const backendLabel = typeof ev.node_label === 'string' ? compactNodeLabel(ev.node_label) : ''
                addLog(
                  formatProgressLine(prog, backendLabel || labelOfRef.current.get(prog.nodeId)),
                  'progress',
                  trimmed,
                )
              }
              continue
            }
            if (nodeId && (t === 'node_end' || t === 'node_complete' || t === 'node_error' || t === 'node_skip')) {
              setNodeProgress((prev) => {
                if (!(nodeId in prev)) return prev
                const next = { ...prev }
                delete next[nodeId]
                return next
              })
            }
            if (t === 'done' || t === 'pipeline_done') sawDone = true
            if (t === 'error' || t === 'pipeline_error') sawError = true
            if (t === 'node_error' || t === 'error') {
              hadError = true
              const errMsg = String(ev.error_message ?? ev.message ?? ev.error ?? 'Node failed')
              lastErrorDetail = errMsg
              setNodeExecStatus({ index: idx, nodeId }, 'failed', { lastError: errMsg })
            }
            if (t === 'cancelled' || t === 'pipeline_cancelled') {
              wasCancelled = true
              settleUnfinishedNodes('cancelled')
            }
            // Terminal `error` that repeats a node_error the stream already showed
            // (backend sets already_reported) — keep it for state, don't log it twice.
            if (t === 'error' && ev.already_reported === true) continue
            let formatted = formatExecutionLine(trimmed)
            if ((t === 'done' || t === 'pipeline_done') && hadError) {
              formatted = { text: 'Pipeline finished with errors', level: 'error', raw: trimmed }
            } else if ((t === 'done' || t === 'pipeline_done') && wasCancelled) {
              formatted = { text: 'Pipeline cancelled', level: 'warning', raw: trimmed }
            }
            addLog(
              relabelLine(formatted.text, ev, (id) => labelOfRef.current.get(id)),
              formatted.level.includes('error') ? 'error' : formatted.level,
              formatted.raw,
            )
          } catch {
            const formatted = formatExecutionLine(trimmed)
            if (/fail|error/i.test(formatted.text)) {
              hadError = true
              lastErrorDetail = lastErrorDetail || formatted.text
            }
            addLog(formatted.text, formatted.level, formatted.raw)
          }
        }
      }
      if (!isCurrent()) return
      let polledTerminal: 'completed' | 'failed' | 'cancelled' | null = null
      if (!sawDone && !sawError && !wasCancelled && !streamCancelled) {
        const msg = 'Stream disconnected — checking run status'
        setStatusMessage(msg)
        addLog(msg, 'warning')
        if (!runId) {
          hadError = true
          lastErrorDetail = 'Stream disconnected before the run id was known; check Observe → Runs.'
        } else {
          // Poll until the journal reports a terminal state (or this run is superseded).
          while (isCurrent()) {
            try {
              const st = await apiJson<{ status?: string }>(
                `/runs/${encodeURIComponent(runId)}/status`,
                { signal: controller.signal, retries: 0 },
              )
              const norm = normalizeRunStatus(st?.status)
              if (norm === 'completed' || norm === 'failed' || norm === 'cancelled') {
                polledTerminal = norm
                break
              }
            } catch (pollErr) {
              if (controller.signal.aborted) throw pollErr
              /* transient — keep polling */
            }
            await new Promise((r) => setTimeout(r, 2000))
          }
          if (!isCurrent()) return
          if (polledTerminal === 'failed') {
            hadError = true
            lastErrorDetail = lastErrorDetail || 'Run failed (reported by run status after stream disconnect).'
          } else if (polledTerminal === 'cancelled') {
            wasCancelled = true
          }
          addLog(`Run status after disconnect: ${polledTerminal}`, polledTerminal === 'completed' ? 'success' : 'warning')
          // Pull authoritative per-node statuses from the journal.
          try {
            const detail = await apiJson<{ logs?: Array<Record<string, unknown>> }>(
              `/runs/${encodeURIComponent(runId)}`,
            )
            if (isCurrent() && Array.isArray(detail.logs)) {
              applyStatusesFromEvents(
                detail.logs.filter((l) => l && typeof l === 'object') as Array<Record<string, unknown>>,
                polledTerminal === 'completed' ? 'succeeded' : polledTerminal ?? 'unknown',
              )
            }
          } catch {
            /* best-effort */
          }
        }
      }
      if (streamCancelled || wasCancelled) {
        settleUnfinishedNodes('cancelled')
        setRunHadErrors(false)
        finishOutcome(runId, 'cancelled')
        setStatusMessage('Run cancelled')
      } else if (hadError) {
        // Downstream nodes that never started read "skipped" (not run).
        settleUnfinishedNodes('failed')
        setRunHadErrors(true)
        finishOutcome(runId, 'failed')
        setStatusMessage('Run failed')
        setActionError({
          title: 'Run failed',
          message: lastErrorDetail ? lastErrorDetail.slice(0, 180) : 'One or more nodes failed during execution.',
          detail: lastErrorDetail || undefined,
        })
        pushToast(
          lastErrorDetail ? `Run failed: ${lastErrorDetail.slice(0, 120)}` : 'Run failed',
          'error',
        )
      } else {
        setRunHadErrors(false)
        finishOutcome(runId, 'succeeded')
        setStatusMessage('Run succeeded')
        pushToast('Run succeeded', 'success', {
          actionLabel: 'View outputs',
          onAction: () => {
            if (runId) openRun(runId, { panel: 'artifacts' })
          },
          ttlMs: 12000,
        })
      }
      if (runId) setLastRunId(runId)
    } catch (err) {
      // Superseded by Cancel / a newer run / unmount: that path owns the UI state.
      if (!isCurrent()) return
      if (err instanceof DOMException && err.name === 'AbortError') {
        streamCancelled = true
        setRunHadErrors(false)
        abortRef.current = null
        setIsRunning(false)
        // Don't assume cancelled: ask the server what actually happened.
        await settleAfterCancel(runIdRef.current, { cancelAccepted: false })
        return
      }
      if (err instanceof ApiError && err.status === 0 && controller.signal.aborted) return
      if (startError) {
        // The run was never created — say so plainly (toast + banner + log),
        // and put the nodes back to idle instead of painting them failed.
        const title = runStartErrorTitle(startError.status)
        const msg = `${startError.message} (HTTP ${startError.status})`
        addLog(`${title}: ${msg}`, 'error')
        setRunHadErrors(false)
        setRunOutcome('idle')
        setStatusMessage(title)
        setActionError({ title, message: msg, detail: msg })
        pushToast(`${title}: ${startError.message}`, 'error', { ttlMs: 15000 })
        setNodes((nds) => nds.map((n) => ({ ...n, data: { ...n.data, status: 'idle' } })))
        return
      }
      const knownRunId = runIdRef.current
      if (knownRunId) {
        // Stream broke mid-run (network error): the server may still be
        // running or may have finished — reconcile instead of guessing.
        const msg = err instanceof Error ? err.message : String(err)
        addLog(`Stream error: ${msg} — checking run status`, 'warning')
        const badge = await reconcileRunFromServer(knownRunId, { isStale: () => !isCurrent() })
        if (!isCurrent()) return
        if (isTerminalBadge(badge)) {
          finishOutcome(knownRunId, badge)
          setRunHadErrors(badge === 'failed')
          setStatusMessage(badge === 'succeeded' ? 'Run succeeded' : badge === 'failed' ? 'Run failed' : 'Run cancelled')
          return
        }
        if (badge === 'running') {
          setServerBadge({ runId: knownRunId, status: 'running' })
          setStatusMessage('Stream lost — run still executing on the server')
          pushToast('Lost the run stream — the run is still executing; open it in Runs to follow.', 'info')
          return
        }
      }
      const msg = err instanceof Error ? err.message : String(err)
      addLog(msg, 'error')
      setRunHadErrors(true)
      finishOutcome(knownRunId, 'failed')
      setStatusMessage('Run failed')
      setActionError({ title: 'Run failed', message: msg, detail: msg })
      pushToast(msg, 'error')
      settleUnfinishedNodes('failed')
    } finally {
      // Only the current run may clear shared run state — a finished/aborted
      // first run must not flip isRunning off under a second run.
      if (isCurrent()) {
        setIsRunning(false)
        abortRef.current = null
      }
    }
  }

  const handleRunAsync = async (extras?: RunExtras) => {
    if (blockOnInvalidConfig('run')) return
    setActionError(null)
    try {
      const graph = graphForRun()
      const res = await apiJson<{ run_id: string }>('/pipelines/run-async', {
        method: 'POST',
        body: runRequestBody(graph, extras),
      })
      setLastRunId(res.run_id)
      pushToast(`Async run started: ${res.run_id}`, 'success')
      openRun(res.run_id)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setActionError({ title: 'Could not start background run', message: msg, detail: msg })
    }
  }

  const exportIr = () => {
    const blob = new Blob([JSON.stringify(currentGraph(), null, 2)], {
      type: 'application/json',
    })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${graphName || 'pipeline'}.graph.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const importIr = () => {
    if (!confirmDiscard('Importing a graph')) return
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json,application/json'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      try {
        loadGraph(JSON.parse(await file.text()) as GraphIR)
        pushToast(`Loaded ${file.name}`, 'success')
      } catch (err) {
        pushToast(err instanceof Error ? err.message : 'Failed to load graph', 'error')
      }
    }
    input.click()
  }

  /** Keep canvas identity and Save slug the same — one document name. */
  const commitDocumentName = (raw: string) => {
    const n = slugifyName(raw)
    setGraphName(n)
    setTemplateName(n)
    return n
  }

  const saveTemplate = async () => {
    const name = slugifyName(graphName || templateName || 'pipeline')
    if (!/^[A-Za-z0-9_-]+$/.test(name)) {
      pushToast('Template name must match [A-Za-z0-9_-]+', 'error')
      return
    }
    if (blockOnInvalidConfig('save')) return
    try {
      const graph = currentGraph()
      const res = await apiJson<{ name: string; version?: string }>('/pipelines/templates', {
        method: 'POST',
        body: JSON.stringify({
          name,
          yaml: JSON.stringify(graph),
          description: 'Saved from Graphyn Editor',
        }),
      })
      commitDocumentName(name)
      pushToast(`Template saved: ${res.name}${res.version ? ` @ ${res.version}` : ''}`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const saveToProject = async (nameOverride?: string) => {
    const project = (activeProject || '').trim()
    if (!project) {
      pushToast('Open a workspace first', 'error')
      return
    }
    const name =
      slugifyName(nameOverride ?? (graphName || templateName || 'main')).replace(
        /[^A-Za-z0-9_-]/g,
        '_',
      ) || 'main'
    if (!/^[A-Za-z0-9_-]+$/.test(name)) {
      pushToast('Pipeline name must match [A-Za-z0-9_-]+', 'error')
      return
    }
    if (blockOnInvalidConfig('save')) return
    try {
      commitDocumentName(name)
      const base = buildGraphFromCanvas(
        nodesRef.current.map((n) => ({ id: n.id, position: n.position, data: n.data })),
        edgesRef.current,
        seed,
        name,
        graphParametersRef.current,
      )
      const graph = stampProjectOnGraph(base, project, builderDataset?.version)
      // Edits made while the PUT is in flight stay dirty.
      const savedSig = snapshotSignature(editorSnapshot(nodesRef.current, edgesRef.current, name, seed))
      await apiJson(`/projects/${encodeURIComponent(project)}/pipelines/${encodeURIComponent(name)}`, {
        method: 'PUT',
        body: JSON.stringify(graph),
      })
      setBaselineSig(savedSig)
      setPipelinePick(name)
      await refreshProjectPipelines()
      pushToast(`Saved to project ${project} · ${name}`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const saveAsProject = () => {
    const snap = useAppStore.getState().editorRunContext
    const base = slugifyName(graphName || templateName || 'pipeline')
    // A run snapshot never overwrites its pipeline: suggest a new slug.
    const suggested = snap?.snapshot ? `${base}-run-${shortRunId(snap.runId)}` : base
    const entered = window.prompt(snap?.snapshot ? 'Save this run snapshot as a new pipeline' : 'Save as pipeline slug', suggested)
    if (entered == null) return
    if (snap?.snapshot && slugifyName(entered) === base) {
      pushToast('Pick a new name — a run snapshot never overwrites the original pipeline', 'error')
      return
    }
    void saveToProject(entered).then(() => {
      if (snap?.snapshot) setEditorRunContext(null)
    })
  }


  const openPipelineEnv = async (
    pipelineName: string,
    env?: 'draft' | 'staging' | 'prod',
    opts: { confirm?: boolean } = {},
  ) => {
    const project = (activeProject || '').trim()
    if (!project || !pipelineName) return
    if (opts.confirm !== false && !confirmDiscard(`Opening ${pipelineName}${env && env !== 'draft' ? ` (${env})` : ''}`)) return
    try {
      const query = env && env !== 'draft' ? { env } : undefined
      const graph = await apiJson<GraphIR>(
        `/projects/${encodeURIComponent(project)}/pipelines/${encodeURIComponent(pipelineName)}`,
        query ? { query } : undefined,
      )
      loadGraph(graph)
      useAppStore.getState().setEditorRunContext(null)
      commitDocumentName(pipelineName)
      setPipelinePick(pipelineName)
      if (env) setPipelineEnv(env)
      pushToast(`Opened ${pipelineName}${env && env !== 'draft' ? ` (${env})` : ''} in Editor`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const refreshProjectPipelines = async () => {
    const project = (activeProject || '').trim()
    if (!project) return
    const pipes = await apiJson<typeof projectPipelineList>(
      `/projects/${encodeURIComponent(project)}/pipelines`,
    ).catch(() => null)
    if (Array.isArray(pipes)) setProjectPipelineList(pipes)
  }

  const promoteProjectPipeline = async (
    pipelineName: string,
    opts: { to_env: 'staging' | 'prod'; from_env?: string; version?: string; approve?: boolean },
  ) => {
    const project = (activeProject || '').trim()
    if (!project || !pipelineName) return
    try {
      const res = await apiJson<{ status?: string; version?: string }>(
        `/projects/${encodeURIComponent(project)}/pipelines/${encodeURIComponent(pipelineName)}/promote`,
        { method: 'POST', body: JSON.stringify(opts) },
      )
      pushToast(
        res.status === 'pending_approval'
          ? `Prod promotion pending approval (${res.version || opts.version || ''})`
          : `Promoted to ${opts.to_env}`,
        'success',
      )
      await refreshProjectPipelines()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  /** Create a versioned snapshot and optionally point staging (same as Home → Publish). */
  const publishProjectPipeline = async (pipelineName: string, setEnv?: 'staging' | 'prod') => {
    const project = (activeProject || '').trim()
    if (!project || !pipelineName) return
    try {
      const res = await apiJson<{ version?: string; status?: string }>(
        `/projects/${encodeURIComponent(project)}/pipelines/${encodeURIComponent(pipelineName)}/publish`,
        {
          method: 'POST',
          body: JSON.stringify({
            message: 'Published from Editor',
            set_env: setEnv,
          }),
        },
      )
      pushToast(
        setEnv === 'prod'
          ? `Published ${res.version} — prod pending approval`
          : `Published ${res.version}${setEnv ? ` → ${setEnv}` : ''}`,
        'success',
      )
      await refreshProjectPipelines()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const categories = React.useMemo(() => {
    const set = new Set<string>()
    for (const n of catalog) {
      if (n.category) set.add(n.category)
    }
    return [...set].sort((a, b) => a.localeCompare(b))
  }, [catalog])

  const filtered = catalog.filter((n) => {
    if (categoryFilter !== 'all' && (n.category || 'Other') !== categoryFilter) return false
    const q = filter.toLowerCase()
    if (!q) return true
    return (
      n.node_type.toLowerCase().includes(q) ||
      (n.label ?? '').toLowerCase().includes(q) ||
      (n.category ?? '').toLowerCase().includes(q) ||
      humanNodeLabel(n.node_type).toLowerCase().includes(q)
    )
  })

  // Pretty view: drop the pipeline-level `error` event that restates the
  // preceding node_error ("X · failed · msg" then "msg"). Raw view stays intact.
  const prettyLogs = showRawLogs
    ? skipConsecutiveByText(logs, (l) => l.raw || l.message)
    : dedupeErrorRows(
        skipConsecutiveByText(logs, (l) => l.message),
        (l) => l.message,
        (l) => l.level,
      )
  // Pretty: each node's node_progress events collapse into one live line
  // (latest values + sparkline). Raw keeps every event.
  const logRows = showRawLogs
    ? prettyLogs.map((row) => ({ kind: 'row' as const, row }))
    : collapseProgressRows(prettyLogs, (l) => l.raw)
  const hasErrorLogs = prettyLogs.some((l) => isErrorRow(l.level, l.message))
  const errorCount = hasErrorLogs
    ? Math.max(
        1,
        countErrorRows(
          showRawLogs
            ? dedupeErrorRows(skipConsecutiveByText(logs, (l) => l.message), (l) => l.message, (l) => l.level)
            : prettyLogs,
          (l) => l.message,
          (l) => l.level,
        ),
      )
    : 0

  React.useEffect(() => {
    const el = logBodyRef.current
    if (!el || logCollapsed) return
    if (stickToBottomRef.current) el.scrollTop = el.scrollHeight
  }, [logs, logCollapsed, showRawLogs, logHeight, toastCount])

  const focusLogErrors = () => {
    setLogCollapsed(false)
    requestAnimationFrame(() => {
      const first = logBodyRef.current?.querySelector('[data-log-error="1"]')
      if (first instanceof HTMLElement) {
        first.focus()
        first.scrollIntoView({ block: 'center' })
      } else {
        logBodyRef.current?.scrollIntoView({ block: 'nearest' })
      }
    })
  }

  const onLogResize = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    const startY = e.clientY
    const startH = logHeight
    const onMove = (ev: PointerEvent) => {
      const max = Math.round(window.innerHeight * 0.5)
      const next = Math.min(max, Math.max(80, startH + (startY - ev.clientY)))
      setLogHeight(next)
      setLogCollapsedByUser(false)
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }


  /**
   * Execution badge + node hydrate for `lastRunId` (bug: a cancelled run showed
   * SUCCEEDED after leaving and returning to the Editor, because the badge was
   * derived from component-local flags). Read the server's status on mount /
   * when lastRunId changes; poll while the server says it's still live.
   */
  React.useEffect(() => {
    if (!lastRunId || isRunning) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const runId = lastRunId
    const remembered = rememberedRunOutcome(runId)
    setServerBadge((prev) =>
      prev?.runId === runId && prev.status !== 'loading'
        ? prev
        : { runId, status: remembered ?? 'loading' },
    )
    const tick = async () => {
      const badge = await reconcileRunFromServer(runId, {
        guardCanvas: true,
        isStale: () => cancelled,
        hydrateLog: true,
      })
      if (cancelled) return
      if (isTerminalBadge(badge)) {
        // Also corrects the store's (un-keyed) runOutcome for the header chip.
        finishOutcome(runId, badge)
        return
      }
      if (badge === 'running') {
        setServerBadge({ runId, status: 'running' })
        timer = setTimeout(() => void tick(), 3000)
        return
      }
      // unknown / missing: keep a remembered terminal outcome when we have one.
      setServerBadge({ runId, status: remembered ?? badge })
    }
    void tick()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [lastRunId, isRunning, reconcileRunFromServer, finishOutcome, loadGen])

  // ── Run ↔ canvas drift (audit) ─────────────────────────────────────
  // Compares the canvas with the exact graph the linked run executed
  // (runs/<id>/graph.json). Snapshot mode = the canvas is that run's exact
  // graph opened read-only: Save becomes "Save as new".
  const editorRunContext = useAppStore((s) => s.editorRunContext)
  const setEditorRunContext = useAppStore((s) => s.setEditorRunContext)
  const snapshotMode = editorRunContext?.snapshot === true
  const driftRunId = snapshotMode ? editorRunContext!.runId : lastRunId
  const [driftRun, setDriftRun] = React.useState<{
    runId: string
    /** graph.json as recorded (run-scoped write paths). */
    rawGraph: GraphIR | null
    /** Same graph with run-scoped output folders removed (for loading). */
    logicalGraph: GraphIR | null
    title: string
    graphName: string
    savedChanged: { pipeline: string } | null
  } | null>(null)
  const [driftDismissedFor, setDriftDismissedFor] = React.useState<string | null>(null)
  React.useEffect(() => {
    if (!driftRunId || isRunning) return
    if (driftRun?.runId === driftRunId) return
    let cancelled = false
    const runId = driftRunId
    void (async () => {
      const [graph, detail] = await Promise.all([
        fetchRunGraph(runId, null).catch(() => null),
        apiJson<Record<string, unknown>>(`/runs/${encodeURIComponent(runId)}`, { retries: 0 }).catch(() => null),
      ])
      if (cancelled) return
      const meta = (detail?.meta && typeof detail.meta === 'object' ? detail.meta : {}) as Record<string, unknown>
      const drift = parsePipelineDrift(detail?.pipeline_drift)
      setDriftRun({
        runId,
        rawGraph: graph,
        logicalGraph: graph ? unscopeRunPaths(graph, runId) : null,
        title: detail ? runTitle({ ...detail, run_id: runId }) : '',
        graphName: String(meta.graph_name ?? graph?.metadata?.name ?? ''),
        savedChanged: drift?.changed ? { pipeline: drift.pipeline } : null,
      })
    })()
    return () => {
      cancelled = true
    }
    // driftRun is read only to skip a refetch of the same run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [driftRunId, isRunning])
  const driftApplies = Boolean(
    driftRun &&
      driftRun.runId === driftRunId &&
      driftRun.rawGraph &&
      (snapshotMode || (driftRun.graphName && slugifyName(driftRun.graphName) === slugifyName(graphName))),
  )
  const driftChanges = React.useMemo(() => {
    if (!driftApplies || !driftRun?.rawGraph) return null
    const byType = new Map(catalog.map((c) => [c.node_type, c]))
    const current = buildGraphFromCanvas(
      nodes.map((n) => ({ id: n.id, position: n.position, data: n.data })),
      edges,
      seed,
      graphName,
      graphParametersRef.current,
    )
    return diffGraphs(driftRun.rawGraph, current, {
      defaultsFor: (t) => defaultsFromSchema(byType.get(t)),
      compareSeed: true,
      runId: driftRun.runId,
    })
    // snapshotSig captures every document change (nodes / edges / name / seed).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [driftApplies, driftRun, snapshotSig, catalog])

  const openRunSnapshot = () => {
    const g = driftRun?.logicalGraph
    if (!g || !driftRun) return
    if (!confirmDiscard('Opening the run’s exact graph')) return
    loadGraph(g)
    setEditorRunContext({ runId: driftRun.runId, snapshot: true })
    pushToast('Opened the run’s exact graph as a read-only snapshot — Save keeps it as a new pipeline', 'info')
  }

  const execBadge: ExecBadgeStatus | null = isRunning
    ? 'running'
    : lastRunId
      ? serverBadge?.runId === lastRunId
        ? serverBadge.status
        : (rememberedRunOutcome(lastRunId) ?? 'loading')
      : null

  const secondaryActions = (
    <>
      <button
        type="button"
        disabled={nodes.length === 0 || isRunning}
        className="btn-quiet w-full justify-start"
        onClick={() => {
          requestRun('async')
          setMoreOpen(false)
        }}
      >
        <Play className="h-3.5 w-3.5" /> Run in background
      </button>
      {/* Seed lives only in the Graph settings panel (toolbar sliders button) — it used
          to also be editable here, which meant the same value could be changed from two places
          with no indication they were the same field. */}
      <ConfirmButton
        label="Clear canvas"
        confirmLabel="Confirm clear"
        danger
        className="w-full justify-start"
        onConfirm={() => {
          setNodes([])
          setEdges([])
          setGraphName('pipeline')
          setTemplateName('pipeline')
          setPipelinePick('')
          setRunHadErrors(false)
          setActionError(null)
          setInspectorId(null)
          setSelectedEdgeId(null)
          clearLogs()
          setMoreOpen(false)
        }}
      />
    </>
  )

  if (!activeProject) {
    return (
      <NeedProjectPrompt
        onOpenProjects={() => {
          openProjects()
        }}
      />
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-[11px] text-amber-950 md:hidden">
        Editor works best on a wide screen — collapse the catalog or rotate to landscape if the canvas feels cramped.
      </div>
      <div ref={areaRef} className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      <aside
        className={
          catalogOpen
            ? 'flex w-[min(17.5rem,32vw)] min-w-[12rem] shrink-0 min-h-0 flex-col overflow-hidden border-r border-ink-200/80 bg-white'
            : 'flex w-10 shrink-0 min-h-0 flex-col overflow-hidden border-r border-ink-200/80 bg-white'
        }
      >
        <div className="flex items-center justify-between gap-1 border-b border-ink-100 px-1.5 py-1">
          {catalogOpen ? (
            <div className="px-1">
              <div
                className="text-[12px] font-semibold text-ink-700"
                title={nodes.length === 0 ? 'Click or drag a node onto the canvas' : undefined}
              >
                Nodes
              </div>
              {nodes.length === 0 ? (
                <div className="text-[10px] text-ink-400">
                  Click or drag onto canvas
                </div>
              ) : null}
            </div>
          ) : null}
          <button
            type="button"
            className="btn-icon ml-auto"
            aria-label={catalogOpen ? 'Collapse node catalog' : 'Expand node catalog'}
            title={catalogOpen ? 'Collapse catalog' : 'Expand catalog'}
            onClick={toggleCatalog}
          >
            {catalogOpen ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        </div>
        {catalogOpen ? (
        <>
        <div className="sticky top-0 z-10 border-b border-ink-100/80 bg-white/95 p-2 backdrop-blur-sm">
          <input
            id="builder-catalog-search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search nodes…"
            aria-label="Search node catalog"
            className="w-full rounded-lg border border-ink-200 bg-ink-50 px-2.5 py-1.5 text-sm"
          />
          <select
            aria-label="Filter by category"
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="field-control mt-1.5"
          >
            <option value="all">All nodes ({catalog.length})</option>
            {categories.map((cat) => (
              <option key={cat} value={cat}>
                {prettyCategory(cat)} ({catalog.filter((n) => (n.category || 'Other') === cat).length})
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1 overflow-y-auto p-1.5">
          {catalog.length === 0 ? (
            <div className="px-1 py-2">
              <EmptyState
                title={
                  bootStatus === 401 || !getApiToken()
                    ? 'Sign in to load the catalog'
                    : bootError
                      ? 'API unavailable'
                      : 'No plugins installed'
                }
                description={
                  bootStatus === 401 || !getApiToken()
                    ? 'The API returned 401 or no token is set — paste your API token in Settings to load nodes.'
                    : bootError
                      ? `${bootError} Fix the connection, then retry loading the catalog.`
                      : 'No node packs are installed yet — install a plugin to populate the catalog.'
                }
                action={
                  bootStatus === 401 || !getApiToken() ? (
                    <button type="button" className="btn-primary" onClick={() => setSettingsOpen(true)}>
                      Open Settings
                    </button>
                  ) : bootError ? (
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => void refreshCatalog?.()}
                      >
                        Retry catalog
                      </button>
                      <button type="button" className="btn-secondary" onClick={() => setSettingsOpen(true)}>
                        Settings
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => goView('plugins')}
                    >
                      Open Plugins
                    </button>
                  )
                }
              />
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-2 py-6 text-sm text-ink-500">No nodes match.</div>
          ) : (
            <div className="space-y-3">
              {(categoryFilter === 'all'
                ? Array.from(
                    filtered.reduce((m, n) => {
                      const cat = n.category || 'Other'
                      const arr = m.get(cat) ?? []
                      arr.push(n)
                      m.set(cat, arr)
                      return m
                    }, new Map<string, typeof filtered>()),
                  )
                : ([[categoryFilter, filtered]] as Array<[string, typeof filtered]>)
              ).map(([cat, items]) => (
                <div key={cat}>
                  <div className="sticky top-0 z-[1] bg-white/95 px-2 py-1 text-[11px] font-medium text-ink-400 backdrop-blur">
                    {prettyCategory(cat)} · {items.length}
                  </div>
                  <div className="space-y-0.5">
                    {items.map((n) => (
                      <button
                        key={n.node_type}
                        type="button"
                        draggable
                        title={`${n.description || n.node_type} — click to add, or drag onto the canvas`}
                        onClick={() => addNode(n)}
                        onDragStart={(e) => onCatalogDragStart(e, n)}
                        className="flex w-full cursor-grab items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition hover:bg-ink-50 active:cursor-grabbing"
                      >
                        {(() => {
                          const look = categoryLook(n.category, n.node_type)
                          const Icon = look.Icon
                          return (
                            <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-white ${look.bg}`}>
                              <Icon className="h-3.5 w-3.5" />
                            </span>
                          )
                        })()}
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium text-ink-900">
                            {n.label || humanNodeLabel(n.node_type)}
                          </span>
                        </span>
                        {n.config_schema?.properties?.stub?.default === true && (
                          <span
                            className="shrink-0 rounded-md bg-amber-100 px-1.5 py-px text-[9px] font-medium text-amber-800"
                            title="Default config.stub=true returns a placeholder, not a real result"
                          >
                            stub
                          </span>
                        )}
                        {isIsolatedRuntime(n.runtime, n.node_type) && (
                          <span className="shrink-0 rounded-md bg-ink-100 px-1.5 py-px text-[9px] font-medium text-ink-500">
                            iso
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        </>
        ) : (
          <div className="flex flex-1 items-start justify-center pt-2">
            <button
              type="button"
              className="rotate-180 text-[11px] font-medium text-ink-400 [writing-mode:vertical-rl] hover:text-ink-700"
              onClick={toggleCatalog}
              title="Expand node catalog"
            >
              Nodes
            </button>
          </div>
        )}
      </aside>

      <div ref={mainColRef} className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {(() => {
          // Toolbar: one row — name (▾ switch pipeline) · version · chips · Run · Save · undo/redo · ⋯.
          // The workspace is already in the sidebar; publish/promote live under ⋯.
          const pipe = projectPipelineList.find((p) => p.name === pipelinePick)
          const hasStaging = Boolean(pipe?.environments?.staging)
          const hasProd = Boolean(pipe?.environments?.prod)
          const pendingProd = pipe?.environments?.pending_prod?.version
          // Only offer switches for versions that exist — never fake staging/prod toggles.
          const switchable: Array<'draft' | 'staging' | 'prod'> = ['draft']
          if (hasStaging) switchable.push('staging')
          if (hasProd) switchable.push('prod')
          const versionActions =
            pipelinePick && (!hasStaging || (hasStaging && !hasProd && !pendingProd) || pendingProd) ? (
              <div className="mb-2 flex flex-col items-stretch gap-0.5 border-b border-ink-100 pb-2">
                <div className="px-2 pb-0.5 text-[11px] font-medium text-ink-400" title="Saved versions of this pipeline (not model stages — those live on Models)">
                  Pipeline version
                </div>
                {!hasStaging ? (
                  <button
                    type="button"
                    className="btn-quiet w-full justify-start"
                    title="Snapshot the saved pipeline and make it the staging pipeline version"
                    onClick={() => {
                      setMoreOpen(false)
                      void publishProjectPipeline(pipelinePick, 'staging')
                    }}
                  >
                    Publish to staging
                  </button>
                ) : null}
                {hasStaging && !hasProd && !pendingProd ? (
                  <button
                    type="button"
                    className="btn-quiet w-full justify-start"
                    title="Ask for this staging pipeline version to become the production version"
                    onClick={() => {
                      setMoreOpen(false)
                      void promoteProjectPipeline(pipelinePick, { to_env: 'prod', from_env: 'staging', approve: false })
                    }}
                  >
                    Request prod version
                  </button>
                ) : null}
                {pendingProd ? (
                  <button
                    type="button"
                    className="btn-quiet w-full justify-start text-emerald-800"
                    title="Approve the pending production pipeline version"
                    onClick={() => {
                      setMoreOpen(false)
                      void promoteProjectPipeline(pipelinePick, { to_env: 'prod', version: pendingProd, approve: true })
                    }}
                  >
                    Approve prod version ({pendingProd})
                  </button>
                ) : null}
              </div>
            ) : null
          return (
        <div className="relative z-30 flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1.5 border-b border-ink-200/50 bg-white/85 px-3 py-1.5 backdrop-blur-md">
          {/* Document identity — Save / Run use this slug (synced with templateName); ▾ opens another saved pipeline. */}
          <PipelineSwitcher
            name={graphName}
            onNameChange={(v) => {
              setGraphName(v)
              setTemplateName(v)
            }}
            onNameCommit={() => commitDocumentName(graphName)}
            pipelines={projectPipelineList.map((p) => p.name)}
            current={pipelinePick}
            onOpen={(name) => {
              const target = projectPipelineList.find((p) => p.name === name)
              // Keep the current version only when the other pipeline has it.
              const env =
                pipelineEnv === 'draft' || target?.environments?.[pipelineEnv] ? pipelineEnv : 'draft'
              // openPipelineEnv sets the pick only once the load succeeds (or isn't cancelled).
              void openPipelineEnv(name, env)
            }}
          />
          {compactToolbar ? null : pipelinePick ? (
            switchable.length > 1 ? (
              <SegmentedTabs
                aria-label="Pipeline version: open the draft, staging, or prod copy of this pipeline"
                className="shrink-0 text-[11px] font-medium capitalize"
                value={pipelineEnv}
                options={switchable.map((env) => ({ id: env, label: env }))}
                onChange={(env) => {
                  if (env === pipelineEnv && !dirty) return
                  void openPipelineEnv(pipelinePick, env)
                }}
              />
            ) : (
              <span
                className="rounded-md bg-ink-100/80 px-1.5 py-0.5 text-[11px] font-medium text-ink-500"
                title="Pipeline version: working copy — Publish to staging (under ⋯) to create a version you can switch to"
              >
                Draft
              </span>
            )
          ) : (
            <span className="text-[11px] text-ink-400" title="Save to create this pipeline in the workspace">
              Not saved
            </span>
          )}
          {pendingProd ? (
            <span
              className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-800 ring-1 ring-emerald-200"
              title={`Prod version ${pendingProd} awaits approval — approve under ⋯`}
            >
              Prod pending
            </span>
          ) : null}
          {pendingProposalCount > 0 && (
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-900 hover:bg-amber-100"
              onClick={() => openProposals()}
              title="Pending graph proposals"
            >
              {pendingProposalCount} proposal{pendingProposalCount === 1 ? '' : 's'}
            </button>
          )}
          {builderDataset?.project && (
            <div
              className="inline-flex max-w-[16rem] items-center gap-0.5 rounded-full border border-ink-200 bg-ink-50 pl-2 text-[11px] text-ink-700"
              title={
                builderDataset.version
                  ? `Linked dataset ${builderDataset.project} / ${builderDataset.version}`
                  : `Linked dataset ${builderDataset.project}`
              }
            >
              <button
                type="button"
                className="min-w-0 truncate py-0.5 hover:underline"
                title="Open in Datasets"
                onClick={() =>
                  openData({
                    mode: 'outputs',
                    project: builderDataset.project,
                    version: builderDataset.version,
                  })
                }
              >
                Dataset: {builderDataset.project}
                {builderDataset.version ? ` / ${builderDataset.version}` : ''}
              </button>
              <button
                type="button"
                className="rounded-full p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
                aria-label="Clear dataset link"
                title="Clear dataset link"
                onClick={() => setBuilderDataset(null)}
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {configIssues.length > 0 ? (
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 text-[11px] font-semibold text-rose-900 ring-1 ring-rose-200 hover:bg-rose-100"
              title={formatConfigIssues(configIssues)}
              onClick={() => {
                setInspectorId(configIssues[0].nodeId)
                setSelectedEdgeId(null)
              }}
            >
              <AlertTriangle className="h-3 w-3" />
              {configIssues.length} invalid field{configIssues.length === 1 ? '' : 's'}
            </button>
          ) : null}
          {runHadErrors && !isRunning && (
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2.5 py-0.5 text-[11px] font-semibold text-rose-900 hover:bg-rose-200"
              onClick={focusLogErrors}
            >
              <AlertTriangle className="h-3 w-3" />
              Errors
            </button>
          )}
          {!isRunning ? (
            <button
              type="button"
              disabled={nodes.length === 0}
              onClick={() => requestRun('stream')}
              className="btn-primary"
            >
              <Play className="h-3.5 w-3.5" /> Run
            </button>
          ) : (
            <button type="button" onClick={() => void handleCancel()} className="btn-danger">
              <Square className="h-3.5 w-3.5" /> Cancel
            </button>
          )}
          <button
            type="button"
            className="btn-secondary"
            disabled={!activeProject}
            title={
              activeProject
                ? dirty
                  ? `Unsaved — save as ${slugifyName(graphName || 'pipeline')} in ${activeProject}`
                  : `Save as ${slugifyName(graphName || 'pipeline')} in ${activeProject}`
                : 'Open a workspace to save'
            }
            onClick={() => (snapshotMode ? saveAsProject() : void saveToProject())}
            aria-label={dirty ? 'Save (unsaved changes)' : 'Save'}
          >
            <Save className="h-3.5 w-3.5" /> Save
            {dirty ? (
              <span className="ml-0.5 h-2 w-2 rounded-full bg-amber-500" aria-hidden="true" title="Unsaved changes" />
            ) : null}
          </button>
          {compactToolbar ? null : (
          <div className="flex items-center gap-0.5">
            <button
              type="button"
              className="btn-icon"
              disabled={!historyFlags.canUndo}
              onClick={undo}
              aria-label="Undo"
              title="Undo (Ctrl/Cmd+Z)"
            >
              <Undo2 className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              className="btn-icon"
              disabled={!historyFlags.canRedo}
              onClick={redo}
              aria-label="Redo"
              title="Redo (Shift+Ctrl/Cmd+Z or Ctrl+Y)"
            >
              <Redo2 className="h-3.5 w-3.5" />
            </button>
          </div>
          )}
          {activeProject ? (
            // Visible entry for schedules / webhooks (also in ⋯); label hides on narrow toolbars.
            <button
              type="button"
              className={`${compactToolbar ? 'btn-icon' : 'btn-quiet'} ${triggersOpen ? 'bg-ink-100 text-ink-900' : ''}`}
              aria-pressed={triggersOpen}
              aria-label="Triggers"
              title="Triggers — schedules and webhooks that start this pipeline"
              onClick={() => {
                setTriggersOpen((v) => !v)
                setAgentOpen(false)
              }}
            >
              <Clock className="h-3.5 w-3.5" />
              {compactToolbar ? null : <span>Triggers</span>}
            </button>
          ) : null}
          <button
            type="button"
            className={`btn-icon ${graphSettingsOpen ? 'bg-ink-100 text-ink-900' : ''}`}
            aria-pressed={graphSettingsOpen}
            aria-label="Graph settings"
            title="Graph settings (seed, steps, linked run)"
            onClick={() => {
              setInspectorId(null)
              setSelectedEdgeId(null)
              setAgentOpen(false)
              setGraphSettingsOpen((v) => !v)
            }}
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
          </button>
          <div className="relative" ref={moreRef}>
            <button
              type="button"
              className="btn-quiet"
              onClick={() => setMoreOpen((o) => !o)}
              aria-expanded={moreOpen}
              aria-haspopup="menu"
              aria-label="More builder actions"
              title="More: validate, versions, triggers, agent, import/export…"
            >
              <MoreHorizontal className="h-3.5 w-3.5" />
            </button>
            {moreOpen && (
              <div
                className="absolute right-0 z-50 mt-1 w-64 rounded-2xl border border-ink-200 bg-white p-2 shadow-soft"
                onMouseDown={(e) => e.stopPropagation()}
                onPointerDown={(e) => e.stopPropagation()}
              >
                {compactToolbar ? (
                  <div className="mb-2 flex flex-col items-stretch gap-0.5 border-b border-ink-100 pb-2">
                    {pipelinePick && switchable.length > 1 ? (
                      <>
                        <div className="px-2 pb-0.5 text-[11px] font-medium text-ink-400">Open version</div>
                        {switchable.map((env) => (
                          <button
                            key={env}
                            type="button"
                            className={`btn-quiet w-full justify-start capitalize ${env === pipelineEnv ? 'bg-ink-100' : ''}`}
                            aria-pressed={env === pipelineEnv}
                            onClick={() => {
                              setMoreOpen(false)
                              if (env === pipelineEnv && !dirty) return
                              void openPipelineEnv(pipelinePick, env)
                            }}
                          >
                            {env}
                          </button>
                        ))}
                      </>
                    ) : (
                      <div className="px-2 pb-0.5 text-[11px] text-ink-400">
                        {pipelinePick ? 'Version: draft' : 'Not saved yet'}
                      </div>
                    )}
                    <div className="flex gap-1 px-1 pt-1">
                      <button type="button" className="btn-quiet flex-1" disabled={!historyFlags.canUndo} onClick={undo} title="Undo (Ctrl/Cmd+Z)">
                        <Undo2 className="h-3.5 w-3.5" /> Undo
                      </button>
                      <button type="button" className="btn-quiet flex-1" disabled={!historyFlags.canRedo} onClick={redo} title="Redo (Shift+Ctrl/Cmd+Z or Ctrl+Y)">
                        <Redo2 className="h-3.5 w-3.5" /> Redo
                      </button>
                    </div>
                  </div>
                ) : null}
                {versionActions}
                <div className="mb-2 flex flex-col items-stretch gap-0.5 border-b border-ink-100 pb-2">
                  <button
                    type="button"
                    className="btn-quiet w-full justify-start"
                    onClick={() => {
                      void handleValidate()
                      setMoreOpen(false)
                    }}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" /> Validate
                  </button>
                  <button
                    type="button"
                    className="btn-quiet w-full justify-start"
                    onClick={() => {
                      goView('templates')
                      setMoreOpen(false)
                    }}
                  >
                    Templates
                  </button>
                  {activeProject ? (
                    <button
                      type="button"
                      className={`btn-quiet w-full justify-start ${triggersOpen ? 'bg-accent-50' : ''}`}
                      onClick={() => {
                        setTriggersOpen((v) => !v)
                        setAgentOpen(false)
                        setMoreOpen(false)
                      }}
                    >
                      <Clock className="h-3.5 w-3.5" /> Triggers
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className={`btn-quiet w-full justify-start ${agentOpen ? 'bg-accent-50' : ''}`}
                    onClick={() => {
                      setAgentOpen((v) => !v)
                      setTriggersOpen(false)
                      setMoreOpen(false)
                    }}
                  >
                    <Sparkles className="h-3.5 w-3.5" /> Agent
                    {pendingProposalCount > 0 ? (
                      <span className="ml-auto rounded-full bg-amber-100 px-1.5 text-[10px] font-semibold text-amber-900">
                        {pendingProposalCount}
                      </span>
                    ) : null}
                  </button>
                </div>
                <div className="mb-2 flex flex-col items-stretch gap-0.5 border-b border-ink-100 pb-2">
                  {activeProject ? (
                    <button
                      type="button"
                      className="btn-quiet w-full justify-start"
                      onClick={() => {
                        setMoreOpen(false)
                        saveAsProject()
                      }}
                    >
                      <Save className="h-3.5 w-3.5" /> Save as…
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="btn-quiet w-full justify-start"
                    onClick={() => {
                      void saveTemplate()
                      setMoreOpen(false)
                    }}
                  >
                    Save as template
                  </button>
                </div>
                <div className="flex flex-col items-stretch gap-0.5">
                  <button type="button" className="btn-quiet w-full justify-start" onClick={() => { importIr(); setMoreOpen(false) }}>
                    <Upload className="h-3.5 w-3.5" /> Import graph
                  </button>
                  <button type="button" className="btn-quiet w-full justify-start" onClick={() => { exportIr(); setMoreOpen(false) }}>
                    <Download className="h-3.5 w-3.5" /> Export graph
                  </button>
                  {secondaryActions}
                </div>
              </div>
            )}
          </div>
          </div>
        </div>
          )
        })()}

        {driftRun && driftApplies && (snapshotMode || driftDismissedFor !== driftRun.runId) ? (
          <RunDriftBanner
            runId={driftRun.runId}
            runTitle={driftRun.title}
            changes={driftChanges}
            snapshot={snapshotMode}
            savedPipelineChanged={driftRun.savedChanged}
            labelFor={(id) => labelOfRef.current.get(id)}
            onOpenSnapshot={openRunSnapshot}
            onSaveAsNew={saveAsProject}
            onExitSnapshot={() => setEditorRunContext(null)}
            onOpenRun={() => openRun(driftRun.runId, { panel: 'lineage' })}
            onDismiss={() => setDriftDismissedFor(driftRun.runId)}
          />
        ) : null}
        {actionError && (
          <div className="border-b border-rose-100 px-3 py-2">
            {(() => {
              const title = actionError.title.toLowerCase()
              const isValidateOrPath =
                title.includes('validation') ||
                title.includes('missing path') ||
                title.includes('invalid config') ||
                title.startsWith('cannot run') ||
                title.startsWith('cannot save')
              // POST /pipelines/run rejected (503 busy, 422, …): nothing ran,
              // so there are no outputs to view — Retry only.
              const isStartRejected = title.startsWith('run not started')
              const isRunFailure =
                !isValidateOrPath &&
                (runHadErrors ||
                  title === 'run failed' ||
                  title.includes('background run') ||
                  /\brun\b/.test(title))
              const showRetry = isRunFailure
              const showViewOutputs =
                Boolean(lastRunId) &&
                !isValidateOrPath &&
                !isStartRejected &&
                (execBadge === 'succeeded' || runOutcome === 'succeeded' || isRunFailure)
              return (
                <ErrorBanner
                  title={actionError.title}
                  message={actionError.message}
                  detail={actionError.detail}
                  onDismiss={() => setActionError(null)}
                  onRetry={showRetry ? () => requestRun('stream') : undefined}
                  actions={
                    showViewOutputs ? (
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => openRun(lastRunId!, { panel: 'artifacts' })}
                      >
                        View outputs
                      </button>
                    ) : null
                  }
                />
              )
            })()}
          </div>
        )}
        <div className="relative flex min-h-0 min-w-0 flex-1 overflow-hidden bg-canvas">
          <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
          <div ref={canvasBoxRef} className="absolute inset-0">
          {nodes.length > 0 && edges.length === 0 && !connectTipDismissed && (
            <div className="absolute left-3 top-3 z-10 flex max-w-xs items-start gap-2 rounded-lg border border-ink-200/80 bg-white/95 px-2.5 py-1.5 text-type-meta text-ink-500 shadow-sm backdrop-blur">
              <p className="min-w-0 flex-1 leading-snug">
                Drag from a teal output handle to a dark input handle to connect. Hover a handle for
                port type.
              </p>
              <button
                type="button"
                className="shrink-0 rounded p-0.5 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
                aria-label="Dismiss connect tip"
                title="Dismiss"
                onClick={() => {
                  setConnectTipDismissed(true)
                  writeBoolPref(CONNECT_TIP_DISMISSED_KEY, true)
                }}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
          {backendMode !== 'distributed' &&
            nodes.some((n) => {
              const p = n.data.placement
              if (!p) return false
              return Boolean(
                (p.mode && p.mode !== 'auto') ||
                  (p.tags && p.tags.length > 0) ||
                  p.require_gpu ||
                  p.pool ||
                  p.worker,
              )
            }) && (
              <button
                type="button"
                className="pointer-events-auto absolute right-3 top-3 z-10 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-950 shadow-sm hover:bg-amber-100"
                title="Placement fields are present but Local mode ignores them"
                onClick={() => openModeExplainer()}
              >
                Placement ignored in Mode A
              </button>
            )}
          <ReactFlow
            nodes={displayNodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultEdgeOptions={defaultEdgeOptions}
            connectionLineStyle={{ stroke: '#ff6d5a', strokeWidth: 2.75 }}
            connectionLineType={ConnectionLineType.Bezier}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={(c) => void onConnect(c)}
            onDragOver={onCanvasDragOver}
            onDrop={onCanvasDrop}
            onNodeClick={(_, n) => {
              setInspectorId(n.id)
              setSelectedEdgeId(null)
            }}
            onEdgeClick={(_, e) => {
              setSelectedEdgeId(e.id)
              setInspectorId(null)
            }}
            onPaneClick={() => {
              setInspectorId(null)
              setSelectedEdgeId(null)
            }}
            onMoveStart={(event) => {
              // A user pan/zoom (event set) ends the automatic fit; programmatic moves have none.
              if (event) autoFitRef.current = false
            }}
            deleteKeyCode={['Backspace', 'Delete']}
            edgesFocusable
            elementsSelectable
            snapToGrid
            snapGrid={[20, 20]}
            panOnScroll
            minZoom={0.15}
          >
            <Background gap={22} size={1} color="#c5d0da" />
            <Controls fitViewOptions={FIT_VIEW_OPTIONS} />
            {partialView && nodes.length > 0 ? (
              <Panel position="top-left">
                <button
                  type="button"
                  className="rounded-md border border-ink-200 bg-white/95 px-2 py-0.5 text-[11px] font-medium text-ink-600 shadow-sm hover:text-ink-900"
                  title="Zoomed to a readable size — the graph continues to the right. Fit the whole graph (small)."
                  onClick={fitAll}
                >
                  Fit all
                </button>
              </Panel>
            ) : null}
            {/* Minimap: anchored bottom-right (zoom Controls are bottom-left, the
                Triggers dock bottom-left, tips/badges top), sized from the canvas,
                hidden below the width/height breakpoint; collapsible (persisted). */}
            {minimap.show && minimapOpen ? (
              <MiniMap
                pannable
                zoomable
                position="bottom-right"
                style={{ width: minimap.width, height: minimap.height, margin: MINIMAP_MARGIN }}
              />
            ) : null}
            {minimap.show ? (
              <Panel
                position="bottom-right"
                style={{
                  margin: MINIMAP_MARGIN,
                  marginBottom: minimapOpen ? minimap.height + MINIMAP_MARGIN + 6 : MINIMAP_MARGIN,
                }}
              >
                <button
                  type="button"
                  className="rounded-md border border-ink-200 bg-white/95 px-1.5 py-0.5 text-[10px] font-medium text-ink-500 shadow-sm hover:text-ink-800"
                  aria-pressed={minimapOpen}
                  title={minimapOpen ? 'Hide minimap' : 'Show minimap'}
                  onClick={() => {
                    setMinimapOpen((v) => {
                      writeBoolPref(MINIMAP_OPEN_KEY, !v)
                      return !v
                    })
                  }}
                >
                  {minimapOpen ? 'Hide map' : 'Map'}
                </button>
              </Panel>
            ) : null}
          </ReactFlow>
          {nodes.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
              <div className="pointer-events-auto max-w-sm rounded-3xl border border-ink-200/80 bg-white/90 px-8 py-7 text-center shadow-soft backdrop-blur">
                <div className="text-lg font-semibold text-ink-950">Start a pipeline</div>
                <p className="mt-2 text-sm leading-relaxed text-ink-500">
                  Click or drag a node from the left catalog onto the canvas, or open a template.
                </p>
                <div className="mt-3 flex flex-wrap justify-center gap-2">
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => goView('templates')}
                  >
                    Open Templates
                  </button>
                </div>
              </div>
            </div>
          )}
          {runDialog ? (
            <RunInputsDialog
              spec={runDialog.spec}
              mode={runDialog.mode}
              draftKey={graphName || 'pipeline'}
              onCancel={() => setRunDialog(null)}
              onRun={(extras) => {
                const mode = runDialog.mode
                setRunDialog(null)
                if (mode === 'async') void handleRunAsync(extras)
                else void handleRun(extras)
              }}
            />
          ) : null}
          {activeProject ? (
            <TriggersDock
              open={triggersOpen}
              onClose={() => setTriggersOpen(false)}
              project={activeProject}
              pipelines={projectPipelineList.map((p) => p.name)}
              defaultPipeline={pipelinePick || graphName}
              canvasPipeline={pipelinePick || graphName}
              canvasHasWebhookTrigger={nodes.some((n) => n.data.nodeType === 'webhook_trigger')}
            />
          ) : null}
          </div>
          </div>
          {inspectorVisible ? (
          <aside
            aria-label="Inspector"
            className={
              inspectorMode === 'docked'
                ? 'relative z-20 flex w-[clamp(15rem,28vw,21.25rem)] shrink-0 min-h-0 flex-col overflow-hidden border-l border-ink-200/70 bg-white/95 shadow-soft backdrop-blur'
                : inspectorMode === 'drawer'
                  ? 'absolute inset-y-0 right-0 z-30 flex w-[min(22rem,92%)] min-h-0 flex-col overflow-hidden border-l border-ink-200 bg-white shadow-2xl'
                  : 'absolute inset-x-0 bottom-0 z-30 flex max-h-[70%] min-h-[45%] flex-col overflow-hidden rounded-t-xl border-t border-ink-200 bg-white shadow-2xl'
            }
          >
            <AgentDrawer open={agentOpen} onClose={() => setAgentOpen(false)} />
            {!agentOpen && (() => {
              const node = inspectorId ? nodes.find((n) => n.id === inspectorId) : null
              const edge = selectedEdgeId ? edges.find((e) => e.id === selectedEdgeId) : null
              const mode: 'node' | 'edge' | 'graph' = node ? 'node' : edge ? 'edge' : 'graph'
              // "Trainer · Path C (MobileNet · lr 0.001)" — path-aware label + branch description.
              const nodePath = node ? pathView.pathOf.get(node.id) : undefined
              const nodeTitle = node
                ? `${pathView.labelOf.get(node.id) || node.data.label || node.data.nodeType}${
                    nodePath?.description ? ` (${nodePath.description})` : ''
                  }`
                : ''
              const title =
                mode === 'node'
                  ? nodeTitle
                  : mode === 'edge'
                    ? 'Connection'
                    : 'Graph settings'
              const subtitle =
                mode === 'node'
                  ? node!.data.nodeType
                  : mode === 'edge'
                    ? edge!.id
                    : graphName || 'pipeline'
              return (
                <>
                  <div className="flex items-start gap-1 border-b border-ink-100 py-1.5 pl-3 pr-1.5">
                    {inspectorMode === 'sheet' ? (
                      <span className="absolute left-1/2 top-1 h-1 w-10 -translate-x-1/2 rounded-full bg-ink-200" aria-hidden="true" />
                    ) : null}
                    <div className="min-w-0 flex-1 pt-0.5">
                      <div className="break-words text-sm font-semibold leading-snug text-ink-950">{title}</div>
                      <div className="truncate font-mono text-[10.5px] text-ink-400" title={subtitle}>
                        {subtitle}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn-icon mt-0.5 shrink-0"
                      aria-label="Close inspector"
                      title="Close (Esc)"
                      onClick={closeInspector}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>

                  {lastRunId || isRunning ? (
                    <div className="flex flex-wrap items-center gap-2 border-b border-ink-100 bg-ink-50/70 px-3 py-1.5 text-[11px] text-ink-600">
                      <span className="font-medium text-ink-500">{isRunning ? 'Current run' : 'Last run'}</span>
                      {execBadge === 'loading' ? (
                        <span className="text-ink-400" aria-live="polite">
                          checking…
                        </span>
                      ) : execBadge === 'missing' ? (
                        <span className="text-ink-500" title="GET /runs/{id}/status returned 404">
                          run not found
                        </span>
                      ) : execBadge ? (
                        <StatusBadge status={execBadge} />
                      ) : null}
                      {lastRunId ? (
                        <>
                          <span className="font-mono text-ink-500" title={lastRunId}>
                            {shortRunId(lastRunId)}
                          </span>
                          <button
                            type="button"
                            className="text-accent-700 hover:underline"
                            onClick={() => openRun(lastRunId)}
                          >
                            Open run
                          </button>
                        </>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="flex-1 space-y-2 overflow-y-auto px-3 py-2">
                    {mode === 'graph' && (
                      <>
                        {/* Graph name is edited once, in the toolbar above the canvas (it's the
                            title bar for the graph, same pattern as n8n's inline workflow name) —
                            this panel used to duplicate that exact field right below its own
                            subtitle line, which already shows the same name. Don't re-add an
                            editable "Graph name" input here; edit it in the toolbar instead. */}
                        <label
                          className="block text-[12px] text-ink-700"
                          title="Random seed recorded with every run, so a run can be reproduced exactly. Per-step retry and failure handling live in each step's Error handling section."
                        >
                          <span className="font-medium">Seed</span>
                          <span className="mt-0.5 block text-[10px] leading-snug text-ink-400">Makes runs reproducible.</span>
                          <input
                            type="number"
                            value={seed}
                            onChange={(e) => setSeed(Number(e.target.value) || 0)}
                            className="field-control mt-1 font-mono"
                          />
                        </label>
                        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-ink-100 pt-2 text-[12px]">
                          <dt className="text-ink-400">Steps</dt>
                          <dd className="text-right tabular-nums text-ink-800">{nodes.length}</dd>
                          <dt className="text-ink-400">Connections</dt>
                          <dd className="text-right tabular-nums text-ink-800">{edges.length}</dd>
                          {lastRunId ? (
                            <>
                              <dt className="text-ink-400">Linked run</dt>
                              <dd className="text-right">
                                <button type="button" className="font-mono text-accent-700 hover:underline" onClick={() => openRun(lastRunId)}>
                                  {shortRunId(lastRunId)}
                                </button>
                              </dd>
                            </>
                          ) : null}
                        </dl>
                        <p className="text-[11px] leading-snug text-ink-400">Select a step or connection on the canvas to edit it.</p>
                      </>
                    )}

                    {mode === 'edge' && edge && (
                      <>
                        <div className="space-y-1.5 text-[12px] text-ink-700">
                          <div className="grid grid-cols-[4.5rem_1fr] gap-1">
                            <span className="text-ink-400">From</span>
                            <span className="min-w-0 break-words" title={edge.source}>
                              {labelOfRef.current.get(edge.source) || nodes.find((n) => n.id === edge.source)?.data.label || edge.source}
                            </span>
                          </div>
                          <div className="grid grid-cols-[4.5rem_1fr] gap-1">
                            <span className="text-ink-400">Port</span>
                            <span className="font-mono text-[11px]">{canonicalPort(edge.sourceHandle, 'output')}</span>
                          </div>
                          <div className="grid grid-cols-[4.5rem_1fr] gap-1">
                            <span className="text-ink-400">To</span>
                            <span className="min-w-0 break-words" title={edge.target}>
                              {labelOfRef.current.get(edge.target) || nodes.find((n) => n.id === edge.target)?.data.label || edge.target}
                            </span>
                          </div>
                          <div className="grid grid-cols-[4.5rem_1fr] gap-1">
                            <span className="text-ink-400">Port</span>
                            <span className="font-mono text-[11px]">{canonicalPort(edge.targetHandle, 'input')}</span>
                          </div>
                        </div>
                        <EdgeConditionEditor
                          key={edge.id}
                          condition={(edge.data as { condition?: string | null } | undefined)?.condition ?? null}
                          sourcePort={canonicalPort(edge.sourceHandle, 'output')}
                          onChange={(next) =>
                            setEdges((eds) =>
                              eds.map((e) =>
                                e.id === edge.id ? { ...e, data: { ...(e.data ?? {}), condition: next } } : e,
                              ),
                            )
                          }
                        />
                        <button
                          type="button"
                          className="btn-danger mt-2"
                          onClick={() => {
                            setEdges((eds) => eds.filter((e) => e.id !== edge.id))
                            setSelectedEdgeId(null)
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" /> Remove connection
                        </button>
                      </>
                    )}

                    {mode === 'node' && node && (
                      <>
                        {/* Node status (the run status is already in the Execution row above).
                            A failed node shows the "Node failed" box instead of a second FAILED badge. */}
                        {(() => {
                          const st = normalizeExecStatus(node.data.status)
                          if (st === 'idle' || st === 'failed') return null
                          return (
                            <div className="mb-1 flex items-center gap-1.5 text-[11px]">
                              <span className="font-medium text-ink-500">Status</span>
                              <StatusBadge status={st === 'skipped' ? 'skipped · not run' : st} />
                            </div>
                          )
                        })()}
                        {normalizeExecStatus(node.data.status) === 'failed' && (
                          <div className="mb-2 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-2 text-type-secondary text-rose-900">
                            <div className="font-semibold text-rose-950">Node failed</div>
                            <p className="mt-1 line-clamp-4 whitespace-pre-wrap break-words">
                              {node.data.lastError || 'See the execution log for details.'}
                            </p>
                            <div className="mt-2 flex flex-wrap gap-2">
                              <button type="button" className="btn-secondary" onClick={focusLogErrors}>
                                Jump to log errors
                              </button>
                              {lastRunId ? (
                                <button type="button" className="btn-secondary" onClick={() => openRun(lastRunId)}>
                                  Open run
                                </button>
                              ) : null}
                              {!isRunning ? (
                                <button type="button" className="btn-primary" onClick={() => requestRun('stream')}>
                                  Retry run
                                </button>
                              ) : null}
                            </div>
                          </div>
                        )}
                        {backendMode === 'distributed' ? (
                        <div className="mb-3 rounded-lg border border-ink-200 bg-ink-50/70 p-2.5 space-y-2">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-[12px] font-semibold text-ink-700">
                              Placement
                            </div>
                            <button
                              type="button"
                              className="text-[11px] text-accent-700 hover:underline"
                              onClick={() => node.data.onChangePlacement?.(null)}
                            >
                              Reset auto
                            </button>
                          </div>
                          <p className="text-[10px] leading-snug text-ink-400">
                            Where this step runs in distributed mode.
                          </p>
                          {(() => {
                            const p = node.data.placement ?? { mode: 'auto' as const }
                            const setP = (patch: Partial<NodePlacement>) => {
                              const next: NodePlacement = { ...p, ...patch }
                              node.data.onChangePlacement?.(next)
                            }
                            return (
                              <>
                                <label className="block text-[12px] text-ink-700">
                                  <span className="font-medium">Mode</span>
                                  <select
                                    className="field-control mt-1"
                                    value={p.mode ?? 'auto'}
                                    onChange={(e) =>
                                      setP({
                                        mode: e.target.value as NodePlacement['mode'],
                                      })
                                    }
                                  >
                                    <option value="auto">auto</option>
                                    <option value="local">local</option>
                                    <option value="worker">worker</option>
                                    <option value="pool">pool</option>
                                  </select>
                                </label>
                                <label className="block text-[12px] text-ink-700">
                                  <span className="font-medium">Tags</span>
                                  <input
                                    className="field-control mt-1 font-mono"
                                    placeholder="gpu,edge (comma-separated)"
                                    value={(p.tags ?? []).join(',')}
                                    onChange={(e) =>
                                      setP({
                                        tags: e.target.value
                                          .split(',')
                                          .map((t) => t.trim())
                                          .filter(Boolean),
                                      })
                                    }
                                  />
                                </label>
                                <label className="flex items-center gap-2 text-[12px] text-ink-700">
                                  <input
                                    type="checkbox"
                                    checked={Boolean(p.require_gpu)}
                                    onChange={(e) => setP({ require_gpu: e.target.checked })}
                                  />
                                  <span className="font-medium">Require GPU</span>
                                </label>
                                <label className="block text-[12px] text-ink-700">
                                  <span className="font-medium">Pool</span>
                                  <input
                                    className="field-control mt-1 font-mono"
                                    placeholder="gpu-lab"
                                    value={p.pool ?? ''}
                                    onChange={(e) => setP({ pool: e.target.value.trim() || null })}
                                  />
                                </label>
                                <label className="block text-[12px] text-ink-700">
                                  <span className="font-medium">Worker</span>
                                  <input
                                    className="field-control mt-1 font-mono"
                                    placeholder="worker id"
                                    value={p.worker ?? ''}
                                    onChange={(e) => setP({ worker: e.target.value.trim() || null })}
                                  />
                                </label>
                              </>
                            )
                          })()}
                        </div>
                        ) : (
                        <p className="mb-2 text-[10px] leading-snug text-ink-400">
                          Placement is ignored in Local mode.{' '}
                          <button
                            type="button"
                            className="font-medium text-accent-800 hover:underline"
                            onClick={() => openModeExplainer()}
                          >
                            Local vs Distributed
                          </button>
                        </p>
                        )}

                        {/wait/i.test(node.data.nodeType) ? (
                          <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50/80 px-2.5 py-2 text-[11px] leading-snug text-amber-950">
                            Delay/wait step — for a human decision use an Approval gate step
                            (<span className="font-mono">hitl_approve</span>); pending gates show on the run’s Overview.
                          </div>
                        ) : null}

                        {(() => {
                          const props = (node.data.schemaProps ?? {}) as Record<string, Record<string, unknown>>
                          const allEntries = Object.entries(props) as [string, Record<string, unknown>][]
                          const settingsState = stepSettingsState({
                            catalog: catalogState,
                            hasEntry: catalogTypes.has(node.data.nodeType),
                            fieldCount: allEntries.length,
                          })
                          if (settingsState === 'loading') {
                            return (
                              <div className="text-[12px] text-ink-400" aria-live="polite">
                                Loading step settings…
                              </div>
                            )
                          }
                          if (settingsState === 'failed' || settingsState === 'missing') {
                            const failed = settingsState === 'failed'
                            return (
                              <div className="rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-2 text-[12px] text-rose-900" role="alert">
                                <div className="font-semibold">
                                  {failed
                                    ? signedOut
                                      ? 'Sign in to load step settings'
                                      : "Couldn't load step settings"
                                    : 'This step type is not in the catalog'}
                                </div>
                                <p className="mt-0.5 break-words text-[11px] leading-snug text-rose-800">
                                  {failed
                                    ? signedOut
                                      ? 'The API needs a token — open Settings to paste it.'
                                      : `${bootError || 'The node catalog failed to load.'} Retrying automatically.`
                                    : `“${node.data.nodeType}” isn't installed (or the API is still loading plugins).`}
                                </p>
                                <div className="mt-1.5 flex flex-wrap gap-2">
                                  {signedOut && failed ? (
                                    <button type="button" className="btn-secondary" onClick={() => setSettingsOpen(true)}>
                                      Open Settings
                                    </button>
                                  ) : (
                                    <button
                                      type="button"
                                      className="btn-secondary"
                                      disabled={catalogRefreshing}
                                      onClick={() => void retryCatalog()}
                                    >
                                      {catalogRefreshing ? 'Retrying…' : 'Retry'}
                                    </button>
                                  )}
                                  {!failed ? (
                                    <button type="button" className="btn-quiet" onClick={() => goView('plugins')}>
                                      Plugins
                                    </button>
                                  ) : null}
                                </div>
                              </div>
                            )
                          }
                          if (settingsState === 'empty') return <div className="text-sm text-ink-400">No config fields</div>
                          const cfg = node.data.config ?? {}
                          // ui.visible_if / depends_on: hide fields that don't apply to the current settings.
                          const entries = allEntries.filter(([, def]) => isFieldVisible(def, cfg, props))
                          const hiddenCount = allEntries.length - entries.length
                          const nodeIssues = issuesByNode.get(node.id)
                          const normalizeGroup = (key: string, def: Record<string, unknown>) => {
                            // Surface EarlyStopping patience with Epochs (Basic) even if the
                            // plugin schema still marks it Advanced.
                            if (key === 'patience') return 'Basic'
                            // Trainer LR next to its Model builder's: show which one wins.
                            if (key === 'learning_rate' && lrLinks.has(node.id)) return 'Basic'
                            const g = String(def.group ?? '').trim()
                            if (!g) return 'Basic'
                            const low = g.toLowerCase()
                            if (low === 'advanced' || low === 'adv') return 'Advanced'
                            if (low === 'basic') return 'Basic'
                            return g
                          }
                          const basic = entries.filter(([key, def]) => normalizeGroup(key, def) !== 'Advanced')
                          const advanced = entries.filter(([key, def]) => normalizeGroup(key, def) === 'Advanced')
                          const advancedInvalid = advanced.filter(([k]) => nodeIssues?.has(k)).length
                          const renderField = ([key, def]: [string, Record<string, unknown>]) => {
                            const fieldIssues = nodeIssues?.get(key) ?? []
                            const hintFull = schemaFieldHint(def)
                            const lrNote = key === 'learning_rate' ? learningRateNote(lrLinks.get(node.id)) : null
                            return (
                            <label key={key} className="block text-[12px] text-ink-700">
                              <span className="font-medium">{schemaFieldLabel(key, def)}</span>
                              {hintFull ? <FieldHelp text={hintFull} /> : null}
                              {lrNote ? (
                                <span className="mt-0.5 block rounded bg-sky-50 px-1.5 py-0.5 text-[11px] leading-snug text-sky-900 ring-1 ring-sky-100">
                                  {lrNote}
                                </span>
                              ) : null}
                              <ConfigFieldEditor
                                fieldKey={key}
                                def={def}
                                value={node.data.config?.[key] ?? def.default}
                                onChange={(v) => node.data.onChangeConfig?.(key, v)}
                                credentials={credentialsList}
                                invalid={fieldIssues.length > 0}
                              />
                              {fieldIssues.length > 0 ? (
                                <span className="mt-0.5 block text-[10px] font-medium leading-snug text-rose-700" role="alert">
                                  {fieldIssues.map((i) => i.message).join(' · ')}
                                </span>
                              ) : null}
                            </label>
                            )
                          }
                          return (
                            <div key={`${node.id}-${historyGen}`} className="space-y-2">
                              {String(node.data.nodeType || '') === 'model_builder' &&
                              String((node.data.config ?? {}).architecture || '') === 'custom' ? (
                                <div className="rounded-lg border border-ink-200 bg-ink-50/80 px-2.5 py-2">
                                  <div className="text-[11px] font-semibold text-ink-700">Load layers from preset</div>
                                  <p className="mt-0.5 text-[10px] leading-snug text-ink-400">
                                    Replace the layer list with a paper body (ds_cnn / mobilenet / simple_cnn)
                                    using this node&apos;s current filters / depth / MobileNet knobs.
                                  </p>
                                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                                    <select
                                      className="field-control max-w-[10rem] py-1 text-[11px]"
                                      value={loadPresetArch}
                                      onChange={(e) => setLoadPresetArch(e.target.value as ModelBuilderPreset)}
                                      onMouseDown={(e) => e.stopPropagation()}
                                    >
                                      <option value="ds_cnn">ds_cnn (Hello Edge)</option>
                                      <option value="mobilenet">mobilenet (MobileNetV2)</option>
                                      <option value="simple_cnn">simple_cnn</option>
                                    </select>
                                    <button
                                      type="button"
                                      className="rounded-md border border-ink-300 bg-white px-2 py-1 text-[11px] font-semibold text-ink-800 hover:bg-ink-50"
                                      onMouseDown={(e) => e.stopPropagation()}
                                      onClick={() => {
                                        const cfg = (node.data.config ?? {}) as Record<string, unknown>
                                        const next = loadPresetIntoConfig(loadPresetArch, cfg)
                                        setNodes((nds) =>
                                          nds.map((n) =>
                                            n.id === node.id
                                              ? { ...n, data: { ...n.data, config: { ...n.data.config, ...next } } }
                                              : n,
                                          ),
                                        )
                                        pushToast(
                                          `Loaded ${loadPresetArch} layers (${exportLayerSpecs(loadPresetArch, {
                                            filters: Number(cfg.filters ?? 64),
                                            numLayers: Number(cfg.num_layers ?? 4),
                                            expansionFactor: Number(cfg.expansion_factor ?? 6),
                                            stemStride: Number(cfg.stem_stride ?? 2),
                                          }).length} ops) → custom`,
                                          'success',
                                        )
                                      }}
                                    >
                                      Apply
                                    </button>
                                  </div>
                                </div>
                              ) : String(node.data.nodeType || '') === 'model_builder' ? (
                                <p className="text-[10px] leading-snug text-ink-400">
                                  Set Architecture to <span className="font-mono">custom</span> to edit layers
                                  (or Load from preset once custom is selected).
                                </p>
                              ) : null}
                              {basic.map(renderField)}
                              {advanced.length > 0 ? (
                                <div className="mt-2 rounded-lg border border-ink-200 bg-ink-50/60">
                                  <button
                                    type="button"
                                    className="flex w-full items-center justify-between px-2.5 py-1.5 text-left text-[12px] font-medium text-ink-600 hover:text-ink-900"
                                    onClick={() => setAdvancedOpen((v) => !v)}
                                    aria-expanded={advancedOpen}
                                  >
                                    <span>
                                      Advanced ({advanced.length})
                                      {advancedInvalid > 0 ? (
                                        <span className="ml-1 text-rose-700">· {advancedInvalid} invalid</span>
                                      ) : null}
                                    </span>
                                    {advancedOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                                  </button>
                                  {advancedOpen || advancedInvalid > 0 ? (
                                    <div className="space-y-2 border-t border-ink-200 px-2.5 py-2">
                                      {advanced.map(renderField)}
                                    </div>
                                  ) : null}
                                </div>
                              ) : null}
                              {hiddenCount > 0 ? (
                                <p className="text-[10px] leading-snug text-ink-400">
                                  {hiddenCount} field{hiddenCount === 1 ? '' : 's'} hidden — not applicable to the current settings.
                                </p>
                              ) : null}
                            </div>
                          )
                        })()}
                        <div className="mt-3">
                          <ErrorHandlingEditor
                            key={`err-${node.id}-${historyGen}`}
                            onError={node.data.onError}
                            retry={node.data.retry}
                            onChange={(next) => node.data.onChangeErrorPolicy?.(next)}
                          />
                        </div>
                      </>
                    )}
                  </div>
                </>
              )
            })()}
          </aside>
          ) : null}
        </div>

        <div data-toast-avoid className="relative z-20 border-t border-ink-800 bg-[#12181f] text-ink-100">
          <div
            className="absolute inset-x-0 -top-1 z-30 h-2 cursor-row-resize"
            onPointerDown={onLogResize}
            title="Drag to resize log"
          />
          <div className="flex min-w-0 items-center gap-2 px-3 py-1">
            {/* Collapsed = a thin bar with the latest line; auto-expands when a run starts. */}
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-[11px]"
              onClick={() => setLogCollapsedByUser(!logCollapsed)}
              aria-expanded={!logCollapsed}
              title={logCollapsed ? 'Show the execution log' : 'Hide the execution log'}
            >
              <span className="shrink-0 font-medium text-ink-300">Execution log</span>
              {logCollapsed ? (
                <span className={`min-w-0 truncate ${isRunning ? 'text-accent-300' : 'text-ink-500'}`}>
                  · {logBarSummary({ isRunning, logs: prettyLogs, runStatus: execBadge })}
                </span>
              ) : null}
            </button>
            {errorCount > 0 && (
              <button
                type="button"
                className="inline-flex items-center gap-1 rounded bg-rose-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-rose-200 hover:bg-rose-500/30"
                onClick={focusLogErrors}
              >
                {errorCount} {errorCount === 1 ? 'error' : 'errors'}
              </button>
            )}
            <div className="ml-auto flex shrink-0 items-center gap-2">
              {execBadge === 'failed' && !isRunning && lastRunId ? (
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded bg-rose-500/25 px-2 py-0.5 text-[11px] font-semibold text-rose-100 hover:bg-rose-500/40"
                  onClick={() => openRun(lastRunId)}
                >
                  <ExternalLink className="h-3 w-3" /> Open failed run
                </button>
              ) : lastRunId ? (
                <button
                  type="button"
                  className="inline-flex items-center gap-1 text-[11px] font-medium text-accent-300 hover:text-accent-200"
                  onClick={() => openRun(lastRunId, { panel: 'artifacts' })}
                >
                  <ExternalLink className="h-3 w-3" /> View outputs
                </button>
              ) : null}
              {!logCollapsed ? (
                <button
                  type="button"
                  className="text-[11px] font-medium text-ink-400 hover:text-ink-100"
                  onClick={() => setShowRawLogs((v) => !v)}
                >
                  {showRawLogs ? 'Pretty' : 'Raw'}
                </button>
              ) : null}
              <button
                type="button"
                className="text-ink-400 hover:text-ink-100"
                aria-label={logCollapsed ? 'Expand log' : 'Collapse log'}
                onClick={() => setLogCollapsedByUser(!logCollapsed)}
              >
                {logCollapsed ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>
          {!logCollapsed && (
            <div
              ref={logBodyRef}
              // The global toast stack is fixed bottom-right over this panel;
              // pad the scroll area while toasts are up so the last log lines
              // can still be scrolled clear of them (auto-stick re-scrolls).
              style={{
                height: logHeight,
                paddingBottom: toastCount > 0 ? Math.min(Math.round(logHeight * 0.6), 24 + toastCount * 64) : undefined,
              }}
              className="overflow-y-auto px-3 pb-2 font-mono text-[11px]"
              onScroll={(e) => {
                const el = e.currentTarget
                stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32
              }}
            >
              {errorCount > 0 && (
                <div className="sticky top-0 z-10 mb-1 rounded bg-rose-950/90 px-2 py-1 text-[11px] text-rose-100">
                  <button type="button" className="hover:underline" onClick={focusLogErrors}>
                    Jump to error
                  </button>
                </div>
              )}
              {prettyLogs.length === 0 ? (
                <div className="text-ink-500">
                  {lastRunId
                    ? 'No events for this graph yet — press Run, or open the linked run for its full log.'
                    : 'No events yet — press Run to see each step’s progress here.'}
                </div>
              ) : (
                logRows.map((entry, i) => {
                  const l = entry.row
                  if (entry.kind === 'progress') {
                    return (
                      <div key={`p-${entry.progress.nodeId}-${i}`} className="text-sky-200" title={`${entry.count} progress updates`}>
                        <ProgressLogLine
                          text={formatProgressLine(entry.progress, pathView.labelOf.get(entry.progress.nodeId))}
                          progress={entry.progress}
                          history={entry.history}
                          count={entry.count}
                        />
                      </div>
                    )
                  }
                  const isErr = isErrorRow(l.level, l.message)
                  return (
                    <div
                      key={`${l.ts}-${i}`}
                      data-log-error={isErr ? '1' : undefined}
                      tabIndex={isErr ? -1 : undefined}
                      className={
                        isErr
                          ? 'rounded bg-rose-500/10 px-1 text-rose-300 outline-none'
                          : l.level === 'success'
                            ? 'text-accent-300'
                            : 'text-ink-200'
                      }
                    >
                      {showRawLogs ? l.raw || l.message : l.message}
                    </div>
                  )
                })
              )}
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
  )
}

export default function BuilderView() {
  return (
    <ReactFlowProvider>
      <BuilderInner />
    </ReactFlowProvider>
  )
}
