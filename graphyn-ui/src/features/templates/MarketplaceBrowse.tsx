import React from 'react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { stampProjectOnGraph } from '../../lib/projectStamp'
import type { GraphIR } from '../../types/graph'
import { EmptyState, ErrorBanner } from '../../components/ui'
import {
  filterMarketplaceCatalog,
  loadMarketplaceCatalog,
  type MarketplaceCatalogItem,
} from './marketplaceCatalog'

const PACKS = ['Agents', 'Audio', 'Common', 'MLOps', 'RAG', 'TinyML', 'Video', 'Vision', 'WakeWord'] as const
const PAGE_SIZE = 48

/**
 * Console browse over the slim marketplace catalog (public JSON) + materialize via REST.
 * Honesty: needs-api cards stay labelled; no fake device flash.
 */
export function MarketplaceBrowse({
  search,
  onStats,
}: {
  search: string
  /** Report matched / loaded / catalog total so the parent chrome can show honest counts. */
  onStats?: (stats: { matched: number; loaded: number; total: number }) => void
}) {
  const pushToast = useAppStore((s) => s.pushToast)
  const activeProject = useAppStore((s) => s.activeProject)
  const [pack, setPack] = React.useState('')
  const [status, setStatus] = React.useState('')
  const [allMatched, setAllMatched] = React.useState<MarketplaceCatalogItem[] | null>(null)
  const [total, setTotal] = React.useState<number | null>(null)
  const [counts, setCounts] = React.useState<Record<string, number>>({})
  const [page, setPage] = React.useState(0)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [opening, setOpening] = React.useState(false)

  const load = React.useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const doc = await loadMarketplaceCatalog()
      const matched = filterMarketplaceCatalog(doc, { q: search, pack, status })
      setAllMatched(matched)
      setTotal(doc.total_templates)
      setCounts(doc.counts_by_pack)
      setPage(0)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setAllMatched([])
      setTotal(null)
    } finally {
      setBusy(false)
    }
  }, [search, pack, status])

  React.useEffect(() => {
    const tmr = window.setTimeout(() => {
      void load()
    }, 150)
    return () => window.clearTimeout(tmr)
  }, [load])

  const matched = allMatched?.length ?? 0
  const pageCount = Math.max(1, Math.ceil(matched / PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const items = (allMatched ?? []).slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE)
  const loaded = items.length

  React.useEffect(() => {
    if (total == null) return
    onStats?.({ matched, loaded, total })
  }, [matched, loaded, total, onStats])

  const openTemplate = async (templateId: string, st?: string) => {
    if (st === 'needs-api') {
      pushToast(
        'needs-api template — open to inspect Graph IR; device flash/OTA APIs are not faked.',
        'info',
      )
    }
    setOpening(true)
    try {
      const res = await apiJson<{ graph?: GraphIR }>('/pipelines/marketplace/materialize', {
        method: 'POST',
        body: JSON.stringify({ template_id: templateId }),
      })
      if (!res.graph) throw new Error('Materialize returned no graph')
      const stamped = stampProjectOnGraph(res.graph, activeProject || '')
      useAppStore.getState().loadGraphIntoBuilder(stamped)
      pushToast(`Opened marketplace template ${templateId}`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setOpening(false)
    }
  }

  const from = matched === 0 ? 0 : safePage * PAGE_SIZE + 1
  const to = Math.min(matched, safePage * PAGE_SIZE + loaded)

  return (
    <div className="mb-3 space-y-3" data-testid="marketplace-browse">
      <div className="rounded-lg border border-ink-200 bg-ink-50/70 px-3 py-2 text-[11px] leading-snug text-ink-600">
        Marketplace catalog ({total ?? '…'} templates). Filter and page locally —{' '}
        <strong>Open in Editor</strong> materializes Graph IR. Cards marked{' '}
        <span className="font-semibold">needs-api</span> stay honesty-only (no fake MCU flash).
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="field-control w-auto text-[12px]"
          value={pack}
          onChange={(e) => setPack(e.target.value)}
          aria-label="Pack filter"
        >
          <option value="">All packs</option>
          {PACKS.map((p) => (
            <option key={p} value={p}>
              {p}
              {counts[p] != null ? ` (${counts[p]})` : ''}
            </option>
          ))}
        </select>
        <select
          className="field-control w-auto text-[12px]"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          aria-label="Status filter"
        >
          <option value="">Any status</option>
          <option value="seeded">seeded</option>
          <option value="proposed">proposed</option>
          <option value="needs-api">needs-api</option>
          <option value="alter-existing">alter-existing</option>
        </select>
        <span className="text-[11px] text-ink-400">
          {busy
            ? 'Loading…'
            : matched === 0
              ? '0 matched'
              : `Showing ${from}–${to} of ${matched} matched`}
        </span>
        {pageCount > 1 ? (
          <div className="ml-auto flex items-center gap-1.5">
            <button
              type="button"
              className="btn-quiet text-[12px]"
              disabled={busy || safePage <= 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              Previous
            </button>
            <span className="text-[11px] text-ink-500">
              Page {safePage + 1} / {pageCount}
            </span>
            <button
              type="button"
              className="btn-quiet text-[12px]"
              disabled={busy || safePage >= pageCount - 1}
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            >
              Next
            </button>
          </div>
        ) : null}
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      {allMatched && allMatched.length === 0 && !busy ? (
        <EmptyState title="No marketplace matches" description="Try another pack, status, or search term." />
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((tpl) => {
          const id = String(tpl.id ?? '')
          const st = String(tpl.status ?? '')
          const needsApi = st === 'needs-api'
          return (
            <article
              key={id}
              className="flex flex-col rounded-xl border border-ink-200 bg-white p-3 shadow-sm"
              data-testid="marketplace-card"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-ink-950" title={String(tpl.name ?? id)}>
                    {String(tpl.name ?? id)}
                  </div>
                  <div className="mt-0.5 font-mono text-[10px] text-ink-400">{id}</div>
                </div>
                <span
                  className={
                    needsApi
                      ? 'shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-900'
                      : 'shrink-0 rounded-full bg-ink-100 px-2 py-0.5 text-[10px] font-medium text-ink-600'
                  }
                >
                  {st || 'catalog'}
                </span>
              </div>
              <p className="mt-2 line-clamp-2 text-[11px] text-ink-500">
                {String(tpl.value_prop || tpl.description || '')}
              </p>
              <div className="mt-2 flex flex-wrap gap-1">
                {tpl.pack ? (
                  <span className="rounded bg-accent-50 px-1.5 py-0.5 text-[10px] text-accent-800">{tpl.pack}</span>
                ) : null}
                {(tpl.tags ?? []).slice(0, 4).map((tag) => (
                  <span key={tag} className="rounded bg-ink-50 px-1.5 py-0.5 text-[10px] text-ink-500">
                    {tag}
                  </span>
                ))}
              </div>
              {needsApi ? (
                <p
                  className="mt-2 rounded border border-dashed border-amber-200 bg-amber-50/70 px-2 py-1 text-[10px] text-amber-950"
                  data-testid="marketplace-needs-api"
                >
                  needs-api — no live device flash/OTA in this product build.
                </p>
              ) : null}
              <div className="mt-auto flex gap-2 pt-3">
                <button
                  type="button"
                  className="btn-primary"
                  disabled={opening || !id}
                  onClick={() => void openTemplate(id, st)}
                >
                  Open in Editor
                </button>
              </div>
            </article>
          )
        })}
      </div>
      {pageCount > 1 ? (
        <div className="flex justify-center gap-2 pt-1">
          <button
            type="button"
            className="btn-secondary text-[12px]"
            disabled={busy || safePage <= 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            Previous page
          </button>
          <button
            type="button"
            className="btn-secondary text-[12px]"
            disabled={busy || safePage >= pageCount - 1}
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
          >
            Next page
          </button>
        </div>
      ) : null}
    </div>
  )
}
