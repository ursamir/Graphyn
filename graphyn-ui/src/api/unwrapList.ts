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
