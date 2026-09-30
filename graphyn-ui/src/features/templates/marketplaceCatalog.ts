/** Slim marketplace index served from `public/marketplace-catalog.json` (UI-only browse). */

export type MarketplaceCatalogItem = {
  id?: string
  name?: string
  pack?: string
  status?: string
  description?: string
  value_prop?: string
  tags?: string[]
  industry?: string
  family?: string
}

export type MarketplaceCatalogDoc = {
  total_templates: number
  counts_by_pack: Record<string, number>
  counts_by_status: Record<string, number>
  templates: MarketplaceCatalogItem[]
}

let cached: MarketplaceCatalogDoc | null = null
let inflight: Promise<MarketplaceCatalogDoc> | null = null

export async function loadMarketplaceCatalog(): Promise<MarketplaceCatalogDoc> {
  if (cached) return cached
  if (inflight) return inflight
  inflight = (async () => {
    const res = await fetch('/marketplace-catalog.json', { headers: { Accept: 'application/json' } })
    if (!res.ok) throw new Error(`Marketplace catalog HTTP ${res.status}`)
    const data = (await res.json()) as MarketplaceCatalogDoc
    if (!Array.isArray(data.templates)) throw new Error('Marketplace catalog missing templates[]')
    cached = {
      total_templates: Number(data.total_templates) || data.templates.length,
      counts_by_pack: data.counts_by_pack || {},
      counts_by_status: data.counts_by_status || {},
      templates: data.templates,
    }
    return cached
  })().finally(() => {
    inflight = null
  })
  return inflight
}

export function filterMarketplaceCatalog(
  doc: MarketplaceCatalogDoc,
  opts: { q?: string; pack?: string; status?: string },
): MarketplaceCatalogItem[] {
  const q = (opts.q || '').trim().toLowerCase()
  const pack = (opts.pack || '').trim().toLowerCase()
  const status = (opts.status || '').trim().toLowerCase()
  return doc.templates.filter((t) => {
    if (pack && String(t.pack || '').toLowerCase() !== pack) return false
    if (status && String(t.status || '').toLowerCase() !== status) return false
    if (!q) return true
    const blob = [t.id, t.name, t.description, t.value_prop, ...(t.tags || [])]
      .map((x) => String(x || '').toLowerCase())
      .join(' ')
    return blob.includes(q)
  })
}
