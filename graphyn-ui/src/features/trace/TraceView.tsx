import React from 'react'
import {
  ArrowRight,
  Box,
  GitBranch,
  Network,
  RefreshCw,
  Search,
  Server,
  Workflow,
} from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { fetchRunGraph } from '../../lib/runGraph'
import {
  CopyableMono,
  EmptyState,
  ErrorBanner,
  KeyValue,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { humanNodeLabel, shortRunId } from '../../lib/format'

type TraceChainStep = {
  step: string
  label: string
  id?: string
  status?: string
  node_type?: string
  hash?: string
  present?: boolean
  ids?: string[]
}

type TracePayload = {
  subject?: { kind?: string; id?: string }
  run?: {
    run_id?: string
    status?: string
    graph_name?: string
    created_at?: string
    distributed_node_workers?: Record<string, string>
  } | null
  graph?: {
    name?: string
    schema_version?: string
    node_count?: number | null
    hash?: string
  } | null
  node?: { id?: string; node_type?: string; worker_id?: string } | null
  artifact?: Record<string, unknown> | null
  lineage?: {
    inputs?: Array<Record<string, unknown>>
    downstream_hint?: string
  }
  chain?: TraceChainStep[]
  warnings?: string[]
}

function parseTraceHash(): { artifactId: string; runId: string } {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const qIdx = raw.indexOf('?')
  if (qIdx < 0) return { artifactId: '', runId: '' }
  const params = new URLSearchParams(raw.slice(qIdx + 1))
  return {
    artifactId: (params.get('artifact_id') || '').trim(),
    runId: (params.get('run_id') || '').trim(),
  }
}

function writeTraceHash(artifactId: string, runId: string) {
  const params = new URLSearchParams()
  if (artifactId.trim()) params.set('artifact_id', artifactId.trim())
  if (runId.trim()) params.set('run_id', runId.trim())
  const qs = params.toString()
  const next = qs ? `#/trace?${qs}` : '#/trace'
  if (window.location.hash !== next) {
    window.history.replaceState(null, '', next)
  }
}

const STEP_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  artifact: Box,
  node: Network,
  run: GitBranch,
  graph: Workflow,
  worker: Server,
}

export default function TraceView() {
  const openRun = useAppStore((s) => s.openRun)
  const openArtifacts = useAppStore((s) => s.openArtifacts)
  const setView = useAppStore((s) => s.setView)
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)
  const pushToast = useAppStore((s) => s.pushToast)

  const initial = parseTraceHash()
  const [artifactId, setArtifactId] = React.useState(initial.artifactId)
  const [runId, setRunId] = React.useState(initial.runId)
  const [trace, setTrace] = React.useState<TracePayload | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [selectedHop, setSelectedHop] = React.useState<number>(0)

  const load = React.useCallback(
    async (aid?: string, rid?: string) => {
      const a = (aid ?? artifactId).trim()
      const r = (rid ?? runId).trim()
      if (!a && !r) {
        setTrace(null)
        setError(null)
        writeTraceHash('', '')
        return
      }
      setLoading(true)
      setError(null)
      writeTraceHash(a, r)
      try {
        const data = await apiJson<TracePayload>('/trace', {
          query: {
            artifact_id: a || undefined,
            run_id: r || undefined,
          },
        })
        setTrace(data)
        const steps = Array.isArray(data.chain) ? data.chain : []
        const prefer = steps.findIndex((s) => s && s.present !== false && (s.step === 'run' || s.step === 'artifact'))
        setSelectedHop(prefer >= 0 ? prefer : 0)
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        setError(msg)
        setTrace(null)
      } finally {
        setLoading(false)
      }
    },
    [artifactId, runId, pushToast],
  )

  React.useEffect(() => {
    const apply = () => {
      const { artifactId: a, runId: r } = parseTraceHash()
      setArtifactId(a)
      setRunId(r)
      if (a || r) void load(a, r)
    }
    apply()
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const browseArtifacts = (opts?: { artifactId?: string; runId?: string }) => {
    const linkedRun = (opts?.runId || trace?.run?.run_id || '').toString().trim() || runId.trim()
    openArtifacts({ runId: linkedRun || undefined })
    if (opts?.artifactId) {
      pushToast(`Browse artifacts — select ${opts.artifactId}`, 'info')
    }
  }

  const openGraphHop = async (name?: string | null) => {
    const graphName = (name || trace?.graph?.name || trace?.run?.graph_name || '').trim()
    const rid = (trace?.run?.run_id || runId || '').trim()
    try {
      const graph = await fetchRunGraph(rid, graphName || null)
      if (graph) {
        loadGraphIntoBuilder(graph)
        pushToast(graphName ? `Opened ${graphName} in Builder` : 'Opened graph in Builder', 'success')
        return
      }
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
      return
    }
    setView('builder')
    window.history.replaceState(null, '', '#/builder')
    pushToast(graphName ? `Builder opened — graph ${graphName} not found on disk` : 'Opened Builder', 'info')
  }

  const chain = trace?.chain ?? []
  const inputs = Array.isArray(trace?.lineage?.inputs) ? trace!.lineage!.inputs! : []

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <PageHeader
        title="Trace"
        description="Provenance chain: artifact → node → run → graph → worker."
        actions={
          <button type="button" className="btn-secondary" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        }
      />

      <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
              Artifact ID
            </span>
            <input
              className="field-control mt-0 w-full font-mono text-xs"
              value={artifactId}
              placeholder="artifact uuid / id"
              onChange={(e) => setArtifactId(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void load()
              }}
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
              Run ID
            </span>
            <input
              className="field-control mt-0 w-full font-mono text-xs"
              value={runId}
              placeholder="run id"
              onChange={(e) => setRunId(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void load()
              }}
            />
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-primary" onClick={() => void load()}>
            <Search className="h-3.5 w-3.5" /> Trace
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              setArtifactId('')
              setRunId('')
              setTrace(null)
              setError(null)
              writeTraceHash('', '')
            }}
          >
            Clear
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {loading && <LoadingBlock label="Assembling trace…" />}

      {!loading && !error && !trace && (
        <EmptyState
          title="Start a backtrack"
          description="Paste an artifact or run id, or use View lineage from Runs / Artifacts."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setView('runs')
                  window.history.replaceState(null, '', '#/runs')
                }}
              >
                Open Runs
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => openArtifacts()}
              >
                Open Artifacts
              </button>
            </div>
          }
        />
      )}

      {trace && !loading && (
        <div className="space-y-6">
          {Array.isArray(trace.warnings) && trace.warnings.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              Partial chain — {trace.warnings.join(' · ')}
            </div>
          )}

          {/* Visual chain */}
          <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold text-ink-800">Chain</h3>
            {chain.length === 0 ? (
              <p className="text-sm text-ink-500">No chain steps available.</p>
            ) : (
              <ol className="flex flex-wrap items-stretch gap-2">
                {chain.map((step, idx) => {
                  const Icon = STEP_ICON[step.step] || Box
                  return (
                    <React.Fragment key={`${step.step}-${idx}`}>
                      {idx > 0 && (
                        <li className="flex items-center text-ink-300" aria-hidden>
                          <ArrowRight className="h-4 w-4" />
                        </li>
                      )}
                      <li className="min-w-[9rem] flex-1">
                        <button
                          type="button"
                          onClick={() => setSelectedHop(idx)}
                          className={`w-full rounded-xl border px-3 py-2.5 text-left transition ${
                            selectedHop === idx
                              ? 'border-accent-300 bg-accent-50/80 shadow-sm'
                              : 'border-ink-100 bg-ink-50/70 hover:border-ink-200'
                          }`}
                        >
                        <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-ink-500">
                          <Icon className="h-3 w-3" />
                          {step.step}
                        </div>
                        <div className="mt-1 truncate text-sm font-medium text-ink-900" title={step.label}>
                          {step.step === 'node' && step.node_type
                            ? humanNodeLabel(String(step.node_type))
                            : step.label}
                        </div>
                        {step.status && (
                          <div className="mt-1">
                            <StatusBadge status={String(step.status)} />
                          </div>
                        )}
                        </button>
                        {step.id && (
                          <div className="mt-1.5 px-1">
                            <CopyableMono value={String(step.id)} />
                          </div>
                        )}
                        {selectedHop === idx && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {step.step === 'run' && step.id && (
                            <>
                              <button
                                type="button"
                                className="btn-secondary !px-2 !py-0.5 text-[11px]"
                                onClick={() => browseArtifacts({ runId: String(step.id) })}
                              >
                                Artifacts
                              </button>
                            </>
                          )}
                          {step.step === 'artifact' && step.id && (
                            <>
                              <button
                                type="button"
                                className="btn-secondary !px-2 !py-0.5 text-[11px]"
                                onClick={() =>
                                  browseArtifacts({
                                    artifactId: String(step.id),
                                    runId: trace?.run?.run_id,
                                  })
                                }
                              >
                                Artifacts
                              </button>
                              <button
                                type="button"
                                className="btn-secondary !px-2 !py-0.5 text-[11px]"
                                onClick={() => {
                                  setArtifactId(String(step.id))
                                  setRunId('')
                                  void load(String(step.id), '')
                                }}
                              >
                                Trace
                              </button>
                            </>
                          )}
                          {step.step === 'graph' && (
                            <button
                              type="button"
                              className="btn-secondary !px-2 !py-0.5 text-[11px]"
                              onClick={() => void openGraphHop(step.label || trace?.graph?.name)}
                            >
                              Builder
                            </button>
                          )}
                          {step.step === 'worker' && (
                            <button
                              type="button"
                              className="btn-secondary !px-2 !py-0.5 text-[11px]"
                              onClick={() => {
                                setView('workers')
                                window.history.replaceState(null, '', '#/workers')
                              }}
                            >
                              Workers
                            </button>
                          )}
                          {step.step === 'node' && (
                            <button
                              type="button"
                              className="btn-secondary !px-2 !py-0.5 text-[11px]"
                              onClick={() => void openGraphHop(trace?.graph?.name)}
                            >
                              Builder
                            </button>
                          )}
                        </div>
                        )}
                      </li>
                    </React.Fragment>
                  )
                })}
              </ol>
            )}
          </div>

          {(() => {
            const hop = chain[selectedHop]
            if (!hop) return null
            let data: Record<string, unknown> | null = null
            if (hop.step === 'run' && trace.run) data = { ...trace.run }
            else if (hop.step === 'graph' && trace.graph) data = { ...trace.graph }
            else if (hop.step === 'node' && trace.node) {
              data = {
                ...trace.node,
                node_type_label: trace.node.node_type
                  ? humanNodeLabel(String(trace.node.node_type))
                  : undefined,
              }
            } else if (hop.step === 'artifact' && trace.artifact) data = { ...trace.artifact }
            else if (hop.step === 'worker') {
              data = { worker_id: hop.id || hop.label, ids: hop.ids }
            } else {
              data = {
                step: hop.step,
                label: hop.label,
                id: hop.id,
                status: hop.status,
                node_type: hop.node_type,
                hash: hop.hash,
              }
            }
            const runIdForOpen =
              hop.step === 'run' && hop.id
                ? String(hop.id)
                : ''
            return (
              <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-ink-800">
                    {hop.step.charAt(0).toUpperCase() + hop.step.slice(1)} detail
                  </h3>
                  <div className="flex flex-wrap gap-1">
                    {hop.step === 'run' && runIdForOpen ? (
                      <button
                        type="button"
                        className="btn-secondary !px-2 !py-0.5 text-[11px]"
                        onClick={() => openRun(runIdForOpen)}
                      >
                        Open Run {shortRunId(runIdForOpen)}
                      </button>
                    ) : null}
                    {hop.step === 'graph' ? (
                      <button
                        type="button"
                        className="btn-secondary !px-2 !py-0.5 text-[11px]"
                        onClick={() => void openGraphHop(hop.label || trace?.graph?.name)}
                      >
                        Builder
                      </button>
                    ) : null}
                    {hop.step === 'worker' ? (
                      <button
                        type="button"
                        className="btn-secondary !px-2 !py-0.5 text-[11px]"
                        onClick={() => {
                          setView('workers')
                          window.history.replaceState(null, '', '#/workers')
                        }}
                      >
                        Workers
                      </button>
                    ) : null}
                    {hop.step === 'artifact' && hop.id ? (
                      <button
                        type="button"
                        className="btn-secondary !px-2 !py-0.5 text-[11px]"
                        onClick={() =>
                          browseArtifacts({
                            artifactId: String(hop.id),
                            runId: trace?.run?.run_id,
                          })
                        }
                      >
                        Artifacts
                      </button>
                    ) : null}
                  </div>
                </div>
                {hop.status ? <StatusBadge status={String(hop.status)} /> : null}
                {data ? <KeyValue data={data} /> : <p className="text-sm text-ink-500">No details for this hop.</p>}
              </div>
            )
          })()}

          <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm space-y-3">
            <h3 className="text-sm font-semibold text-ink-800">Lineage inputs</h3>
            {inputs.length === 0 ? (
              <p className="text-sm text-ink-500">No upstream inputs recorded.</p>
            ) : (
              <ul className="space-y-1.5">
                {inputs.map((item, i) => {
                  const id = String(item.artifact_id ?? item.id ?? '').trim()
                  if (!id) return null
                  const label = String(item.node_type ?? item.artifact_type ?? id)
                  return (
                    <li
                      key={`${id}-${i}`}
                      className="flex flex-wrap items-center gap-2 rounded-xl border border-ink-200 bg-ink-50/50 px-3 py-2"
                    >
                      <button
                        type="button"
                        className="min-w-0 flex-1 truncate text-left text-sm font-medium text-ink-900 hover:text-accent-700"
                        onClick={() => {
                          setArtifactId(id)
                          void load(id, runId)
                        }}
                      >
                        {item.node_type ? humanNodeLabel(String(item.node_type)) : label}
                      </button>
                      <CopyableMono value={id} />
                      <button
                        type="button"
                        className="btn-secondary !px-2 !py-0.5 text-[11px]"
                        onClick={() => {
                          setArtifactId(id)
                          void load(id, '')
                        }}
                      >
                        Trace
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
            {trace.lineage?.downstream_hint && (
              <p className="text-xs text-ink-400">{trace.lineage.downstream_hint}</p>
            )}
          </div>

        </div>
      )}
    </div>
  )
}
