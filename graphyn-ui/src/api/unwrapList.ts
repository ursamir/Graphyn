/**
 * Accept either a bare `T[]` or an API-PAGE-001 list envelope `{ items: T[], ... }`
 * and return `T[]`. Safe during the P1 default-envelope rollout.
 */
export function unwrapList<T = unknown>(raw: unknown): T[] {
  if (Array.isArray(raw)) return raw as T[]
  if (
    raw &&
    typeof raw === 'object' &&
    Array.isArray((raw as { items?: unknown }).items)
  ) {
    return (raw as { items: T[] }).items
  }
  return []
}

/**
 * Walk API-PAGE-001 pages until `next_offset` is null.
 * Bare-array responses are treated as the full list (no further pages).
 * Default page size matches the API max (`le=500`) so one round-trip covers typical catalogs.
 */
export async function fetchAllPages<T = unknown>(
  fetchPage: (offset: number, limit: number) => Promise<unknown>,
  pageSize = 500,
): Promise<T[]> {
  const all: T[] = []
  let offset = 0
  for (let guard = 0; guard < 100; guard++) {
    const raw = await fetchPage(offset, pageSize)
    if (Array.isArray(raw)) return raw as T[]
    const items = unwrapList<T>(raw)
    all.push(...items)
    const next =
      raw && typeof raw === 'object'
        ? (raw as { next_offset?: number | null }).next_offset
        : null
    if (next == null || items.length === 0) break
    offset = next
  }
  return all
}
