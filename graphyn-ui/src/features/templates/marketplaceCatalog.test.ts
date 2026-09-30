import { describe, expect, it } from 'vitest'
import { filterMarketplaceCatalog, type MarketplaceCatalogDoc } from './marketplaceCatalog'

const doc: MarketplaceCatalogDoc = {
  total_templates: 3,
  counts_by_pack: { Audio: 2, RAG: 1 },
  counts_by_status: { proposed: 3 },
  templates: [
    { id: 'tpl-a', name: 'Alpha Kws', pack: 'Audio', status: 'proposed', tags: ['kws'] },
    { id: 'tpl-b', name: 'Beta Rag', pack: 'RAG', status: 'needs-api', tags: ['rag'] },
    { id: 'tpl-c', name: 'Gamma Kws', pack: 'Audio', status: 'proposed', tags: ['kws', 'edge'] },
  ],
}

describe('filterMarketplaceCatalog', () => {
  it('filters by pack', () => {
    expect(filterMarketplaceCatalog(doc, { pack: 'Audio' })).toHaveLength(2)
  })

  it('filters by q substring', () => {
    expect(filterMarketplaceCatalog(doc, { q: 'rag' }).map((t) => t.id)).toEqual(['tpl-b'])
  })

  it('filters by status', () => {
    expect(filterMarketplaceCatalog(doc, { status: 'needs-api' })).toHaveLength(1)
  })
})
