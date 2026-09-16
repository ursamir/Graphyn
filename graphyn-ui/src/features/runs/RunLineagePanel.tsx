/**
 * Run-scoped provenance detail — node list lives in the parent PipelineStack.
 * Right pane content follows Focus (All = overview, node = that hop’s artifacts).
 */
import React from 'react'
import { ArrowRight, Box, GitBranch, Network, RefreshCw, Server, Workflow } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { CopyableMono, EmptyState, ErrorBanner, LoadingBlock } from '../../components/ui'
import { ReproPackButton } from '../../components/ReproPackButton'
import { goView } from '../../routes/nav'
import { humanNodeLabel, focusMatchesNode } from '../../lib/format'

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
export function RunLineagePanel({
  runId,
  runMeta,
  focusNodeId = null,
}: {
  runId: string
  runMeta?: Record<string, unknown> | null
  focusNodeId?: string | null
}) {
  const openArtifacts = useAppStore((s) => s.openArtifacts)

  const [trace, setTrace] = React.useState<TracePayload | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)

  const load = React.useCallback(async () => {
    const rid = runId.trim()
    if (!rid) return
    setLoading(true)
    setError(null)
    try {
      const data = await apiJson<TracePayload>('/trace', { query: { run_id: rid } })
      setTrace(data)
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
  const nodeSteps = chain.filter((s) => s.step === 'node')
  const contextSteps = chain.filter((s) => s.step !== 'node')

  const selectedNode: TraceChainStep | null = React.useMemo(() => {
    if (!focusNodeId) return null
    const fromChain = nodeSteps.find(
      (s) =>
        focusMatchesNode(focusNodeId, s.id) ||
        focusMatchesNode(focusNodeId, s.label) ||
        focusMatchesNode(focusNodeId, s.node_type),
    )
    if (fromChain) return fromChain
    const fromNodes = nodes.find(
      (n) =>
        focusMatchesNode(focusNodeId, String(n.id || '')) ||
        focusMatchesNode(focusNodeId, String(n.node_type || '')),
    )
    if (fromNodes) {
      return {
        step: 'node',
        label: String(fromNodes.node_type || fromNodes.id || 'node'),
        id: String(fromNodes.id || ''),
        node_type: fromNodes.node_type ? String(fromNodes.node_type) : undefined,
        status: fromNodes.status ? String(fromNodes.status) : undefined,
        present: true,
      }
    }
    return {
      step: 'node',
      label: humanNodeLabel(focusNodeId),
      id: focusNodeId,
      node_type: focusNodeId,
      present: true,
    }
  }, [focusNodeId, nodeSteps, nodes])

  const meta = runMeta && typeof runMeta === 'object' ? runMeta : {}
  const graphHash =
    (typeof trace?.graph?.hash === 'string' && trace.graph.hash) ||
    (typeof meta.graph_hash === 'string' && meta.graph_hash) ||
    (typeof meta.graphHash === 'string' && meta.graphHash) ||
    (typeof (meta.graph as { hash?: string } | undefined)?.hash === 'string'
      ? (meta.graph as { hash: string }).hash
      : '') ||
    ''

  if (loading && !trace) return <LoadingBlock label="Loading lineage…" />
  if (error) return <ErrorBanner message={error} onRetry={() => void load()} />
  if (!trace) {
    return (
      <EmptyState
        title="No lineage for this run"
        description="Node order and artifacts will appear here after the run records them."
      />
    )
  }

  const nodeArts = selectedNode
    ? arts.filter(
        (a) =>
          focusMatchesNode(selectedNode.id, String(a.node_id || '')) ||
          focusMatchesNode(focusNodeId, String(a.node_id || '')),
      )
    : arts

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0 text-[12px] text-ink-600">
          {trace.graph?.name ? (
            <span className="font-medium text-ink-900">{trace.graph.name}</span>
          ) : null}
          {typeof trace.graph?.node_count === 'number' ? (
            <span className="text-ink-500">
              {trace.graph?.name ? ' · ' : ''}
              {trace.graph.node_count} nodes
            </span>
          ) : null}
          {typeof trace.lineage?.artifact_count === 'number' ? (
            <span className="text-ink-500">
              {' · '}
              {trace.lineage.artifact_count} artifacts
            </span>
          ) : null}
          {graphHash ? (
            <span className="ml-2 font-mono text-[11px] text-ink-400" title={graphHash}>
              {graphHash.length > 16 ? `${graphHash.slice(0, 12)}…` : graphHash}
            </span>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <ReproPackButton runId={runId} />
          <button type="button" className="btn-quiet" aria-label="Refresh lineage" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {Array.isArray(trace.warnings) && trace.warnings.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {trace.warnings.map((w) => w.replace(/^[^:]+:/, (m) => m)).join(' · ')}
        </div>
      )}

      {nodeSteps.length === 0 && nodes.length === 0 ? (
        <EmptyState
          title="No node execution recorded"
          description="This run has no node stats or artifacts yet."
        />
      ) : (
        <div className="space-y-3 rounded-xl border border-ink-200 bg-white p-3">
          {contextSteps.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-500">
              <span className="font-semibold uppercase tracking-wide text-ink-400">Context</span>
              {contextSteps.map((step, idx) => {
                const Icon = STEP_ICON[step.step] || Box
                return (
                  <React.Fragment key={`${step.step}-${idx}`}>
                    {idx > 0 && <ArrowRight className="h-3 w-3 text-ink-300" />}
                    <span className="inline-flex items-center gap-1 rounded-full border border-ink-200 bg-white px-2 py-0.5">
                      <Icon className="h-3 w-3" />
                      {step.step}: {step.label}
                    </span>
                  </React.Fragment>
                )
              })}
            </div>
          )}

          {!focusNodeId ? (
            <div className="rounded-xl border border-ink-100 bg-ink-50/60 px-3 py-2.5">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Whole run</div>
              <p className="mt-1 text-sm text-ink-700">
                {nodeSteps.length || nodes.length} nodes executed
                {typeof trace.lineage?.artifact_count === 'number'
                  ? ` · ${trace.lineage.artifact_count} artifacts`
                  : ''}
                . Select a step on the left to inspect node artifacts.
              </p>
              {arts.length > 0 ? (
                <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto">
                  {arts.slice(0, 16).map((a, i) => (
                    <li
                      key={String(a.artifact_id || i)}
                      className="flex items-center justify-between gap-2 text-[12px]"
                    >
                      <span className="truncate text-ink-600">
                        {a.node_id ? `${humanNodeLabel(String(a.node_id))} · ` : ''}
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
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : selectedNode ? (
            <div className="rounded-xl border border-ink-100 bg-ink-50/60 px-3 py-2.5">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Node</div>
              <div className="mt-1 text-sm font-medium text-ink-900">
                {selectedNode.node_type
                  ? humanNodeLabel(String(selectedNode.node_type))
                  : selectedNode.label}
              </div>
              {selectedNode.id ? (
                <div className="mt-1">
                  <CopyableMono value={String(selectedNode.id)} />
                </div>
              ) : null}
              <div className="mt-2 space-y-1">
                {nodeArts.slice(0, 8).map((a) => (
                  <div
                    key={String(a.artifact_id)}
                    className="flex items-center justify-between gap-2 text-[12px]"
                  >
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
                {nodeArts.length === 0 ? (
                  <p className="text-[12px] text-ink-500">
                    No registered artifacts for this node — check Run outputs for downloads.
                  </p>
                ) : null}
              </div>
              {selectedNode.step === 'worker' ? (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <button type="button" className="btn-secondary" onClick={() => goView('workers')}>
                    <Server className="h-3.5 w-3.5" /> Workers
                  </button>
                </div>
              ) : null}
            </div>
          ) : (
            <p className="text-sm text-ink-500">Select a node on the left to inspect lineage.</p>
          )}

          {Array.isArray(trace.lineage?.inputs) && trace.lineage!.inputs!.length > 0 && (
            <div className="rounded-xl border border-ink-100 px-3 py-2">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                Upstream inputs
              </div>
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
        </div>
      )}
    </div>
  )
}
