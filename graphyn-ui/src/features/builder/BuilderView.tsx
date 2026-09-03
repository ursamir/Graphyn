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
} from 'lucide-react'
import { apiFetch, apiJson, ApiError, getApiToken } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { EmptyState } from '../../components/ui'
import { formatExecutionLine, formatValidationErrors, humanNodeLabel, isIsolatedRuntime, skipConsecutiveByText } from '../../lib/format'
import {
  buildGraphFromCanvas,
  catalogPorts,
  type GraphIR,
  type NodeCatalogEntry,
} from '../../types/graph'
import GraphynNode, { type GraphynNodeData } from './GraphynNode'

const nodeTypes = { graphyn: GraphynNode }

function defaultsFromSchema(entry?: NodeCatalogEntry): Record<string, unknown> {
  const props = entry?.config_schema?.properties ?? {}
  const cfg: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(props)) {
    if (v && typeof v === 'object' && 'default' in v) cfg[k] = v.default
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
  const setLastRunId = useAppStore((s) => s.setLastRunId)
  const setStatusMessage = useAppStore((s) => s.setStatusMessage)
  const pushToast = useAppStore((s) => s.pushToast)
  const openRun = useAppStore((s) => s.openRun)
  const setGetCanvasGraph = useAppStore((s) => s.setGetCanvasGraph)

  const [nodes, setNodes, onNodesChange] = useNodesState<GraphynNodeData>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [filter, setFilter] = React.useState('')
  const [templateName, setTemplateName] = React.useState('')
  const [moreOpen, setMoreOpen] = React.useState(false)
  const [showRawLogs, setShowRawLogs] = React.useState(false)
  const moreRef = React.useRef<HTMLDivElement | null>(null)
  const abortRef = React.useRef<AbortController | null>(null)
  const nodesRef = React.useRef(nodes)
  const edgesRef = React.useRef(edges)
  nodesRef.current = nodes
  edgesRef.current = edges

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
        },
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
      ),
    [seed],
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
      const outPort = connection.sourceHandle || 'output'
      const inPort = connection.targetHandle || 'input'
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
      setEdges((eds) => addEdge({ ...connection, id: `${connection.source}-${outPort}->${connection.target}-${inPort}` }, eds))
    },
    [setEdges, pushToast],
  )

  const addNode = (entry: NodeCatalogEntry) => {
    const id = `${entry.node_type}_${crypto.randomUUID().slice(0, 8)}`
    const ports = catalogPorts(entry)
    const node: Node<GraphynNodeData> = attachHandlers({
      id,
      type: 'graphyn',
      position: { x: 120 + Math.random() * 240, y: 80 + nodes.length * 28 },
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
    if (typeof graph.metadata?.seed === 'number') setSeed(graph.metadata.seed)
    const byType = new Map(catalog.map((c) => [c.node_type, c]))
    const ui = graph.ui?.positions
      ? graph.ui
      : (graph.parameters?.ui as { positions?: Record<string, { x: number; y: number }> } | undefined)
    const positions = ui?.positions ?? {}
    const nextNodes = graph.nodes.map((n, i) => {
      const entry = byType.get(n.node_type)
      const ports = catalogPorts(entry)
      return attachHandlers({
        id: n.id,
        type: 'graphyn',
        position: positions[n.id] ?? { x: 180 + (i % 3) * 280, y: 60 + Math.floor(i / 3) * 160 },
        data: {
          nodeType: n.node_type,
          label: entry?.label || n.label || humanNodeLabel(n.node_type),
          category: entry?.category,
          runtime: entry?.runtime,
          config: { ...defaultsFromSchema(entry), ...(n.config ?? {}) },
          schemaProps: entry?.config_schema?.properties ?? {},
          inputs: ports.inputs.length ? ports.inputs : [{ name: 'input' }],
          outputs: ports.outputs.length ? ports.outputs : [{ name: 'output' }],
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
    }))
    setNodes(nextNodes)
    setEdges(nextEdges)
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
      setStatusMessage(hadError ? 'Run finished with errors' : 'Run complete')
      pushToast(hadError ? 'Run finished with errors' : 'Run complete', hadError ? 'error' : 'success')
      if (runId) setLastRunId(runId)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      if (err instanceof ApiError && err.status === 0) return
      const msg = err instanceof Error ? err.message : String(err)
      addLog(msg, 'error')
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
    a.download = 'pipeline.graph.json'
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
    if (!/^[A-Za-z0-9_-]+$/.test(templateName)) {
      pushToast('Template name must match [A-Za-z0-9_-]+', 'error')
      return
    }
    try {
      const graph = currentGraph()
      const res = await apiJson<{ name: string; version?: string }>('/pipelines/templates', {
        method: 'POST',
        body: JSON.stringify({
          name: templateName,
          yaml: JSON.stringify(graph),
          description: 'Saved from Graphyn Builder',
        }),
      })
      pushToast(`Template saved: ${res.name}${res.version ? ` @ ${res.version}` : ''}`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const filtered = catalog.filter((n) => {
    const q = filter.toLowerCase()
    if (!q) return true
    return (
      n.node_type.toLowerCase().includes(q) ||
      (n.label ?? '').toLowerCase().includes(q) ||
      (n.category ?? '').toLowerCase().includes(q)
    )
  })

  const byCategory = React.useMemo(() => {
    const map = new Map<string, NodeCatalogEntry[]>()
    for (const n of filtered) {
      const cat = n.category || 'Other'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(n)
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [filtered])

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-72 shrink-0 flex-col border-r border-ink-200 bg-white/80 backdrop-blur">
        <div className="border-b border-ink-100 p-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-ink-500">Node catalog</div>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search nodes…"
            className="mt-2 w-full rounded-lg border border-ink-200 bg-ink-50 px-2.5 py-1.5 text-sm"
          />
        </div>
        <div className="flex-1 overflow-y-auto p-2">
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
          ) : byCategory.length === 0 ? (
            <div className="px-2 py-6 text-sm text-ink-500">No nodes match the search.</div>
          ) : (
            byCategory.map(([cat, items]) => (
              <div key={cat} className="mb-3">
                <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                  {cat}
                </div>
                <div className="space-y-1">
                  {items.map((n) => (
                    <button
                      key={n.node_type}
                      type="button"
                      onClick={() => addNode(n)}
                      className="w-full rounded-lg border border-transparent px-2 py-1.5 text-left hover:border-ink-200 hover:bg-ink-50"
                    >
                      <div className="flex flex-wrap items-center gap-1.5">
                        <div className="text-sm font-medium text-ink-900">{n.label || humanNodeLabel(n.node_type)}</div>
                        {isIsolatedRuntime(n.runtime, n.node_type) && (
                          <span className="rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-600">
                            Isolated
                          </span>
                        )}
                      </div>
                      <div className="font-mono text-[10px] text-ink-400">{n.node_type}</div>
                    </button>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-200 bg-white/70 px-3 py-2 backdrop-blur">
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
          <div className="relative ml-auto" ref={moreRef}>
            <button
              type="button"
              className="btn-quiet"
              onClick={() => setMoreOpen((o) => !o)}
              aria-expanded={moreOpen}
            >
              <MoreHorizontal className="h-3.5 w-3.5" /> More
            </button>
            {moreOpen && (
              <div className="absolute right-0 z-20 mt-1 w-64 rounded-xl border border-ink-200 bg-white p-2 shadow-lg">
                <button type="button" className="btn-quiet w-full justify-start" onClick={() => { importIr(); setMoreOpen(false) }}>
                  <Upload className="h-3.5 w-3.5" /> Import
                </button>
                <button type="button" className="btn-quiet w-full justify-start" onClick={() => { exportIr(); setMoreOpen(false) }}>
                  <Download className="h-3.5 w-3.5" /> Export
                </button>
                <div className="mt-1 flex items-center gap-1 px-1">
                  <input
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                    placeholder="template-name"
                    className="min-w-0 flex-1 rounded-lg border border-ink-200 px-2 py-1 text-xs"
                  />
                  <button type="button" className="btn-quiet shrink-0" onClick={() => void saveTemplate()}>
                    <BookmarkPlus className="h-3.5 w-3.5" /> Save
                  </button>
                </div>
                <button
                  type="button"
                  className="btn-quiet w-full justify-start"
                  onClick={() => {
                    if (!window.confirm('Clear the canvas?')) return
                    setNodes([])
                    setEdges([])
                    clearLogs()
                    setMoreOpen(false)
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" /> Clear
                </button>
                <button
                  type="button"
                  disabled={nodes.length === 0 || isRunning}
                  className="btn-quiet w-full justify-start"
                  onClick={() => {
                    void handleRunAsync()
                    setMoreOpen(false)
                  }}
                >
                  Run in background
                </button>
                <label className="mt-1 flex items-center gap-2 px-2 py-1 text-xs text-ink-500">
                  <Hash className="h-3.5 w-3.5" />
                  Seed
                  <input
                    type="number"
                    value={seed}
                    onChange={(e) => setSeed(Number(e.target.value) || 0)}
                    className="w-16 rounded border border-ink-200 px-1 py-0.5 font-mono text-xs"
                    title="Graph seed"
                  />
                </label>
              </div>
            )}
          </div>
        </div>

        <div className="relative min-h-0 flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={(c) => void onConnect(c)}
            fitView
          >
            <Background gap={18} color="#c9d3dc" />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
          {nodes.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
              <div className="pointer-events-auto max-w-sm rounded-2xl border border-ink-200 bg-white/95 px-6 py-5 text-center shadow-sm">
                <div className="font-display text-base font-bold text-ink-900">Empty canvas</div>
                <p className="mt-1 text-sm text-ink-500">Add a node from the catalog, or open Templates.</p>
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

        <div className="h-40 border-t border-ink-200 bg-ink-950 px-3 py-2 text-ink-100">
          <div className="mb-1 flex items-center justify-between">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">
              Execution log
            </div>
            <button
              type="button"
              className="text-[11px] font-medium text-ink-400 hover:text-ink-100"
              onClick={() => setShowRawLogs((v) => !v)}
            >
              {showRawLogs ? 'Pretty' : 'Raw'}
            </button>
          </div>
          <div className="h-[7.5rem] overflow-y-auto font-mono text-[11px]">
            {logs.length === 0 ? (
              <div className="text-ink-500">No events yet.</div>
            ) : (
              skipConsecutiveByText(logs, (l) => (showRawLogs ? l.raw || l.message : l.message)).map((l, i) => (
                <div
                  key={`${l.ts}-${i}`}
                  className={
                    l.level === 'error'
                      ? 'text-rose-300'
                      : l.level === 'success'
                        ? 'text-accent-300'
                        : 'text-ink-200'
                  }
                >
                  {showRawLogs ? l.raw || l.message : l.message}
                </div>
              ))
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
