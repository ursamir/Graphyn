import React from 'react'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  MarkerType,
  ConnectionLineType,
} from 'reactflow'
import 'reactflow/dist/style.css'
import {
  Play,
  CheckCircle2,
  Trash2,
  Download,
  Upload,
  Hash,
  Square,
  BookmarkPlus,
  MoreHorizontal,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  ExternalLink,
  X,
  Database,
  FolderKanban,
} from 'lucide-react'
import { apiFetch, apiJson, ApiError, getApiToken } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { stampProjectOnGraph } from '../../lib/projectStamp'
import { ConfirmButton, EmptyState, ErrorBanner, NeedProjectPrompt, StatusBadge } from '../../components/ui'
import { formatExecutionLine, formatValidationErrors, humanNodeLabel, isIsolatedRuntime, schemaFieldHint, schemaFieldLabel, shortRunId, skipConsecutiveByText, startCase } from '../../lib/format'
import {
  buildGraphFromCanvas,
  type NodePlacement,
  catalogPorts,
  type GraphIR,
  type NodeCatalogEntry,
  canonicalPort,
} from '../../types/graph'
import GraphynNode, { ConfigFieldEditor, categoryLook, normalizeExecStatus, type GraphynNodeData, type NodeExecStatus } from './GraphynNode'
import DeletableEdge from './DeletableEdge'

const nodeTypes = { graphyn: GraphynNode }
const edgeTypes = { default: DeletableEdge }

const EDGE_STYLE = { stroke: '#555555', strokeWidth: 2.75 }
const EDGE_MARKER = { type: MarkerType.ArrowClosed, width: 14, height: 14, color: '#555555' }
const defaultEdgeOptions = {
  type: 'default' as const,
  style: EDGE_STYLE,
  markerEnd: EDGE_MARKER,
}

const CATALOG_OPEN_KEY = 'graphyn.builder.catalogOpen'
const LOG_COLLAPSED_KEY = 'graphyn.builder.logCollapsed'

function readBoolPref(key: string, defaultValue: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    if (v === null) return defaultValue
    return v === '1' || v === 'true'
  } catch {
    return defaultValue
  }
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
  const COL = 300
  const ROW = 110
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

function defaultsFromSchema(entry?: NodeCatalogEntry): Record<string, unknown> {
  const props = entry?.config_schema?.properties ?? {}
  const cfg: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(props)) {
    if (v && typeof v === 'object' && 'default' in v) cfg[k] = v.default
  }
  const nodeType = entry?.node_type || 'node'
  for (const key of ['output_dir', 'output_path'] as const) {
    if (key in props) {
      const current = cfg[key]
      if (current === undefined || current === null || current === '') {
        cfg[key] = `workspace/artifacts/builder/${nodeType}`
      }
    }
  }
  return cfg
}

function BuilderInner() {
  const catalog = useAppStore((s) => s.catalog)
  const setView = useAppStore((s) => s.setView)
  const bootStatus = useAppStore((s) => s.bootStatus)
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

  const [nodes, setNodes, onNodesChange] = useNodesState<GraphynNodeData>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [filter, setFilter] = React.useState('')
  const [categoryFilter, setCategoryFilter] = React.useState('all')
  const [templateName, setTemplateName] = React.useState('')
  const [graphName, setGraphName] = React.useState('pipeline')
  const [moreOpen, setMoreOpen] = React.useState(false)
  const [showRawLogs, setShowRawLogs] = React.useState(false)
  const [logHeight, setLogHeight] = React.useState(148)
  const [catalogOpen, setCatalogOpen] = React.useState(() => readBoolPref(CATALOG_OPEN_KEY, true))
  const [logCollapsed, setLogCollapsed] = React.useState(() => readBoolPref(LOG_COLLAPSED_KEY, true))
  const [runHadErrors, setRunHadErrors] = React.useState(false)
  const [runCancelled, setRunCancelled] = React.useState(false)
  const [inspectorId, setInspectorId] = React.useState<string | null>(null)
  const [advancedOpen, setAdvancedOpen] = React.useState(false)

  React.useEffect(() => {
    setAdvancedOpen(false)
  }, [inspectorId])
  const [selectedEdgeId, setSelectedEdgeId] = React.useState<string | null>(null)
  const [actionError, setActionError] = React.useState<{ title: string; message: string; detail?: string } | null>(null)
  const moreRef = React.useRef<HTMLDivElement | null>(null)
  const abortRef = React.useRef<AbortController | null>(null)
  const nodesRef = React.useRef(nodes)
  const edgesRef = React.useRef(edges)
  const logBodyRef = React.useRef<HTMLDivElement | null>(null)
  const stickToBottomRef = React.useRef(true)
  nodesRef.current = nodes
  edgesRef.current = edges

  React.useEffect(() => {
    if (isRunning) setLogCollapsed(false)
  }, [isRunning])

  React.useEffect(() => {
    writeBoolPref(CATALOG_OPEN_KEY, catalogOpen)
  }, [catalogOpen])

  React.useEffect(() => {
    writeBoolPref(LOG_COLLAPSED_KEY, logCollapsed)
  }, [logCollapsed])

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
        onDelete: () => {
          setNodes((nds) => nds.filter((n) => n.id !== node.id))
          setEdges((eds) => eds.filter((e) => e.source !== node.id && e.target !== node.id))
          setInspectorId((id) => (id === node.id ? null : id))
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


  const setNodeExecStatus = React.useCallback(
    (
      matcher: { index?: number; nodeId?: string; nodeType?: string },
      status: NodeExecStatus,
      extra?: { lastError?: string },
    ) => {
      const norm = normalizeExecStatus(status)
      setNodes((nds) =>
        nds.map((n, i) => {
          const patch = (data: typeof n.data) => ({
            ...n,
            data: {
              ...data,
              status: norm,
              lastError: extra?.lastError !== undefined ? extra.lastError : (norm === 'failed' ? data.lastError : undefined),
            },
          })
          if (matcher.nodeId && n.id === matcher.nodeId) return patch(n.data)
          if (matcher.index != null && !Number.isNaN(matcher.index) && i === matcher.index) {
            return patch(n.data)
          }
          // Fallback: first idle/pending match by type only when index missing
          if (
            matcher.nodeType &&
            matcher.index == null &&
            !matcher.nodeId &&
            n.data.nodeType === matcher.nodeType &&
            normalizeExecStatus(n.data.status) === 'pending'
          ) {
            return patch(n.data)
          }
          return n
        }),
      )
    },
    [setNodes],
  )

  const applyStatusesFromEvents = React.useCallback(
    (events: Array<Record<string, unknown>>) => {
      const byIndex = new Map<number, NodeExecStatus>()
      const byId = new Map<string, NodeExecStatus>()
      for (const ev of events) {
        const t = String(ev.type ?? '')
        const idx = Number(ev.node_index)
        const nodeId = typeof ev.node_id === 'string' ? ev.node_id : undefined
        let st: NodeExecStatus | null = null
        if (t === 'node_start') st = 'running'
        else if (t === 'node_end' || t === 'node_complete') st = 'succeeded'
        else if (t === 'node_error') st = 'failed'
        else if (t === 'node_skip') st = 'skipped'
        if (!st) continue
        if (!Number.isNaN(idx)) byIndex.set(idx, st)
        if (nodeId) byId.set(nodeId, st)
      }
      setNodes((nds) =>
        nds.map((n, i) => {
          const st = byId.get(n.id) ?? byIndex.get(i)
          return st ? { ...n, data: { ...n.data, status: st } } : n
        }),
      )
    },
    [setNodes],
  )

  const currentGraph = React.useCallback(
    () =>
      buildGraphFromCanvas(
        nodesRef.current.map((n) => ({ id: n.id, position: n.position, data: n.data })),
        edgesRef.current,
        seed,
        graphName,
      ),
    [seed, graphName],
  )

  React.useEffect(() => {
    setGetCanvasGraph(() => currentGraph)
    return () => setGetCanvasGraph(null)
  }, [currentGraph, setGetCanvasGraph])

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

  const addNode = (entry: NodeCatalogEntry) => {
    const id = `${entry.node_type}_${crypto.randomUUID().slice(0, 8)}`
    const ports = catalogPorts(entry)
    const node: Node<GraphynNodeData> = attachHandlers({
      id,
      type: 'graphyn',
      position: {
        x: nodes.reduce((m, n) => Math.max(m, n.position.x), -40) + 300,
        y: nodes.find((n) => n.id === inspectorId)?.position.y ?? 80,
      },
      data: {
        nodeType: entry.node_type,
        label: entry.label || humanNodeLabel(entry.node_type),
        category: entry.category,
        runtime: entry.runtime,
        config: defaultsFromSchema(entry),
        schemaProps: entry.config_schema?.properties ?? {},
        inputs: ports.inputs,
        outputs: ports.outputs,
        status: 'idle',
      },
    })
    setNodes((nds) => [...nds, node])
  }

  const pendingGraph = useAppStore((s) => s.pendingGraph)

  const loadGraph = (graph: GraphIR) => {
    const loadedName = slugifyName(graph.metadata?.name || '')
    setGraphName(loadedName)
    if (/^[A-Za-z0-9_-]+$/.test(loadedName)) setTemplateName(loadedName)
    if (typeof graph.metadata?.seed === 'number') setSeed(graph.metadata.seed)
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
      for (const name of namedOut) {
        if (!ports.outputs.some((p) => p.name === name)) ports.outputs.push({ name })
      }
      return attachHandlers({
        id: n.id,
        type: 'graphyn',
        position: positions[n.id] ?? { x: 60 + (i % 3) * 380, y: 40 + Math.floor(i / 3) * 300 },
        data: {
          nodeType: n.node_type,
          label: entry?.label || n.label || humanNodeLabel(n.node_type),
          category: entry?.category,
          runtime: entry?.runtime,
          config: { ...defaultsFromSchema(entry), ...(n.config ?? {}) },
          schemaProps: entry?.config_schema?.properties ?? {},
          placement: (n.placement as NodePlacement | null | undefined) ?? null,
          inputs: ports.inputs,
          outputs: ports.outputs,
          status: 'idle',
        },
      })
    })
    const nextEdges: Edge[] = graph.edges.map((e) => ({
      id: `${e.src_id}-${e.src_port}->${e.dst_id}-${e.dst_port}`,
      source: e.src_id,
      target: e.dst_id,
      sourceHandle: e.src_port,
      targetHandle: e.dst_port,
      ...defaultEdgeOptions,
    }))
    setNodes(layoutLeftToRight(nextNodes, nextEdges, Object.keys(positions).length === 0))
    setEdges(nextEdges)
    setRunHadErrors(false)
  }

  React.useEffect(() => {
    if (!pendingGraph) return
    const graph = useAppStore.getState().consumePendingGraph()
    if (graph) loadGraph(graph)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingGraph, catalog])

  React.useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<GraphIR>).detail
      if (detail) loadGraph(detail)
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

  const handleCancel = () => {
    abortRef.current?.abort()
    abortRef.current = null
    setIsRunning(false)
    setRunCancelled(true)
    setRunHadErrors(false)
    setRunOutcome('cancelled')
    setStatusMessage('Run cancelled')
    addLog('Run cancelled by user', 'warning')
  }

  const graphForRun = React.useCallback(() => {
    const base = currentGraph()
    const project = (activeProject || builderDataset?.project || '').trim()
    if (!project) return base
    return stampProjectOnGraph(base, project, builderDataset?.version)
  }, [currentGraph, activeProject, builderDataset])

  const handleRun = async () => {
    // Light pre-run path check (empty DatasetIngest / input paths)
    const missingPaths = findMissingInputPaths(nodesRef.current)
    if (missingPaths.length > 0) {
      const names = missingPaths.map((m) => m.label).join(', ')
      const msg = `Missing path on: ${names}. Set a dataset/input path before Run (or Validate).`
      setActionError({ title: 'Cannot run — missing path', message: msg, detail: msg })
      setStatusMessage(msg)
      setRunOutcome('failed')
      setRunHadErrors(true)
      setRunCancelled(false)
      pushToast(msg, 'error')
      addLog(msg, 'error')
      return
    }

    clearLogs()
    setRunHadErrors(false)
    setRunCancelled(false)
    setActionError(null)
    setLogCollapsed(false)
    setIsRunning(true)
    setRunOutcome('running')
    setStatusMessage('Running…')
    setNodes((nds) => nds.map((n) => ({ ...n, data: { ...n.data, status: 'pending' } })))
    const controller = new AbortController()
    abortRef.current = controller
    let streamCancelled = false
    try {
      const graph = graphForRun()
      const res = await apiFetch('/pipelines/run', {
        method: 'POST',
        body: JSON.stringify(graph),
        signal: controller.signal,
        timeoutMs: 30 * 60 * 1000,
        headers: { 'Content-Type': 'application/json' },
      })
      if (!res.ok) {
        let detail = `Run failed: HTTP ${res.status}`
        try {
          const body = await res.clone().json()
          if (typeof body?.detail === 'string') detail = body.detail
          else if (typeof body?.error === 'string') detail = body.error
          else if (body?.detail != null) detail = JSON.stringify(body.detail)
        } catch {
          try {
            const t = await res.clone().text()
            if (t.trim()) detail = t.trim().slice(0, 500)
          } catch {
            /* keep status text */
          }
        }
        throw new ApiError(detail, res.status, '/pipelines/run')
      }
      if (!res.body) throw new Error('No response body')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let hadError = false
      let wasCancelled = false
      let lastErrorDetail = ''
      let runId: string | null = null
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
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
            if (t === 'node_error' || t === 'error') {
              hadError = true
              const errMsg = String(ev.error_message ?? ev.message ?? ev.error ?? 'Node failed')
              lastErrorDetail = errMsg
              setNodeExecStatus({ index: idx, nodeId }, 'failed', { lastError: errMsg })
            }
            if (t === 'cancelled' || t === 'pipeline_cancelled') {
              wasCancelled = true
              setNodes((nds) =>
                nds.map((n) =>
                  normalizeExecStatus(n.data.status) === 'running' || normalizeExecStatus(n.data.status) === 'pending'
                    ? { ...n, data: { ...n.data, status: 'cancelled' } }
                    : n,
                ),
              )
            }
            let formatted = formatExecutionLine(trimmed)
            if ((t === 'done' || t === 'pipeline_done') && hadError) {
              formatted = { text: 'Pipeline finished with errors', level: 'error', raw: trimmed }
            } else if ((t === 'done' || t === 'pipeline_done') && wasCancelled) {
              formatted = { text: 'Pipeline cancelled', level: 'warning', raw: trimmed }
            }
            addLog(
              formatted.text,
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
      if (streamCancelled || wasCancelled) {
        setRunCancelled(true)
        setRunHadErrors(false)
        setRunOutcome('cancelled')
        setStatusMessage('Run cancelled')
      } else if (hadError) {
        setRunHadErrors(true)
        setRunCancelled(false)
        setRunOutcome('failed')
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
        setRunCancelled(false)
        setRunOutcome('succeeded')
        setStatusMessage('Run succeeded')
        pushToast('Run succeeded', 'success')
      }
      if (runId) setLastRunId(runId)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        streamCancelled = true
        setRunCancelled(true)
        setRunHadErrors(false)
        setRunOutcome('cancelled')
        setStatusMessage('Run cancelled')
        setNodes((nds) =>
          nds.map((n) =>
            normalizeExecStatus(n.data.status) === 'running' || normalizeExecStatus(n.data.status) === 'pending'
              ? { ...n, data: { ...n.data, status: 'cancelled' } }
              : n,
          ),
        )
        return
      }
      if (err instanceof ApiError && err.status === 0) return
      const msg = err instanceof Error ? err.message : String(err)
      addLog(msg, 'error')
      setRunHadErrors(true)
      setRunCancelled(false)
      setRunOutcome('failed')
      setStatusMessage('Run failed')
      setActionError({ title: 'Run failed', message: msg, detail: msg })
      pushToast(msg, 'error')
      setNodes((nds) =>
        nds.map((n) =>
          normalizeExecStatus(n.data.status) === 'running' || normalizeExecStatus(n.data.status) === 'pending'
            ? { ...n, data: { ...n.data, status: 'failed' } }
            : n,
        ),
      )
    } finally {
      setIsRunning(false)
      abortRef.current = null
    }
  }

  const handleRunAsync = async () => {
    setActionError(null)
    try {
      const graph = graphForRun()
      const res = await apiJson<{ run_id: string }>('/pipelines/run-async', {
        method: 'POST',
        body: JSON.stringify(graph),
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

  const saveTemplate = async () => {
    const name = templateName.trim() || graphName
    if (!/^[A-Za-z0-9_-]+$/.test(name)) {
      pushToast('Template name must match [A-Za-z0-9_-]+', 'error')
      return
    }
    try {
      const graph = currentGraph()
      const res = await apiJson<{ name: string; version?: string }>('/pipelines/templates', {
        method: 'POST',
        body: JSON.stringify({
          name,
          yaml: JSON.stringify(graph),
          description: 'Saved from Graphyn Builder',
        }),
      })
      setTemplateName(name)
      pushToast(`Template saved: ${res.name}${res.version ? ` @ ${res.version}` : ''}`, 'success')
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

  const prettyLogs = skipConsecutiveByText(logs, (l) => (showRawLogs ? l.raw || l.message : l.message))
  const errorLogs = prettyLogs.filter((l) => l.level === 'error' || /fail|error/i.test(l.message))

  React.useEffect(() => {
    const el = logBodyRef.current
    if (!el || logCollapsed) return
    if (stickToBottomRef.current) el.scrollTop = el.scrollHeight
  }, [logs, logCollapsed, showRawLogs, logHeight])

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
      setLogCollapsed(false)
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }


  React.useEffect(() => {
    if (!lastRunId || isRunning) return
    let cancelled = false
    void (async () => {
      try {
        const detail = await apiJson<{ logs?: Array<Record<string, unknown>> }>(`/runs/${lastRunId}`)
        if (cancelled || !Array.isArray(detail.logs)) return
        const events = detail.logs.filter((l) => l && typeof l === 'object') as Array<Record<string, unknown>>
        if (events.some((e) => typeof e.type === 'string' && String(e.type).startsWith('node_'))) {
          applyStatusesFromEvents(events)
        }
      } catch {
        /* optional inspect hydrate */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [lastRunId, isRunning, applyStatusesFromEvents])

  const secondaryActions = (
    <>
      <ConfirmButton
        label="Clear canvas"
        confirmLabel="Confirm clear"
        danger
        onConfirm={() => {
          setNodes([])
          setEdges([])
          setGraphName('pipeline')
          setRunHadErrors(false)
          setActionError(null)
          setInspectorId(null)
          setSelectedEdgeId(null)
          clearLogs()
          setMoreOpen(false)
        }}
      />
      <button
        type="button"
        disabled={nodes.length === 0 || isRunning}
        className="btn-quiet"
        onClick={() => {
          void handleRunAsync()
          setMoreOpen(false)
        }}
      >
        Run in background
      </button>
      <label className="flex items-center gap-1.5 px-1 text-xs text-ink-500">
        <Hash className="h-3.5 w-3.5" />
        Seed
        <input
          type="number"
          value={seed}
          onChange={(e) => setSeed(Number(e.target.value) || 0)}
          className="field-control mt-0 w-16 py-0.5 font-mono text-xs"
          title="Graph seed"
        />
      </label>
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
    <div className="flex h-full min-h-0">
      <aside
        className={
          catalogOpen
            ? 'flex w-[17.5rem] shrink-0 flex-col border-r border-ink-200/80 bg-white'
            : 'flex w-10 shrink-0 flex-col border-r border-ink-200/80 bg-white'
        }
      >
        <div className="flex items-center justify-between gap-1 border-b border-ink-100 px-1.5 py-1">
          {catalogOpen ? (
            <div className="px-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">Catalog</div>
          ) : null}
          <button
            type="button"
            className="btn-icon ml-auto"
            aria-label={catalogOpen ? 'Collapse node catalog' : 'Expand node catalog'}
            title={catalogOpen ? 'Collapse catalog' : 'Expand catalog'}
            onClick={() => setCatalogOpen((v) => !v)}
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
            <option value="all">All categories ({catalog.length})</option>
            {categories.map((cat) => (
              <option key={cat} value={cat}>
                {startCase(cat)} ({catalog.filter((n) => (n.category || 'Other') === cat).length})
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1 overflow-y-auto p-1.5">
          {catalog.length === 0 ? (
            <div className="px-1 py-2">
              <EmptyState
                title={bootStatus === 401 || !getApiToken() ? 'Sign in to load nodes' : 'No plugins installed'}
                description={
                  bootStatus === 401 || !getApiToken()
                    ? 'Paste your API token in Settings to load the node catalog.'
                    : 'Install a plugin to populate the catalog, then add nodes here — or browse Data / Projects while you wait.'
                }
                action={
                  bootStatus === 401 || !getApiToken() ? (
                    <button type="button" className="btn-primary" onClick={() => setSettingsOpen(true)}>
                      Open Settings
                    </button>
                  ) : (
                    <div className="flex flex-wrap justify-center gap-2">
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => {
                          setView('plugins')
                          window.history.replaceState(null, '', '#/plugins')
                        }}
                      >
                        Open Plugins
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => openData({ mode: 'inputs' })}
                      >
                        <Database className="h-3.5 w-3.5" /> Open Data
                      </button>
                      <button type="button" className="btn-secondary" onClick={() => openProjects()}>
                        <FolderKanban className="h-3.5 w-3.5" /> Open Projects
                      </button>
                    </div>
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
                    {startCase(cat)} · {items.length}
                  </div>
                  <div className="space-y-0.5">
                    {items.map((n) => (
                      <button
                        key={n.node_type}
                        type="button"
                        title={n.description || n.node_type}
                        onClick={() => addNode(n)}
                        className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition hover:bg-ink-50"
                      >
                        {(() => {
                          const look = categoryLook(n.category)
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
            <span className="write-vertical-right rotate-180 text-[10px] font-semibold uppercase tracking-wide text-ink-400 [writing-mode:vertical-rl]">
              Nodes
            </span>
          </div>
        )}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="relative z-30 flex flex-wrap items-center gap-2 border-b border-ink-200/50 bg-white/80 px-3 py-1.5 backdrop-blur-md">
          <span
            className="inline-flex items-center gap-1 rounded-full border border-accent-200 bg-accent-50 px-2.5 py-0.5 text-[11px] font-semibold text-accent-950"
            title="Editor scoped to open workspace"
          >
            Editor · {activeProject}
          </span>
          {pendingProposalCount > 0 && (
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-[11px] font-semibold text-amber-900 hover:bg-amber-100"
              onClick={() => openProposals()}
              title="Pending graph proposals"
            >
              {pendingProposalCount} proposal{pendingProposalCount === 1 ? '' : 's'}
            </button>
          )}
          {builderDataset?.project && (
            <div
              className="inline-flex items-center gap-1.5 rounded-full border border-accent-200 bg-accent-50 px-2.5 py-0.5 text-[11px] font-semibold text-accent-950"
              title={
                builderDataset.version
                  ? `${builderDataset.project} / ${builderDataset.version}`
                  : builderDataset.project
              }
            >
              <span>
                Dataset: {builderDataset.project}
                {builderDataset.version ? ` / ${builderDataset.version}` : ''}
              </span>
              <button
                type="button"
                className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold text-accent-800 hover:bg-accent-100"
                onClick={() =>
                  openData({
                    mode: 'outputs',
                    project: builderDataset.project,
                    version: builderDataset.version,
                  })
                }
              >
                Open Data
              </button>
              <button
                type="button"
                className="rounded-full p-0.5 text-accent-700 hover:bg-accent-100"
                aria-label="Clear dataset link"
                onClick={() => setBuilderDataset(null)}
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          )}
          {!isRunning ? (
            <button
              type="button"
              disabled={nodes.length === 0}
              onClick={() => void handleRun()}
              className="btn-primary"
            >
              <Play className="h-3.5 w-3.5" /> Run
            </button>
          ) : (
            <button type="button" onClick={handleCancel} className="btn-danger">
              <Square className="h-3.5 w-3.5" /> Cancel
            </button>
          )}
          <button type="button" onClick={() => void handleValidate()} className="btn-secondary">
            <CheckCircle2 className="h-3.5 w-3.5" /> Validate
          </button>
          <input
            value={graphName}
            onChange={(e) => setGraphName(e.target.value.replace(/[^A-Za-z0-9_-]/g, '-'))}
            onBlur={() => setGraphName((n) => slugifyName(n))}
            placeholder="graph-name"
            className="w-40 rounded-lg border border-ink-200/80 bg-ink-50/60 px-2.5 py-1.5 text-sm font-medium text-ink-900 outline-none focus:border-accent-400 focus:bg-white focus:ring-2 focus:ring-accent-200/70"
            title="Graph name — used as the artifact slug on Run"
            aria-label="Graph name"
          />
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
          <div className="relative ml-auto" ref={moreRef}>
            <button
              type="button"
              className="btn-quiet"
              onClick={() => setMoreOpen((o) => !o)}
              aria-expanded={moreOpen}
              aria-haspopup="menu"
              aria-label="More builder actions"
            >
              <MoreHorizontal className="h-3.5 w-3.5" />
            </button>
            {moreOpen && (
              <div
                className="absolute right-0 z-50 mt-1 w-64 rounded-2xl border border-ink-200 bg-white p-2 shadow-soft"
                onMouseDown={(e) => e.stopPropagation()}
                onPointerDown={(e) => e.stopPropagation()}
              >
                <div className="mb-2 space-y-1 border-b border-ink-100 px-1 pb-2">
                  <input
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                    placeholder="template-name"
                    className="field-control mt-0 text-xs"
                    title="Name used when saving a template"
                    aria-label="Template name"
                  />
                  <button type="button" className="btn-secondary w-full justify-start" onClick={() => { void saveTemplate(); setMoreOpen(false) }}>
                    <BookmarkPlus className="h-3.5 w-3.5" /> Save template
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

        {actionError && (
          <div className="border-b border-rose-100 px-3 py-2">
            <ErrorBanner
              title={actionError.title}
              message={actionError.message}
              detail={actionError.detail}
              onDismiss={() => setActionError(null)}
              onRetry={runHadErrors || actionError.title.toLowerCase().includes('run') ? () => void handleRun() : undefined}
              actions={
                lastRunId ? (
                  <button type="button" className="btn-secondary" onClick={() => openRun(lastRunId)}>
                    Open run
                  </button>
                ) : null
              }
            />
          </div>
        )}
        <div className="relative flex min-h-0 flex-1 bg-canvas">
          <div className="relative min-h-0 min-w-0 flex-1">
          {nodes.length > 0 && (
            <div className="pointer-events-none absolute left-3 top-3 z-10 max-w-xs rounded-lg border border-ink-200/80 bg-white/90 px-2.5 py-1.5 text-type-meta text-ink-500 shadow-sm backdrop-blur">
              Drag from a teal output handle to a dark input handle to connect. Hover a handle for port type.
            </div>
          )}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultEdgeOptions={defaultEdgeOptions}
            connectionLineStyle={{ stroke: '#ff6d5a', strokeWidth: 2.75 }}
            connectionLineType={ConnectionLineType.Bezier}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={(c) => void onConnect(c)}
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
            deleteKeyCode={['Backspace', 'Delete']}
            edgesFocusable
            elementsSelectable
            snapToGrid
            snapGrid={[20, 20]}
            panOnScroll
            fitView
          >
            <Background gap={22} size={1} color="#c5d0da" />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
          {nodes.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
              <div className="pointer-events-auto max-w-sm rounded-3xl border border-ink-200/80 bg-white/90 px-8 py-7 text-center shadow-soft backdrop-blur">
                <div className="text-lg font-semibold text-ink-950">Start a pipeline</div>
                <p className="mt-2 text-sm leading-relaxed text-ink-500">
                  Pick a node from the left, open a template, or pull files / a dataset workspace into the loop.
                </p>
                <div className="mt-3 flex flex-wrap justify-center gap-2">
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => {
                      setView('templates')
                      window.history.replaceState(null, '', '#/templates')
                    }}
                  >
                    Open Templates
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() =>
                      openData({
                        mode: 'outputs',
                        project: builderDataset?.project,
                        version: builderDataset?.version,
                      })
                    }
                  >
                    <Database className="h-3.5 w-3.5" /> Open Data
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() =>
                      openProjects({ project: builderDataset?.project })
                    }
                  >
                    <FolderKanban className="h-3.5 w-3.5" /> Open Projects
                  </button>
                </div>
              </div>
            </div>
          )}
          </div>
          <aside className="z-20 flex w-[340px] shrink-0 flex-col overflow-hidden border-l border-ink-200/70 bg-white/95 shadow-soft backdrop-blur">
            {(() => {
              const node = inspectorId ? nodes.find((n) => n.id === inspectorId) : null
              const edge = selectedEdgeId ? edges.find((e) => e.id === selectedEdgeId) : null
              const mode: 'node' | 'edge' | 'graph' = node ? 'node' : edge ? 'edge' : 'graph'
              const title =
                mode === 'node'
                  ? node!.data.label || node!.data.nodeType
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
                  <div className="flex items-start justify-between gap-2 border-b border-ink-100 px-3 py-2">
                    <div className="min-w-0">
                      <div className="text-type-meta font-semibold uppercase tracking-wide text-ink-400">
                        {mode === 'node' ? 'Node' : mode === 'edge' ? 'Edge' : 'Graph'}
                      </div>
                      <div className="truncate text-sm font-semibold text-ink-950">{title}</div>
                      <div className="truncate text-[11px] text-ink-400" title={subtitle}>
                        {subtitle}
                      </div>
                    </div>
                    {(inspectorId || selectedEdgeId) && (
                      <button
                        type="button"
                        className="btn-icon"
                        aria-label="Clear selection"
                        onClick={() => {
                          setInspectorId(null)
                          setSelectedEdgeId(null)
                        }}
                      >
                        <X className="h-4 w-4" />
                      </button>
                    )}
                  </div>

                  {lastRunId || isRunning ? (
                    <div className="flex flex-wrap items-center gap-2 border-b border-ink-100 bg-ink-50/70 px-3 py-1.5 text-[11px] text-ink-600">
                      <span className="font-semibold uppercase tracking-wide text-ink-400">Execution</span>
                      {isRunning ? (
                        <StatusBadge status="running" />
                      ) : runCancelled ? (
                        <StatusBadge status="cancelled" />
                      ) : runHadErrors ? (
                        <StatusBadge status="failed" />
                      ) : lastRunId ? (
                        <StatusBadge status="succeeded" />
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
                        <label className="block text-[12px] text-ink-700">
                          <span className="font-medium">Graph name</span>
                          <input
                            value={graphName}
                            onChange={(e) => setGraphName(e.target.value.replace(/[^A-Za-z0-9_-]/g, '-'))}
                            onBlur={() => setGraphName((n) => slugifyName(n))}
                            className="field-control mt-1"
                            placeholder="pipeline"
                          />
                        </label>
                        <label className="block text-[12px] text-ink-700">
                          <span className="font-medium">Seed</span>
                          <input
                            type="number"
                            value={seed}
                            onChange={(e) => setSeed(Number(e.target.value) || 0)}
                            className="field-control mt-1 font-mono"
                          />
                        </label>
                        <div className="rounded-lg border border-ink-100 bg-ink-50 px-2.5 py-2 text-[11px] text-ink-500">
                          {nodes.length} nodes · {edges.length} connections
                          {lastRunId ? (
                            <div className="mt-1">
                              Linked run{' '}
                              <button type="button" className="font-mono text-accent-700 hover:underline" onClick={() => openRun(lastRunId)}>
                                {shortRunId(lastRunId)}
                              </button>
                            </div>
                          ) : (
                            <div className="mt-1">Select a node or connection to inspect details.</div>
                          )}
                        </div>
                      </>
                    )}

                    {mode === 'edge' && edge && (
                      <>
                        <div className="space-y-1.5 text-[12px] text-ink-700">
                          <div className="grid grid-cols-[4.5rem_1fr] gap-1">
                            <span className="text-ink-400">From</span>
                            <span className="font-mono text-[11px]">{edge.source}</span>
                          </div>
                          <div className="grid grid-cols-[4.5rem_1fr] gap-1">
                            <span className="text-ink-400">Port</span>
                            <span className="font-mono text-[11px]">{canonicalPort(edge.sourceHandle, 'output')}</span>
                          </div>
                          <div className="grid grid-cols-[4.5rem_1fr] gap-1">
                            <span className="text-ink-400">To</span>
                            <span className="font-mono text-[11px]">{edge.target}</span>
                          </div>
                          <div className="grid grid-cols-[4.5rem_1fr] gap-1">
                            <span className="text-ink-400">Port</span>
                            <span className="font-mono text-[11px]">{canonicalPort(edge.targetHandle, 'input')}</span>
                          </div>
                        </div>
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
                        {normalizeExecStatus(node.data.status) !== 'idle' && (
                          <div className="mb-1">
                            <StatusBadge status={normalizeExecStatus(node.data.status)} />
                          </div>
                        )}
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
                                <button type="button" className="btn-primary" onClick={() => void handleRun()}>
                                  Retry run
                                </button>
                              ) : null}
                            </div>
                          </div>
                        )}
                        <div className="mb-3 rounded-lg border border-ink-200 bg-ink-50/70 p-2.5 space-y-2">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                              Placement (Mode B)
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
                            Local Mode A ignores these hints. Distributed Mode B routes by mode / tags / GPU / pool / worker.
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
                        {(() => {
                          const entries = Object.entries(node.data.schemaProps ?? {}) as [string, Record<string, unknown>][]
                          if (entries.length === 0) return <div className="text-sm text-ink-400">No config fields</div>
                          const normalizeGroup = (def: Record<string, unknown>) => {
                            const g = String(def.group ?? '').trim()
                            if (!g) return 'Basic'
                            const low = g.toLowerCase()
                            if (low === 'advanced' || low === 'adv') return 'Advanced'
                            if (low === 'basic') return 'Basic'
                            return g
                          }
                          const basic = entries.filter(([, def]) => normalizeGroup(def) !== 'Advanced')
                          const advanced = entries.filter(([, def]) => normalizeGroup(def) === 'Advanced')
                          const renderField = ([key, def]: [string, Record<string, unknown>]) => (
                            <label key={key} className="block text-[12px] text-ink-700" title={schemaFieldHint(def)}>
                              <span className="font-medium">{schemaFieldLabel(key, def)}</span>
                              {schemaFieldHint(def) ? (
                                <span className="mt-0.5 block text-[10px] leading-snug text-ink-400">
                                  {schemaFieldHint(def)}
                                </span>
                              ) : null}
                              <ConfigFieldEditor
                                fieldKey={key}
                                def={def}
                                value={node.data.config?.[key] ?? def.default}
                                onChange={(v) => node.data.onChangeConfig?.(key, v)}
                              />
                            </label>
                          )
                          return (
                            <>
                              {basic.map(renderField)}
                              {advanced.length > 0 ? (
                                <div className="mt-2 rounded-lg border border-ink-200 bg-ink-50/60">
                                  <button
                                    type="button"
                                    className="flex w-full items-center justify-between px-2.5 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-500 hover:text-ink-800"
                                    onClick={() => setAdvancedOpen((v) => !v)}
                                    aria-expanded={advancedOpen}
                                  >
                                    <span>Advanced ({advanced.length})</span>
                                    {advancedOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                                  </button>
                                  {advancedOpen ? (
                                    <div className="space-y-2 border-t border-ink-200 px-2.5 py-2">
                                      {advanced.map(renderField)}
                                    </div>
                                  ) : null}
                                </div>
                              ) : null}
                            </>
                          )
                        })()}
                      </>
                    )}
                  </div>
                </>
              )
            })()}
          </aside>
        </div>

        <div className="relative z-20 border-t border-ink-800 bg-[#12181f] text-ink-100">
          <div
            className="absolute inset-x-0 -top-1 z-30 h-2 cursor-row-resize"
            onPointerDown={onLogResize}
            title="Drag to resize log"
          />
          <div className="flex items-center gap-2 px-3 py-1">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Execution log</div>
            {errorLogs.length > 0 && (
              <button
                type="button"
                className="inline-flex items-center gap-1 rounded bg-rose-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-rose-200 hover:bg-rose-500/30"
                onClick={focusLogErrors}
              >
                {errorLogs.length} {errorLogs.length === 1 ? 'error' : 'errors'}
              </button>
            )}
            <div className="ml-auto flex items-center gap-2">
              {lastRunId && (
                <button
                  type="button"
                  className="inline-flex items-center gap-1 text-[11px] font-medium text-accent-300 hover:text-accent-200"
                  onClick={() => openRun(lastRunId)}
                >
                  <ExternalLink className="h-3 w-3" /> Open run
                </button>
              )}
              <button
                type="button"
                className="text-[11px] font-medium text-ink-400 hover:text-ink-100"
                onClick={() => setShowRawLogs((v) => !v)}
              >
                {showRawLogs ? 'Pretty' : 'Raw'}
              </button>
              <button
                type="button"
                className="text-ink-400 hover:text-ink-100"
                aria-label={logCollapsed ? 'Expand log' : 'Collapse log'}
                onClick={() => setLogCollapsed((v) => !v)}
              >
                {logCollapsed ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>
          {!logCollapsed && (
            <div
              ref={logBodyRef}
              style={{ height: logHeight }}
              className="overflow-y-auto px-3 pb-2 font-mono text-[11px]"
              onScroll={(e) => {
                const el = e.currentTarget
                stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32
              }}
            >
              {errorLogs.length > 0 && (
                <div className="sticky top-0 z-10 mb-1 rounded bg-rose-950/90 px-2 py-1 text-[11px] text-rose-100">
                  <button type="button" className="hover:underline" onClick={focusLogErrors}>
                    Jump to error
                  </button>
                </div>
              )}
              {prettyLogs.length === 0 ? (
                <div className="text-ink-500">No events yet.</div>
              ) : (
                prettyLogs.map((l, i) => {
                  const isErr = l.level === 'error' || /fail|error/i.test(l.message)
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
  )
}

export default function BuilderView() {
  return (
    <ReactFlowProvider>
      <BuilderInner />
    </ReactFlowProvider>
  )
}
