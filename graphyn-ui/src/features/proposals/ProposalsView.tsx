import React from 'react'
import {
  Check,
  RefreshCw,
  X,
} from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import type { GraphIR } from '../../types/graph'
import {
  CollapsibleJson,
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { formatLocaleDateTime } from '../../lib/format'

type DiffSummary = {
  nodes_added?: string[]
  nodes_removed?: string[]
  nodes_changed?: Array<{
    id: string
    node_type?: string
    config_keys_before?: string[]
    config_keys_after?: string[]
  }>
  edges_changed?: { added?: string[]; removed?: string[] }
  counts?: {
    nodes_added?: number
    nodes_removed?: number
    nodes_changed?: number
    edges_added?: number
    edges_removed?: number
  }
}

type ProposalSummary = {
  id: string
  status: string
  created_at?: string
  updated_at?: string
  actor?: string
  summary?: string
  base_graph_hash?: string | null
  diff_summary?: {
    nodes_added?: number
    nodes_removed?: number
    nodes_changed?: number
    edges_changed?: number
  }
}

type ProposalDetail = ProposalSummary & {
  proposed_graph?: GraphIR
  diff_summary?: DiffSummary
  resolved_by?: string
  reject_reason?: string
}

function countLine(p: ProposalSummary): string {
  const d = p.diff_summary || {}
  const parts = [
    d.nodes_added ? `+${d.nodes_added} nodes` : null,
    d.nodes_removed ? `−${d.nodes_removed} nodes` : null,
    d.nodes_changed ? `~${d.nodes_changed} nodes` : null,
    d.edges_changed ? `${d.edges_changed} edges` : null,
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : 'No structural diff'
}

export default function ProposalsView() {
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)
  const pushToast = useAppStore((s) => s.pushToast)
  const setPendingProposalCount = useAppStore((s) => s.setPendingProposalCount)

  const [items, setItems] = React.useState<ProposalSummary[] | null>(null)
  const [filter, setFilter] = React.useState<'pending' | 'all' | 'accepted' | 'rejected'>('pending')
  const [selectedId, setSelectedId] = React.useState<string | null>(null)
  const [detail, setDetail] = React.useState<ProposalDetail | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [detailLoading, setDetailLoading] = React.useState(false)
  const [busy, setBusy] = React.useState(false)

  const refresh = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const statusQ = filter === 'all' ? '' : `?status=${filter}`
      const data = await apiJson<{ proposals: ProposalSummary[] }>(`/proposals${statusQ}`)
      const list = Array.isArray(data?.proposals) ? data.proposals : []
      setItems(list)
      setSelectedId((prev) => {
        if (prev && list.some((p) => p.id === prev)) return prev
        return list[0]?.id ?? null
      })
      const pendingPayload = await apiJson<{ proposals: ProposalSummary[] }>('/proposals?status=pending')
      const pendingCount = Array.isArray(pendingPayload?.proposals) ? pendingPayload.proposals.length : 0
      setPendingProposalCount(pendingCount)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      pushToast(msg, 'error')
    } finally {
      setLoading(false)
    }
  }, [filter, pushToast, setPendingProposalCount])

  React.useEffect(() => {
    void refresh()
  }, [refresh])

  React.useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    let cancelled = false
    setDetailLoading(true)
    void (async () => {
      try {
        const data = await apiJson<ProposalDetail>(`/proposals/${selectedId}`)
        if (!cancelled) setDetail(data)
      } catch (err) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : String(err)
          setError(msg)
          setDetail(null)
        }
      } finally {
        if (!cancelled) setDetailLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedId])

  const onAccept = async () => {
    if (!detail?.id || busy) return
    setBusy(true)
    try {
      const accepted = await apiJson<ProposalDetail>(`/proposals/${detail.id}/accept`, {
        method: 'POST',
        body: JSON.stringify({ actor: 'ui' }),
      })
      const graph = accepted.proposed_graph
      if (!graph || typeof graph !== 'object') {
        throw new Error('Accepted proposal did not include a proposed_graph')
      }
      pushToast('Proposal accepted — opening Builder', 'success')
      loadGraphIntoBuilder(graph as GraphIR)
      void refresh()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  const onReject = async () => {
    if (!detail?.id || busy) return
    setBusy(true)
    try {
      await apiJson(`/proposals/${detail.id}/reject`, {
        method: 'POST',
        body: JSON.stringify({ actor: 'ui' }),
      })
      pushToast('Proposal rejected', 'info')
      void refresh()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  const diff = detail?.diff_summary

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 border-b border-ink-100 px-4 py-4 sm:px-6">
        <PageHeader
          title="Proposals"
          description="Agents propose GraphIR changes; you approve before they enter Builder. Secrets never belong in IR."
          actions={
            <>
              <div className="flex rounded-lg border border-ink-200 bg-white p-0.5 text-[12px]">
                {(['pending', 'all', 'accepted', 'rejected'] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    className={
                      filter === f
                        ? 'rounded-md bg-ink-900 px-2.5 py-1 font-medium text-white'
                        : 'rounded-md px-2.5 py-1 text-ink-600 hover:bg-ink-50'
                    }
                    onClick={() => setFilter(f)}
                  >
                    {f === 'all' ? 'All' : f[0].toUpperCase() + f.slice(1)}
                  </button>
                ))}
              </div>
              <button type="button" className="btn-secondary" onClick={() => void refresh()} disabled={loading}>
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            </>
          }
        />
      </div>

      {error && (
        <div className="px-4 pt-3 sm:px-6">
          <ErrorBanner message={error} onRetry={() => void refresh()} />
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(16rem,22rem)_1fr]">
        <aside className="min-h-0 overflow-y-auto border-b border-ink-100 lg:border-b-0 lg:border-r">
          {loading && !items ? (
            <LoadingBlock label="Loading proposals…" />
          ) : !items?.length ? (
            <div className="p-4">
              <EmptyState
                title="No proposals"
                description={
                  filter === 'pending'
                    ? 'Agents can submit GraphIR via MCP propose_graph or POST /api/v1/proposals.'
                    : 'Nothing matches this filter.'
                }
              />
            </div>
          ) : (
            <ul className="divide-y divide-ink-100">
              {items.map((p) => {
                const active = p.id === selectedId
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(p.id)}
                      className={
                        active
                          ? 'flex w-full flex-col gap-1 bg-white px-4 py-3 text-left ring-1 ring-inset ring-accent-300'
                          : 'flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-white/80'
                      }
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-[13px] font-medium text-ink-950">
                          {p.summary || p.id}
                        </span>
                        <StatusBadge status={p.status} />
                      </div>
                      <div className="text-[11px] text-ink-500">
                        {p.actor || 'unknown'} · {formatLocaleDateTime(p.created_at)}
                      </div>
                      <div className="font-mono text-[10px] text-ink-400">{countLine(p)}</div>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </aside>

        <section className="min-h-0 overflow-y-auto px-4 py-4 sm:px-6">
          {!selectedId ? (
            <EmptyState
              title="Select a proposal"
              description="Review the diff summary, then Accept to load into Builder or Reject."
            />
          ) : detailLoading && !detail ? (
            <LoadingBlock label="Loading proposal…" />
          ) : !detail ? (
            <EmptyState title="Proposal not found" description="It may have been removed." />
          ) : (
            <div className="mx-auto max-w-3xl space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-lg font-semibold text-ink-950">{detail.summary}</h3>
                    <StatusBadge status={detail.status} />
                  </div>
                  <p className="mt-1 text-sm text-ink-500">
                    Proposed by <span className="font-medium text-ink-700">{detail.actor || 'unknown'}</span>
                    {detail.created_at ? ` · ${formatLocaleDateTime(detail.created_at)}` : ''}
                    <span className="ml-2 font-mono text-[11px] text-ink-400">{detail.id}</span>
                  </p>
                </div>
                {detail.status === 'pending' && (
                  <div className="flex gap-2">
                    <button type="button" className="btn-secondary" onClick={() => void onReject()} disabled={busy}>
                      <X className="h-3.5 w-3.5" />
                      Reject
                    </button>
                    <button type="button" className="btn-primary" onClick={() => void onAccept()} disabled={busy}>
                      <Check className="h-3.5 w-3.5" />
                      Accept → Builder
                    </button>
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-sm">
                <h4 className="mb-2 text-sm font-semibold text-ink-900">Diff summary</h4>
                {!diff ? (
                  <p className="text-sm text-ink-500">No diff available.</p>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <DiffList title="Nodes added" items={diff.nodes_added} empty="None" tone="add" />
                    <DiffList title="Nodes removed" items={diff.nodes_removed} empty="None" tone="remove" />
                    <div className="sm:col-span-2">
                      <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-ink-400">
                        Nodes changed
                      </div>
                      {!diff.nodes_changed?.length ? (
                        <p className="text-sm text-ink-500">None</p>
                      ) : (
                        <ul className="space-y-1.5">
                          {diff.nodes_changed.map((n) => (
                            <li
                              key={n.id}
                              className="rounded-lg border border-ink-100 bg-ink-50/80 px-2.5 py-1.5 text-[12px]"
                            >
                              <span className="font-mono font-medium text-ink-900">{n.id}</span>
                              {n.node_type ? (
                                <span className="ml-2 text-ink-500">{n.node_type}</span>
                              ) : null}
                              <div className="mt-0.5 font-mono text-[10px] text-ink-400">
                                config: {(n.config_keys_before || []).join(', ') || '∅'} →{' '}
                                {(n.config_keys_after || []).join(', ') || '∅'}
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <DiffList
                      title="Edges added"
                      items={diff.edges_changed?.added}
                      empty="None"
                      tone="add"
                    />
                    <DiffList
                      title="Edges removed"
                      items={diff.edges_changed?.removed}
                      empty="None"
                      tone="remove"
                    />
                  </div>
                )}
              </div>

              {detail.base_graph_hash && (
                <p className="font-mono text-[11px] text-ink-400">
                  base_graph_hash: {detail.base_graph_hash}
                </p>
              )}

              <CollapsibleJson value={detail.proposed_graph} label="Proposed GraphIR" />
              <CollapsibleJson value={detail} label="Full proposal JSON" />
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function DiffList({
  title,
  items,
  empty,
  tone,
}: {
  title: string
  items?: string[]
  empty: string
  tone: 'add' | 'remove'
}) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-ink-400">{title}</div>
      {!items?.length ? (
        <p className="text-sm text-ink-500">{empty}</p>
      ) : (
        <ul className="space-y-1">
          {items.map((id) => (
            <li
              key={id}
              className={
                tone === 'add'
                  ? 'rounded-md bg-emerald-50 px-2 py-1 font-mono text-[12px] text-emerald-900'
                  : 'rounded-md bg-rose-50 px-2 py-1 font-mono text-[12px] text-rose-900'
              }
            >
              {id}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
