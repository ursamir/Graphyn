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
  const setView = useAppStore((s) => s.setView)
  const pushToast = useAppStore((s) => s.pushToast)

  const initial = parseTraceHash()
  const [artifactId, setArtifactId] = React.useState(initial.artifactId)
  const [runId, setRunId] = React.useState(initial.runId)
  const [trace, setTrace] = React.useState<TracePayload | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)

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
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        setError(msg)
        setTrace(null)
        pushToast(msg, 'error')
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

  const openArtifact = (id: string) => {
    setView('artifacts')
    window.history.replaceState(null, '', '#/artifacts')
    // Artifacts view does not deep-link yet — toast the id for copy.
    pushToast(`Open Artifacts and select ${id}`, 'info')
  }

  const chain = trace?.chain ?? []
  const inputs = Array.isArray(trace?.lineage?.inputs) ? trace!.lineage!.inputs! : []

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <PageHeader
        title="Trace"
        description="Accountability backtrack (canonical) — artifact → node → run → graph → inputs → worker. Artifacts is the library; Runs is the execution session."
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
          description="Paste an artifact id or run id, or use Open in Trace from Artifacts / Runs. This is the accountability surface — not the artifact library."
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
                onClick={() => {
                  setView('artifacts')
                  window.history.replaceState(null, '', '#/artifacts')
                }}
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
                      <li className="min-w-[9rem] flex-1 rounded-xl border border-ink-100 bg-ink-50/70 px-3 py-2.5">
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
                        {step.id && (
                          <div className="mt-1.5">
                            <CopyableMono value={String(step.id)} />
                          </div>
                        )}
                        <div className="mt-2 flex flex-wrap gap-1">
                          {step.step === 'run' && step.id && (
                            <button
                              type="button"
                              className="btn-secondary !px-2 !py-0.5 text-[11px]"
                              onClick={() => openRun(String(step.id))}
                            >
                              Open Run
                            </button>
                          )}
                          {step.step === 'artifact' && step.id && (
                            <button
                              type="button"
                              className="btn-secondary !px-2 !py-0.5 text-[11px]"
                              onClick={() => openArtifact(String(step.id))}
                            >
                              Artifacts
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
                        </div>
                      </li>
                    </React.Fragment>
                  )
                })}
              </ol>
            )}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm space-y-3">
              <h3 className="text-sm font-semibold text-ink-800">Run</h3>
              {trace.run ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    {trace.run.status && <StatusBadge status={String(trace.run.status)} />}
                    {trace.run.run_id && (
                      <button
                        type="button"
                        className="btn-secondary !px-2 !py-0.5 text-[11px]"
                        onClick={() => openRun(String(trace.run!.run_id))}
                      >
                        Open Run {shortRunId(String(trace.run.run_id))}
                      </button>
                    )}
                  </div>
                  <KeyValue data={trace.run} />
                </>
              ) : (
                <p className="text-sm text-ink-500">No run linked.</p>
              )}
            </div>

            <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm space-y-3">
              <h3 className="text-sm font-semibold text-ink-800">Graph</h3>
              {trace.graph ? <KeyValue data={trace.graph} /> : <p className="text-sm text-ink-500">No graph summary.</p>}
              {trace.node && (
                <>
                  <h3 className="pt-2 text-sm font-semibold text-ink-800">Node</h3>
                  <KeyValue
                    data={{
                      ...trace.node,
                      node_type_label: trace.node.node_type
                        ? humanNodeLabel(String(trace.node.node_type))
                        : undefined,
                    }}
                  />
                </>
              )}
            </div>
          </div>

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

          {trace.artifact && (
            <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm space-y-3">
              <h3 className="text-sm font-semibold text-ink-800">Artifact record</h3>
              <KeyValue data={trace.artifact} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
