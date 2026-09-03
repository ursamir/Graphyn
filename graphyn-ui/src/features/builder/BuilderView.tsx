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
  AlertTriangle,
  ExternalLink,
  X,
} from 'lucide-react'
import { apiFetch, apiJson, ApiError, getApiToken } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { EmptyState } from '../../components/ui'
import { formatExecutionLine, formatValidationErrors, humanNodeLabel, isIsolatedRuntime, schemaFieldHint, schemaFieldLabel, skipConsecutiveByText } from '../../lib/format'
import {
  buildGraphFromCanvas,
  catalogPorts,
  type GraphIR,
  type NodeCatalogEntry,
  canonicalPort,
} from '../../types/graph'
import GraphynNode, { ConfigFieldEditor, categoryLook, type GraphynNodeData } from './GraphynNode'
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
  const pushToast = useAppStore((s) => s.pushToast)
  const openRun = useAppStore((s) => s.openRun)
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
  const [logCollapsed, setLogCollapsed] = React.useState(true)
  const [runHadErrors, setRunHadErrors] = React.useState(false)
  const [inspectorId, setInspectorId] = React.useState<string | null>(null)
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
    if (!moreOpen) return
    const onDoc = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as HTMLElement)) setMoreOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
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
        setStatusMessage(`Valid graph (${result.node_count ?? graph.nodes.length} nodes)`)
        pushToast('Validation passed', 'success')
        addLog('Validation passed', 'success')
      } else {
        setStatusMessage(result.error ?? 'Validation failed')
        pushToast(result.error ?? 'Validation failed', 'error')
        addLog(result.error ?? 'Validation failed', 'error')
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setStatusMessage(msg)
      pushToast(msg, 'error')
    }
  }

  const handleCancel = () => {
    abortRef.current?.abort()
    abortRef.current = null
    setIsRunning(false)
    setStatusMessage('Run cancelled')
    addLog('Run cancelled by user', 'warning')
  }

  const handleRun = async () => {
    clearLogs()
    setRunHadErrors(false)
    setLogCollapsed(false)
    setIsRunning(true)
    setStatusMessage('Running…')
    setNodes((nds) => nds.map((n) => ({ ...n, data: { ...n.data, status: 'idle' } })))
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const graph = currentGraph()
      const res = await apiFetch('/pipelines/run', {
        method: 'POST',
        body: JSON.stringify(graph),
        signal: controller.signal,
        timeoutMs: 30 * 60 * 1000,
        headers: { 'Content-Type': 'application/json' },
      })
      if (!res.ok) throw new ApiError(`Run failed: HTTP ${res.status}`, res.status, '/pipelines/run')
      if (!res.body) throw new Error('No response body')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let hadError = false
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
            if (ev.type === 'node_start' && typeof ev.node_type === 'string') {
              const idx = Number(ev.node_index)
              setNodes((nds) =>
                nds.map((n, i) =>
                  i === idx || n.data.nodeType === ev.node_type
                    ? { ...n, data: { ...n.data, status: i === idx ? 'running' : n.data.status } }
                    : n,
                ),
              )
              if (!Number.isNaN(idx)) {
                setNodes((nds) =>
                  nds.map((n, i) => (i === idx ? { ...n, data: { ...n.data, status: 'running' } } : n)),
                )
              }
            }
            if (ev.type === 'node_end') {
              const idx = Number(ev.node_index)
              if (!Number.isNaN(idx)) {
                setNodes((nds) =>
                  nds.map((n, i) => (i === idx ? { ...n, data: { ...n.data, status: 'success' } } : n)),
                )
              }
            }
            if (ev.type === 'node_error' || ev.type === 'error') {
              hadError = true
              const idx = Number(ev.node_index)
              if (!Number.isNaN(idx)) {
                setNodes((nds) =>
                  nds.map((n, i) => (i === idx ? { ...n, data: { ...n.data, status: 'error' } } : n)),
                )
              }
            }
            const formatted = formatExecutionLine(trimmed)
            addLog(
              formatted.text,
              formatted.level.includes('error') ? 'error' : formatted.level,
              formatted.raw,
            )
          } catch {
            const formatted = formatExecutionLine(trimmed)
            addLog(formatted.text, formatted.level, formatted.raw)
          }
        }
      }
      setRunHadErrors(hadError)
      setStatusMessage(hadError ? 'Run finished with errors' : 'Run complete')
      pushToast(hadError ? 'Run finished with errors' : 'Run complete', hadError ? 'error' : 'success')
      if (runId) setLastRunId(runId)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      if (err instanceof ApiError && err.status === 0) return
      const msg = err instanceof Error ? err.message : String(err)
      addLog(msg, 'error')
      setRunHadErrors(true)
      setStatusMessage(msg)
      pushToast(msg, 'error')
    } finally {
      setIsRunning(false)
      abortRef.current = null
    }
  }

  const handleRunAsync = async () => {
    try {
      const graph = currentGraph()
      const res = await apiJson<{ run_id: string }>('/pipelines/run-async', {
        method: 'POST',
        body: JSON.stringify(graph),
      })
      setLastRunId(res.run_id)
      pushToast(`Async run started: ${res.run_id}`, 'success')
      openRun(res.run_id)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
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

  const secondaryActions = (
    <>
      <button
        type="button"
        className="btn-quiet"
        onClick={() => {
          if (!window.confirm('Clear the canvas?')) return
          setNodes([])
          setEdges([])
          setGraphName('pipeline')
          setRunHadErrors(false)
          clearLogs()
          setMoreOpen(false)
        }}
      >
        <Trash2 className="h-3.5 w-3.5" /> Clear
      </button>
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

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-[17.5rem] shrink-0 flex-col border-r border-ink-200/80 bg-white">
        <div className="sticky top-0 z-10 border-b border-ink-100 bg-white p-2">
          <input
            id="builder-catalog-search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search nodes…"
            className="w-full rounded-lg border border-ink-200 bg-ink-50 px-2.5 py-1.5 text-sm"
          />
          <div className="mt-2 flex flex-wrap gap-1">
            <button
              type="button"
              className={categoryFilter === 'all' ? 'catalog-pill catalog-pill-on' : 'catalog-pill'}
              onClick={() => setCategoryFilter('all')}
            >
              All
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                className={categoryFilter === cat ? 'catalog-pill catalog-pill-on' : 'catalog-pill'}
                onClick={() => setCategoryFilter(cat)}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-1.5">
          {catalog.length === 0 ? (
            <div className="px-1 py-2">
              <EmptyState
                title={bootStatus === 401 || !getApiToken() ? 'Sign in to load nodes' : 'No plugins installed'}
                description={
                  bootStatus === 401 || !getApiToken()
                    ? 'Paste your API token in Settings to load the node catalog.'
                    : 'Install a plugin to populate the catalog, then add nodes here.'
                }
                action={
                  bootStatus === 401 || !getApiToken() ? (
                    <button type="button" className="btn-primary" onClick={() => setSettingsOpen(true)}>
                      Open Settings
                    </button>
                  ) : (
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
                  {categoryFilter === 'all' && (
                    <div className="px-2 pb-1 text-[11px] font-medium text-ink-400">
                      {cat}
                    </div>
                  )}
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
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="relative z-30 flex flex-wrap items-center gap-2 border-b border-ink-200/70 bg-white/90 px-3 py-2 backdrop-blur">
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

        <div className="relative flex min-h-0 flex-1 bg-canvas">
          <div className="relative min-h-0 min-w-0 flex-1">
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
            onNodeClick={(_, n) => setInspectorId(n.id)}
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
                <p className="mt-2 text-sm leading-relaxed text-ink-500">Pick a node from the left, or open a template and run it.</p>
                <button
                  type="button"
                  className="btn-primary mt-3"
                  onClick={() => {
                    setView('templates')
                    window.history.replaceState(null, '', '#/templates')
                  }}
                >
                  Open Templates
                </button>
              </div>
            </div>
          )}
          </div>
          {inspectorId && nodes.find((n) => n.id === inspectorId) && (
            <aside className="z-20 flex w-[380px] shrink-0 flex-col overflow-hidden border-l border-ink-200/70 bg-white/95 shadow-soft backdrop-blur">
              {(() => {
                const node = nodes.find((n) => n.id === inspectorId)
                if (!node) return null
                const entries = Object.entries(node.data.schemaProps ?? {})
                return (
                  <>
                    <div className="flex items-start justify-between gap-2 border-b border-ink-100 px-3 py-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-ink-950">
                          {node.data.label || node.data.nodeType}
                        </div>
                        <div className="truncate text-[11px] text-ink-400">{node.data.nodeType}</div>
                      </div>
                      <button
                        type="button"
                        className="btn-icon"
                        aria-label="Close inspector"
                        onClick={() => setInspectorId(null)}
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                    <div className="flex-1 space-y-2 overflow-y-auto px-3 py-2">
                      {entries.length === 0 ? (
                        <div className="text-sm text-ink-400">No config fields</div>
                      ) : (
                        entries.map(([key, def]) => (
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
                        ))
                      )}
                    </div>
                  </>
                )
              })()}
            </aside>
          )}
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
