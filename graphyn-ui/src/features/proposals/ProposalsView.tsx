import React from 'react'
import {
  Check,
  ExternalLink,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  X,
} from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import type { GraphIR } from '../../types/graph'
import { emptyGraph } from '../../types/graph'
import {
  CollapsibleJson,
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import { MasterDetail } from '../../layout'
import { formatLocaleDateTime } from '../../lib/format'
import { paths } from '../../routes/paths'
import { navigatePath } from '../../routes/parsePath'
import { onPathChange, readSearchParams } from '../../routes/nav'

/** MCP propose_graph docs — console has no create-proposal form (POST needs full GraphIR). */
const DOCS_MCP_PROPOSE =
  'https://github.com/ursamir/Graphyn/blob/main/docs/MCP_SERVER.md#propose_graph'

const BANNER_DISMISS_KEY = 'graphyn.proposals.bannerDismissed'
const chatKey = (id: string) => `graphyn.proposal.chat.${id}`

type ChatTurn = { role: 'user' | 'assistant'; text: string; at: string }

function readChat(id: string): ChatTurn[] {
  try {
    const raw = localStorage.getItem(chatKey(id))
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? (parsed as ChatTurn[]) : []
  } catch {
    return []
  }
}

function appendChat(id: string, turn: ChatTurn) {
  try {
    const next = [...readChat(id), turn].slice(-50)
    localStorage.setItem(chatKey(id), JSON.stringify(next))
  } catch {
    /* ignore */
  }
}

function pipelineSlugFromSummary(summary?: string): string {
  const base = (summary || 'proposal')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 40)
  return base || 'proposal'
}

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
  /** Optional alias / MCP payload field. */
  graph?: GraphIR
  /** Present when create included a base graph (side-by-side diff). */
  base_graph?: GraphIR
  diff_summary?: DiffSummary
  resolved_by?: string
  reject_reason?: string
  metadata?: Record<string, unknown>
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

function readBannerDismissed(): boolean {
  try {
    const v = localStorage.getItem(BANNER_DISMISS_KEY)
    return v === '1' || v === 'true'
  } catch {
    return false
  }
}

function writeBannerDismissed() {
  try {
    localStorage.setItem(BANNER_DISMISS_KEY, '1')
  } catch {
    /* ignore */
  }
}

function parseProposalsLocation(): { id?: string } {
  const parts = window.location.pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  if (parts[0] === 'agent' && parts[1] === 'inbox' && parts[2]) {
    return { id: decodeURIComponent(parts[2]) }
  }
  const id = (readSearchParams().get('id') || '').trim()
  return id ? { id } : {}
}

export default function ProposalsView() {
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)
  const pushToast = useAppStore((s) => s.pushToast)
  const setPendingProposalCount = useAppStore((s) => s.setPendingProposalCount)
  const activeProject = useAppStore((s) => s.activeProject)

  const [items, setItems] = React.useState<ProposalSummary[] | null>(null)
  const [filter, setFilter] = React.useState<'pending' | 'all' | 'accepted' | 'rejected'>('pending')
  const [search, setSearch] = React.useState('')
  const [selectedId, setSelectedId] = React.useState<string | null>(() => parseProposalsLocation().id ?? null)
  const [detail, setDetail] = React.useState<ProposalDetail | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [detailLoading, setDetailLoading] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [bannerDismissed, setBannerDismissed] = React.useState(() => readBannerDismissed())
  const [generatePrompt, setGeneratePrompt] = React.useState('')
  const [generateBusy, setGenerateBusy] = React.useState(false)
  const [generateOpen, setGenerateOpen] = React.useState(false)
  const [chatTurns, setChatTurns] = React.useState<ChatTurn[]>([])

  const refresh = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const statusQ = filter === 'all' ? '' : `?status=${filter}`
      const data = await apiJson<{ proposals: ProposalSummary[] }>(`/proposals${statusQ}`)
      const list = Array.isArray(data?.proposals) ? data.proposals : []
      setItems(list)
      setSelectedId((prev) => {
        const fromPath = parseProposalsLocation().id
        if (fromPath && list.some((p) => p.id === fromPath)) return fromPath
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
    const apply = () => {
      const id = parseProposalsLocation().id
      if (id) setSelectedId(id)
    }
    return onPathChange(apply)
  }, [])

  React.useEffect(() => {
    const next = selectedId ? paths.proposal(selectedId) : paths.agentInbox()
    const cur = `${window.location.pathname}${window.location.search}`
    if (cur !== next) navigatePath(next, true)
  }, [selectedId])

  React.useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      setChatTurns([])
      return
    }
    setChatTurns(readChat(selectedId))
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

  const visibleItems = React.useMemo(() => {
    if (!items) return []
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter((p) => {
      const blob = [p.id, p.summary ?? '', p.actor ?? '', p.status].join(' ').toLowerCase()
      return blob.includes(q)
    })
  }, [items, search])

  // When search filters out the current selection, snap to first visible (or clear).
  React.useEffect(() => {
    if (!items || loading) return
    if (!selectedId) return
    if (visibleItems.some((p) => p.id === selectedId)) return
    setSelectedId(visibleItems[0]?.id ?? null)
  }, [items, loading, selectedId, visibleItems])

  const dismissBanner = () => {
    writeBannerDismissed()
    setBannerDismissed(true)
  }

  const onGenerate = async () => {
    const prompt = generatePrompt.trim()
    if (!prompt) {
      pushToast('Enter a prompt / summary for the proposal', 'error')
      return
    }
    setGenerateBusy(true)
    try {
      const stub = emptyGraph('agent-proposal')
      const projectTag = activeProject?.trim() || ''
      stub.metadata = {
        ...stub.metadata,
        description: prompt.slice(0, 500),
        tags: [
          ...(stub.metadata.tags || []),
          'agent-inbox',
          ...(projectTag ? [`project:${projectTag}`] : []),
        ],
        ...(projectTag ? { project: projectTag } : {}),
      }
      const summaryParts = [
        prompt.slice(0, 240),
        projectTag ? `[project:${projectTag}]` : null,
      ].filter(Boolean)
      const created = await apiJson<ProposalDetail>('/proposals', {
        method: 'POST',
        body: JSON.stringify({
          summary: summaryParts.join(' ').slice(0, 280),
          graph: stub,
          actor: 'ui-generate',
        }),
      })
      if (created?.id) {
        appendChat(created.id, {
          role: 'user',
          text: prompt,
          at: new Date().toISOString(),
        })
        setSelectedId(created.id)
        setChatTurns(readChat(created.id))
      }
      pushToast('Proposal created — review in the inbox', 'success')
      setGeneratePrompt('')
      setGenerateOpen(false)
      setFilter('pending')
      await refresh()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setGenerateBusy(false)
    }
  }

  const resolveAcceptedGraph = (accepted: ProposalDetail): GraphIR => {
    const graph = accepted.proposed_graph || accepted.graph
    if (!graph || typeof graph !== 'object') {
      throw new Error('Accepted proposal did not include a proposed_graph')
    }
    return graph as GraphIR
  }

  const onAccept = async (andSave: boolean) => {
    if (!detail?.id || busy) return
    setBusy(true)
    try {
      const accepted = await apiJson<ProposalDetail>(`/proposals/${detail.id}/accept`, {
        method: 'POST',
        body: JSON.stringify({ actor: 'ui' }),
      })
      const graph = resolveAcceptedGraph(accepted)
      loadGraphIntoBuilder(graph)
      if (andSave) {
        const project = (activeProject || '').trim()
        if (!project) {
          pushToast('Accepted → Editor. Open a workspace to save as a pipeline.', 'info')
        } else {
          const name = pipelineSlugFromSummary(detail.summary || accepted.summary)
          await apiJson(`/projects/${encodeURIComponent(project)}/pipelines/${encodeURIComponent(name)}`, {
            method: 'PUT',
            body: JSON.stringify(graph),
          })
          pushToast(`Accepted & saved draft ${project}/${name}`, 'success')
        }
      } else {
        pushToast('Applied to Editor — review the graph, then Run', 'success')
      }
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
  const proposedGraph = detail?.proposed_graph || detail?.graph
  const baseGraph = detail?.base_graph
  const showSideBySide = !!(baseGraph && proposedGraph)

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 border-b border-ink-100 px-4 py-4 sm:px-6">
        <PageHeader
          title="Agent inbox"
          description="Generate stub proposals via POST /proposals, or review agent GraphIR from MCP propose_graph."
          actions={
            <>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setGenerateOpen((o) => !o)}
              >
                <Sparkles className="h-3.5 w-3.5" />
                Generate proposal
              </button>
              <button type="button" className="btn-quiet" onClick={() => void refresh()} disabled={loading}>
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            </>
          }
        />
        {generateOpen && (
          <div className="mt-3 space-y-2 rounded-xl border border-ink-200 bg-white p-3">
            <label className="block text-[12px] font-medium text-ink-700">
              Prompt / summary
              <textarea
                className="field-control mt-1 min-h-[4.5rem] w-full text-sm"
                value={generatePrompt}
                onChange={(e) => setGeneratePrompt(e.target.value)}
                placeholder="Describe the graph change (creates a stub GraphIR proposal for review)…"
              />
            </label>
            <p className="text-[11px] text-ink-500">
              Uses <code className="font-mono">POST /api/v1/proposals</code> with an empty-graph stub. Richer
              generation still lives in MCP <code className="font-mono">propose_graph</code> /{' '}
              <code className="font-mono">generate_graph</code>.
              {activeProject ? (
                <>
                  {' '}
                  Will bind to workspace <code className="font-mono">{activeProject}</code>.
                </>
              ) : (
                <> Open a workspace to auto-bind the proposal.</>
              )}
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-primary"
                disabled={generateBusy}
                onClick={() => void onGenerate()}
              >
                {generateBusy ? 'Creating…' : 'Create proposal'}
              </button>
              <button type="button" className="btn-quiet" onClick={() => setGenerateOpen(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
        {!bannerDismissed && (
          <div className="mt-3 flex flex-wrap items-start gap-3 rounded-xl border border-accent-200 bg-accent-50/60 px-3 py-2.5 text-sm text-ink-800">
            <p className="min-w-0 flex-1">
              Agents create proposals via MCP <code className="font-mono text-[12px]">propose_graph</code> or{' '}
              <code className="font-mono text-[12px]">POST /api/v1/proposals</code>; review and accept them here.
            </p>
            <div className="flex shrink-0 items-center gap-2">
              <a
                href={DOCS_MCP_PROPOSE}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[12px] font-medium text-accent-700 hover:text-accent-900"
              >
                <ExternalLink className="h-3 w-3" />
                Docs
              </a>
              <button type="button" className="btn-quiet" onClick={dismissBanner} aria-label="Dismiss banner">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="relative min-w-[12rem] flex-1 sm:max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search actor, summary, id…"
              aria-label="Search proposals"
              className="field-control mt-0 w-full pl-8 text-sm"
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(['pending', 'all', 'accepted', 'rejected'] as const).map((f) => (
              <button
                key={f}
                type="button"
                className={filter === f ? 'catalog-pill catalog-pill-on' : 'catalog-pill'}
                onClick={() => setFilter(f)}
              >
                {f === 'all' ? 'All' : f[0].toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="px-4 pt-3 sm:px-6">
          <ErrorBanner message={error} onRetry={() => void refresh()} />
        </div>
      )}

      <MasterDetail
        className="min-h-0 flex-1"
        masterClassName="!bg-white"
        detailClassName="!p-0"
        master={
        <div className="min-h-0">
          {loading && !items ? (
            <LoadingBlock label="Loading proposals…" />
          ) : !items?.length ? (
            <div className="p-4">
              <EmptyState
                title="No proposals yet"
                description={
                  filter === 'pending'
                    ? 'Generate a stub proposal above, or create via MCP propose_graph / POST /api/v1/proposals. Accept loads GraphIR into the Editor.'
                    : 'Nothing matches this filter.'
                }
                action={
                  filter === 'pending' ? (
                    <button type="button" className="btn-primary inline-flex items-center gap-1" onClick={() => setGenerateOpen(true)}>
                      <Sparkles className="h-3.5 w-3.5" />
                      Generate proposal
                    </button>
                  ) : undefined
                }
              />
            </div>
          ) : visibleItems.length === 0 ? (
            <div className="p-4">
              <EmptyState
                title="No matching proposals"
                description={`Nothing matches “${search.trim()}”. Try another actor, summary, or id.`}
              />
            </div>
          ) : (
            <ul className="divide-y divide-ink-100">
              {visibleItems.map((p) => {
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
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span
                          className="inline-flex max-w-full truncate rounded-md bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-700"
                          title={p.actor || 'unknown'}
                        >
                          {p.actor || 'unknown'}
                        </span>
                        <span className="text-[11px] text-ink-500">{formatLocaleDateTime(p.created_at)}</span>
                      </div>
                      <div className="font-mono text-[10px] text-ink-400">{countLine(p)}</div>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
        }
        detail={
        <section className="min-h-0 px-4 py-4 sm:px-6">
          {!selectedId ? (
            <EmptyState
              title="Select a proposal"
              description="Review the diff summary, then Accept to load into Editor or Reject."
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
                    <h3 className="text-lg font-semibold text-ink-950">{detail.summary || detail.id}</h3>
                    <StatusBadge status={detail.status} />
                  </div>
                  <p className="mt-1 text-sm text-ink-500">
                    Proposed by{' '}
                    <span className="inline-flex items-center rounded-md bg-ink-100 px-1.5 py-0.5 text-[12px] font-medium text-ink-800">
                      {detail.actor || 'unknown'}
                    </span>
                    {detail.created_at ? ` · ${formatLocaleDateTime(detail.created_at)}` : ''}
                    <span className="ml-2 font-mono text-[11px] text-ink-400">{detail.id}</span>
                  </p>
                  {detail.reject_reason ? (
                    <p className="mt-1 text-sm text-rose-700">Rejected: {detail.reject_reason}</p>
                  ) : null}
                </div>
                {detail.status === 'pending' && (
                  <div className="flex flex-col items-end gap-2">
                    <div className="flex flex-wrap justify-end gap-2">
                      <button type="button" className="btn-secondary" onClick={() => void onReject()} disabled={busy}>
                        <X className="h-3.5 w-3.5" />
                        Reject
                      </button>
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => void onAccept(false)}
                        disabled={busy}
                      >
                        <Check className="h-3.5 w-3.5" />
                        Accept → Editor
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => void onAccept(true)}
                        disabled={busy}
                        title={
                          activeProject
                            ? `Save draft under ${activeProject}/${pipelineSlugFromSummary(detail.summary)}`
                            : 'Accept then save requires an open workspace'
                        }
                      >
                        <Save className="h-3.5 w-3.5" />
                        Accept then save…
                      </button>
                    </div>
                    <label
                      className="flex cursor-not-allowed items-center gap-1.5 text-[11px] text-ink-400"
                      title="Partial apply is not supported by the API yet"
                    >
                      <input type="checkbox" checked={false} disabled className="rounded border-ink-300" />
                      Partial apply (coming)
                    </label>
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

              {showSideBySide ? (
                <div className="grid gap-3 lg:grid-cols-2">
                  <CollapsibleJson value={baseGraph} label="Base GraphIR" defaultOpen />
                  <CollapsibleJson value={proposedGraph} label="Proposed GraphIR" defaultOpen />
                </div>
              ) : (
                <CollapsibleJson value={proposedGraph} label="Proposed GraphIR" />
              )}

              {chatTurns.length > 0 ? (
                <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-sm">
                  <h4 className="mb-2 text-sm font-semibold text-ink-900">Chat transcript</h4>
                  <ul className="space-y-2">
                    {chatTurns.map((t, i) => (
                      <li
                        key={`${t.at}-${i}`}
                        className={
                          t.role === 'user'
                            ? 'rounded-lg border border-accent-100 bg-accent-50/60 px-3 py-2 text-[13px] text-ink-800'
                            : 'rounded-lg border border-ink-100 bg-ink-50/80 px-3 py-2 text-[13px] text-ink-700'
                        }
                      >
                        <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                          {t.role} · {formatLocaleDateTime(t.at)}
                        </div>
                        <div className="whitespace-pre-wrap">{t.text}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <CollapsibleJson value={detail} label="Full proposal JSON" />
            </div>
          )}
        </section>
        }
      />
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
