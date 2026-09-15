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
  CollapsibleJson,
  CopyableMono,
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { formatLocaleDateTime, humanNodeLabel, humanizeTemplateName, shortRunId } from '../../lib/format'

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

type RecentRun = {
  run_id: string
  status?: string
  graph_name?: string
  created_at?: string
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
  const activeProject = useAppStore((s) => s.activeProject)

  const initial = parseTraceHash()
  const [artifactId, setArtifactId] = React.useState(initial.artifactId)
  const [runId, setRunId] = React.useState(initial.runId)
  const [idsUnlocked, setIdsUnlocked] = React.useState(
    () => !(initial.artifactId.trim() || initial.runId.trim()),
  )
  const [trace, setTrace] = React.useState<TracePayload | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [selectedHop, setSelectedHop] = React.useState<number>(0)
  const [recentRuns, setRecentRuns] = React.useState<RecentRun[]>([])
  const [recentError, setRecentError] = React.useState<string | null>(null)
  const hasPrefill = Boolean(artifactId.trim() || runId.trim())
  const showRawIdPaste = idsUnlocked || !hasPrefill

  const loadRecentRuns = React.useCallback(async () => {
    setRecentError(null)
    try {
      const query: Record<string, string | number> = { limit: 20 }
      if (activeProject) query.project = activeProject
      const rows = await apiJson<RecentRun[]>('/runs', { query })
      setRecentRuns(Array.isArray(rows) ? rows : [])
    } catch (err) {
      setRecentRuns([])
      setRecentError(err instanceof Error ? err.message : String(err))
    }
  }, [activeProject])

  React.useEffect(() => {
    void loadRecentRuns()
  }, [loadRecentRuns])

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
    [artifactId, runId],
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

  const pickRecentRun = (id: string) => {
    const rid = id.trim()
    if (!rid) return
    setRunId(rid)
    setArtifactId('')
    setIdsUnlocked(false)
    void load('', rid)
  }

  const browseArtifacts = (opts?: { artifactId?: string; runId?: string }) => {
    const linkedRun = (opts?.runId || trace?.run?.run_id || '').toString().trim() || runId.trim()
    openArtifacts({
      runId: linkedRun || undefined,
      artifactId: opts?.artifactId,
    })
  }

  const openGraphHop = async (name?: string | null) => {
    const graphName = (name || trace?.graph?.name || trace?.run?.graph_name || '').trim()
    const rid = (trace?.run?.run_id || runId || '').trim()
    try {
      const graph = await fetchRunGraph(rid, graphName || null)
      if (graph) {
        loadGraphIntoBuilder(graph)
        pushToast(graphName ? `Opened ${graphName} in Editor` : 'Opened graph in Editor', 'success')
        return
      }
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
      return
    }
    setView('builder')
    window.history.replaceState(null, '', '#/builder')
    pushToast(graphName ? `Editor opened — graph ${graphName} not found on disk` : 'Opened Editor', 'info')
  }

  const chain = trace?.chain ?? []
  const inputs = Array.isArray(trace?.lineage?.inputs) ? trace!.lineage!.inputs! : []
  const selected = chain[selectedHop]

  const hopActions = (hop: TraceChainStep | undefined) => {
    if (!hop) return null
    const buttons: React.ReactNode[] = []
    if (hop.step === 'run' && hop.id) {
      buttons.push(
        <button
          key="open-run"
          type="button"
          className="btn-primary !px-2.5 !py-1 text-[12px]"
          onClick={() => openRun(String(hop.id))}
        >
          Open run {shortRunId(String(hop.id))}
        </button>,
        <button
          key="artifacts"
          type="button"
          className="btn-secondary !px-2.5 !py-1 text-[12px]"
          onClick={() => browseArtifacts({ runId: String(hop.id) })}
        >
          Artifacts
        </button>,
      )
    }
    if (hop.step === 'artifact' && hop.id) {
      buttons.push(
        <button
          key="artifacts"
          type="button"
          className="btn-primary !px-2.5 !py-1 text-[12px]"
          onClick={() =>
            browseArtifacts({
              artifactId: String(hop.id),
              runId: trace?.run?.run_id,
            })
          }
        >
          Artifacts
        </button>,
        <button
          key="retrace"
          type="button"
          className="btn-secondary !px-2.5 !py-1 text-[12px]"
          onClick={() => {
            setArtifactId(String(hop.id))
            setRunId('')
            void load(String(hop.id), '')
          }}
        >
          Trace this
        </button>,
      )
      if (trace?.run?.run_id) {
        buttons.push(
          <button
            key="open-run"
            type="button"
            className="btn-secondary !px-2.5 !py-1 text-[12px]"
            onClick={() => openRun(String(trace.run!.run_id))}
          >
            Open run
          </button>,
        )
      }
    }
    if (hop.step === 'graph') {
      buttons.push(
        <button
          key="builder"
          type="button"
          className="btn-primary !px-2.5 !py-1 text-[12px]"
          onClick={() => void openGraphHop(hop.label || trace?.graph?.name)}
        >
          Editor
        </button>,
      )
    }
    if (hop.step === 'node') {
      buttons.push(
        <button
          key="builder"
          type="button"
          className="btn-primary !px-2.5 !py-1 text-[12px]"
          onClick={() => void openGraphHop(trace?.graph?.name)}
        >
          Editor
        </button>,
      )
    }
    if (hop.step === 'worker') {
      buttons.push(
        <button
          key="workers"
          type="button"
          className="btn-primary !px-2.5 !py-1 text-[12px]"
          onClick={() => {
            setView('workers')
            window.history.replaceState(null, '', '#/workers')
          }}
        >
          Workers
        </button>,
      )
    }
    if (buttons.length === 0) return null
    return <div className="flex flex-wrap gap-1.5">{buttons}</div>
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <PageHeader
        title="Lineage"
        description="Deep-link and advanced provenance (`#/trace`). Open lineage from Runs → Lineage for a selected run."
        actions={
          <button type="button" className="btn-secondary" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        }
      />

      <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm space-y-3">
        <div className="space-y-2">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <label className="block min-w-[14rem] flex-1 text-sm">
              <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                Recent runs{activeProject ? ` · ${activeProject}` : ''}
              </span>
              <select
                className="field-control mt-0 w-full text-sm"
                value={recentRuns.some((r) => r.run_id === runId.trim()) ? runId.trim() : ''}
                onChange={(e) => pickRecentRun(e.target.value)}
              >
                <option value="">Pick a recent run…</option>
                {recentRuns.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {shortRunId(r.run_id)}
                    {r.graph_name ? ` · ${humanizeTemplateName(r.graph_name)}` : ''}
                    {r.status ? ` · ${r.status}` : ''}
                    {r.created_at ? ` · ${formatLocaleDateTime(r.created_at)}` : ''}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn-quiet text-[11px]" onClick={() => void loadRecentRuns()}>
              Refresh list
            </button>
          </div>
          {recentError ? <p className="text-[12px] text-rose-700">{recentError}</p> : null}
          {!recentError && recentRuns.length === 0 ? (
            <p className="text-[12px] text-ink-400">
              No recent runs{activeProject ? ' in this project' : ''}. Open Runs and select a run, or paste an artifact id below.
            </p>
          ) : null}
        </div>

        {hasPrefill && !showRawIdPaste ? (
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-2 text-sm text-ink-700">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Context</span>
            {runId.trim() ? (
              <span className="rounded-full border border-ink-200 bg-white px-2 py-0.5 font-mono text-[11px] text-ink-600" title={runId}>
                run {shortRunId(runId)}
              </span>
            ) : null}
            {artifactId.trim() ? (
              <span className="rounded-full border border-ink-200 bg-white px-2 py-0.5 font-mono text-[11px] text-ink-600" title={artifactId}>
                artifact {artifactId.length > 12 ? `${artifactId.slice(0, 8)}…` : artifactId}
              </span>
            ) : null}
            <span className="text-[11px] text-ink-400">Opened from Runs / Artifacts — no paste needed.</span>
            <button type="button" className="btn-quiet ml-auto text-[11px]" onClick={() => setIdsUnlocked(true)}>
              Change IDs
            </button>
          </div>
        ) : (
          <details className="rounded-xl border border-ink-100 bg-ink-50/50" open={!hasPrefill}>
            <summary className="cursor-pointer select-none px-3 py-2 text-[12px] font-medium text-ink-600">
              Advanced — paste artifact / run IDs
            </summary>
            <div className="grid gap-3 border-t border-ink-100 px-3 py-3 sm:grid-cols-2">
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
          </details>
        )}
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
              setIdsUnlocked(true)
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
          title="Open lineage from a run, or pick a recent run below."
          description="Prefer Runs → Lineage for a selected run. Use this page for artifact-id deep links only."
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={() => {
                setView('runs')
                window.history.replaceState(null, '', '#/runs')
                window.dispatchEvent(new HashChangeEvent('hashchange'))
              }}
            >
              Open Runs
            </button>
          }
        />
      )}

      {trace && !loading && (
        <div className="space-y-4">
          {Array.isArray(trace.warnings) && trace.warnings.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              Partial chain — {trace.warnings.join(' · ')}
            </div>
          )}

          {/* Hero hop chain */}
          <div className="rounded-2xl border border-accent-200/60 bg-gradient-to-b from-white to-accent-50/30 p-5 shadow-sm">
            <h3 className="mb-1 text-base font-semibold tracking-tight text-ink-900">Hop chain</h3>
            <p className="mb-4 text-[12px] text-ink-500">Select a hop for details and actions.</p>
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
                          className={`w-full rounded-xl border px-3 py-3 text-left transition ${
                            selectedHop === idx
                              ? 'border-accent-400 bg-white shadow-md ring-1 ring-accent-200'
                              : 'border-ink-100 bg-white/80 hover:border-ink-200'
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
                      </li>
                    </React.Fragment>
                  )
                })}
              </ol>
            )}
          </div>

          {/* Secondary hop detail + contextual actions */}
          {(() => {
            const hop = selected
            if (!hop) return null
            const pick = (src: Record<string, unknown> | null | undefined, keys: string[]) => {
              if (!src) return [] as Array<[string, string]>
              const out: Array<[string, string]> = []
              for (const k of keys) {
                const v = src[k]
                if (v == null || v === '') continue
                if (typeof v === 'object') continue
                out.push([k, String(v)])
              }
              return out
            }
            let fields: Array<[string, string]> = []
            if (hop.step === 'run' && trace.run) {
              fields = pick(trace.run as Record<string, unknown>, [
                'run_id',
                'status',
                'graph_name',
                'created_at',
                'worker_id',
              ])
            } else if (hop.step === 'graph' && trace.graph) {
              fields = pick(trace.graph as Record<string, unknown>, [
                'name',
                'graph_name',
                'version',
                'hash',
                'node_count',
              ])
            } else if (hop.step === 'node' && trace.node) {
              const node = trace.node as Record<string, unknown>
              fields = pick(node, ['id', 'node_type', 'status', 'label'])
              if (node.node_type) {
                fields = [['node_type', humanNodeLabel(String(node.node_type))], ...fields.filter(([k]) => k !== 'node_type')]
              }
            } else if (hop.step === 'artifact' && trace.artifact) {
              fields = pick(trace.artifact as Record<string, unknown>, [
                'artifact_id',
                'id',
                'artifact_type',
                'node_type',
                'run_id',
                'hash',
              ])
            } else if (hop.step === 'worker') {
              if (hop.id || hop.label) fields.push(['worker_id', String(hop.id || hop.label)])
              if (hop.ids && Array.isArray(hop.ids) && hop.ids.length) {
                fields.push(['ids', hop.ids.map(String).join(', ')])
              }
            } else {
              for (const [k, v] of [
                ['label', hop.label],
                ['id', hop.id],
                ['status', hop.status],
                ['node_type', hop.node_type],
                ['hash', hop.hash],
              ] as Array<[string, unknown]>) {
                if (v != null && v !== '') fields.push([k, String(v)])
              }
            }
            return (
              <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-ink-800">
                    {hop.step.charAt(0).toUpperCase() + hop.step.slice(1)} detail
                  </h3>
                  {hop.status ? <StatusBadge status={String(hop.status)} /> : null}
                </div>
                {hop.id ? (
                  <div>
                    <CopyableMono value={String(hop.id)} />
                  </div>
                ) : null}
                {hopActions(hop)}
                {fields.length > 0 ? (
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
                    {fields.slice(0, 6).map(([k, v]) => (
                      <React.Fragment key={k}>
                        <dt className="text-ink-500">{k}</dt>
                        <dd className="min-w-0 truncate font-mono text-[12px] text-ink-800" title={v}>
                          {v}
                        </dd>
                      </React.Fragment>
                    ))}
                  </dl>
                ) : (
                  <p className="text-sm text-ink-500">No details for this hop.</p>
                )}
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

          <CollapsibleJson value={trace} label="Raw trace JSON" />
        </div>
      )}
    </div>
  )
}
