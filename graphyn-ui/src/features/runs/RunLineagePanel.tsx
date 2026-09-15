import React from 'react'
import { ArrowRight, Box, GitBranch, Network, RefreshCw, Server, Workflow } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { fetchRunGraph } from '../../lib/runGraph'
import { CollapsibleJson, CopyableMono, EmptyState, ErrorBanner, LoadingBlock, StatusBadge } from '../../components/ui'
import { humanNodeLabel, shortRunId } from '../../lib/format'

type TraceChainStep = {
  step: string
  label: string
  id?: string
  status?: string
  node_type?: string
  present?: boolean
}

type TracePayload = {
  run?: {
    run_id?: string
    status?: string
    graph_name?: string
    created_at?: string
  } | null
  graph?: { name?: string; hash?: string; node_count?: number | null } | null
  lineage?: {
    inputs?: Array<Record<string, unknown>>
    nodes?: Array<Record<string, unknown>>
    artifacts?: Array<Record<string, unknown>>
    artifact_count?: number
    provenance_count?: number
    downstream_hint?: string
  }
  chain?: TraceChainStep[]
  warnings?: string[]
}

const STEP_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  artifact: Box,
  node: Network,
  run: GitBranch,
  graph: Workflow,
  worker: Server,
}

/** Run-scoped provenance: executed nodes → run → graph (Prefect-style accountability). */
export function RunLineagePanel({ runId }: { runId: string }) {
  const setView = useAppStore((s) => s.setView)
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)
  const pushToast = useAppStore((s) => s.pushToast)
  const openArtifacts = useAppStore((s) => s.openArtifacts)

  const [trace, setTrace] = React.useState<TracePayload | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [selectedHop, setSelectedHop] = React.useState(0)

  const load = React.useCallback(async () => {
    const rid = runId.trim()
    if (!rid) return
    setLoading(true)
    setError(null)
    try {
      const data = await apiJson<TracePayload>('/trace', { query: { run_id: rid } })
      setTrace(data)
      const steps = Array.isArray(data.chain) ? data.chain : []
      const prefer = steps.findIndex((s) => s && s.present !== false && s.step === 'node')
      setSelectedHop(prefer >= 0 ? prefer : 0)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setTrace(null)
    } finally {
      setLoading(false)
    }
  }, [runId])

  React.useEffect(() => {
    void load()
  }, [load])

  const chain = Array.isArray(trace?.chain) ? trace!.chain! : []
  const nodes = Array.isArray(trace?.lineage?.nodes) ? trace!.lineage!.nodes! : []
  const arts = Array.isArray(trace?.lineage?.artifacts) ? trace!.lineage!.artifacts! : []
  const selected = chain[selectedHop]
  const nodeSteps = chain.filter((s) => s.step === 'node')
  const contextSteps = chain.filter((s) => s.step !== 'node')

  const openEditor = () => {
    void (async () => {
      try {
        const g = await fetchRunGraph(runId)
        if (g) {
          loadGraphIntoBuilder(g)
          setView('builder')
          window.history.replaceState(null, '', '#/builder')
          window.dispatchEvent(new HashChangeEvent('hashchange'))
        } else {
          pushToast('No graph snapshot for this run', 'error')
        }
      } catch (err) {
        pushToast(err instanceof Error ? err.message : String(err), 'error')
      }
    })()
  }

  if (loading && !trace) return <LoadingBlock label="Loading lineage…" />
  if (error) return <ErrorBanner message={error} onRetry={() => void load()} />
  if (!trace) {
    return (
      <EmptyState
        title="No lineage for this run"
        description="Lineage answers: which nodes ran, what they produced, and which graph/worker. It is not the log."
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-ink-900">What ran, in order</p>
          <p className="mt-0.5 text-xs text-ink-500">
            Accountability for run <span className="font-mono text-ink-700">{shortRunId(runId)}</span>
            {typeof trace.lineage?.artifact_count === 'number'
              ? ` · ${trace.lineage.artifact_count} artifact${trace.lineage.artifact_count === 1 ? '' : 's'}`
              : ''}
            {typeof trace.lineage?.provenance_count === 'number'
              ? ` · ${trace.lineage.provenance_count} provenance`
              : ''}
            . Not a substitute for Logs.
          </p>
        </div>
        <button type="button" className="btn-quiet" aria-label="Refresh lineage" onClick={() => void load()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      {Array.isArray(trace.warnings) && trace.warnings.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {trace.warnings.map((w) => w.replace(/^[^:]+:/, (m) => m)).join(' · ')}
        </div>
      )}

      {nodeSteps.length === 0 && nodes.length === 0 ? (
        <EmptyState
          title="No node execution recorded"
          description="This run has no node_stats or registered artifacts yet. Logs still show what printed; Files shows downloadable outputs."
        />
      ) : (
        <ol className="space-y-1.5">
          {(nodeSteps.length ? nodeSteps : nodes.map((n) => ({
            step: 'node',
            label: String(n.node_type || n.id || 'node'),
            id: String(n.id || ''),
            node_type: n.node_type ? String(n.node_type) : undefined,
            status: n.status ? String(n.status) : undefined,
            present: true,
          }))).map((step, idx) => {
            const Icon = STEP_ICON.node
            const hopIdx = chain.findIndex((c) => c.step === 'node' && c.id === step.id && c.label === step.label)
            const active = hopIdx === selectedHop || (hopIdx < 0 && idx === selectedHop)
            return (
              <li key={`${step.id || step.label}-${idx}`}>
                <button
                  type="button"
                  onClick={() => setSelectedHop(hopIdx >= 0 ? hopIdx : idx)}
                  className={`flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left transition ${
                    active
                      ? 'border-accent-400 bg-white shadow-sm ring-1 ring-accent-200'
                      : 'border-ink-100 bg-white/80 hover:border-ink-200'
                  }`}
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink-100 text-[11px] font-semibold text-ink-600">
                    {idx + 1}
                  </span>
                  <Icon className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink-900">
                    {step.node_type ? humanNodeLabel(String(step.node_type)) : step.label}
                  </span>
                  {step.id ? (
                    <span className="hidden font-mono text-[10px] text-ink-400 sm:inline">{step.id}</span>
                  ) : null}
                  {step.status ? <StatusBadge status={String(step.status)} /> : null}
                </button>
              </li>
            )
          })}
        </ol>
      )}

      {contextSteps.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-500">
          <span className="font-semibold uppercase tracking-wide text-ink-400">Context</span>
          {contextSteps.map((step, idx) => {
            const Icon = STEP_ICON[step.step] || Box
            return (
              <React.Fragment key={`${step.step}-${idx}`}>
                {idx > 0 && <ArrowRight className="h-3 w-3 text-ink-300" />}
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded-full border border-ink-200 bg-white px-2 py-0.5 hover:border-accent-300"
                  onClick={() => {
                    const i = chain.findIndex((c) => c === step)
                    if (i >= 0) setSelectedHop(i)
                  }}
                >
                  <Icon className="h-3 w-3" />
                  {step.step}: {step.label}
                </button>
              </React.Fragment>
            )
          })}
        </div>
      )}

      {selected ? (
        <div className="rounded-xl border border-ink-100 bg-ink-50/60 px-3 py-2.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">{selected.step}</div>
          <div className="mt-1 text-sm font-medium text-ink-900">
            {selected.step === 'node' && selected.node_type
              ? humanNodeLabel(String(selected.node_type))
              : selected.label}
          </div>
          {selected.id ? (
            <div className="mt-1">
              <CopyableMono value={String(selected.id)} />
            </div>
          ) : null}
          {selected.step === 'node' && (
            <div className="mt-2 space-y-1">
              {arts
                .filter((a) => String(a.node_id || '') === String(selected.id || ''))
                .slice(0, 8)
                .map((a) => (
                  <div key={String(a.artifact_id)} className="flex items-center justify-between gap-2 text-[12px]">
                    <span className="truncate text-ink-600">
                      {String(a.artifact_type || 'artifact')}
                      {a.data_path ? ` · ${String(a.data_path).split('/').pop()}` : ''}
                    </span>
                    {a.artifact_id ? (
                      <button
                        type="button"
                        className="btn-quiet shrink-0 text-[11px]"
                        onClick={() =>
                          openArtifacts({
                            artifactId: String(a.artifact_id),
                            runId,
                          })
                        }
                      >
                        Record
                      </button>
                    ) : null}
                  </div>
                ))}
              {arts.filter((a) => String(a.node_id || '') === String(selected.id || '')).length === 0 ? (
                <p className="text-[12px] text-ink-500">No registered artifacts for this node — check Files for downloadable outputs.</p>
              ) : null}
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {(selected.step === 'graph' || selected.step === 'run' || selected.step === 'node') && (
              <button type="button" className="btn-secondary" onClick={openEditor}>
                <Workflow className="h-3.5 w-3.5" /> Open in Editor
              </button>
            )}
            {selected.step === 'worker' && (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setView('workers')
                  window.history.replaceState(null, '', '#/workers')
                  window.dispatchEvent(new HashChangeEvent('hashchange'))
                }}
              >
                <Server className="h-3.5 w-3.5" /> Workers
              </button>
            )}
          </div>
        </div>
      ) : null}

      {Array.isArray(trace.lineage?.inputs) && trace.lineage!.inputs!.length > 0 && (
        <div className="rounded-xl border border-ink-100 px-3 py-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Upstream inputs</div>
          <ul className="mt-1 space-y-0.5">
            {trace.lineage!.inputs!.slice(0, 12).map((inp, i) => (
              <li key={i} className="font-mono text-[11px] text-ink-600">
                {String(inp.artifact_id || '—')}
                {inp.node_type ? ` ← ${humanNodeLabel(String(inp.node_type))}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}

      <CollapsibleJson value={trace} label="Raw lineage JSON" />
    </div>
  )
}
