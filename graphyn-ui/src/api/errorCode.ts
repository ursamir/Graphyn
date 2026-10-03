import { ApiError } from './client'

/**
 * Machine-readable error code from an API error body. The UX API envelope is
 * `{ error: { code, message, ... }, detail: { code?, ... } }`; older routes put
 * `{ detail: { code } }` only. Returns null when absent.
 */
export function apiErrorCode(err: unknown): string | null {
  const body = err instanceof ApiError ? err.body : (err as { body?: unknown } | null)?.body
  if (!body || typeof body !== 'object') return null
  const b = body as { error?: { code?: unknown }; detail?: { code?: unknown } | unknown }
  if (b.error && typeof b.error.code === 'string') return b.error.code
  const d = b.detail
  if (d && typeof d === 'object' && typeof (d as { code?: unknown }).code === 'string') {
    return (d as { code: string }).code
  }
  return null
}

/** `detail` (or `error`) object of an API error body, for extra fields like `expected`. */
export function apiErrorDetail(err: unknown): Record<string, unknown> | null {
  const body = err instanceof ApiError ? err.body : (err as { body?: unknown } | null)?.body
  if (!body || typeof body !== 'object') return null
  const b = body as { error?: unknown; detail?: unknown }
  if (b.detail && typeof b.detail === 'object' && !Array.isArray(b.detail)) return b.detail as Record<string, unknown>
  if (b.error && typeof b.error === 'object') return b.error as Record<string, unknown>
  return null
}
