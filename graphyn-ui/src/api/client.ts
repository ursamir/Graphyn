const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL

export const API_BASE_URL =
  typeof rawApiBaseUrl === 'string' && rawApiBaseUrl.trim() !== ''
    ? rawApiBaseUrl.replace(/\/+$/, '')
    : '/api/v1'

export const STATIC_BASE_URL = API_BASE_URL.replace(/\/api\/v1\/?$/, '') || ''

const TOKEN_KEY = 'graphyn_api_token'

export type QueryValue = string | number | boolean | null | undefined

export class ApiError extends Error {
  status: number
  path: string
  body: unknown

  constructor(message: string, status: number, path: string, body?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.path = path
    this.body = body
  }
}

export function getApiToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY)?.trim() ?? ''
  } catch {
    return ''
  }
}

export function setApiToken(token: string): void {
  try {
    if (token.trim()) localStorage.setItem(TOKEN_KEY, token.trim())
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

export function apiUrl(path: string, query?: Record<string, QueryValue>): string {
  const normalized = path.startsWith('/') ? path : `/${path}`
  const url = `${API_BASE_URL}${normalized}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

export function staticUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${STATIC_BASE_URL}${normalized}`
}

function authHeaders(): Record<string, string> {
  const token = getApiToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function requestId(): string {
  return crypto.randomUUID()
}

async function parseError(res: Response, path: string): Promise<ApiError> {
  let body: unknown
  let detail = `HTTP ${res.status}`
  try {
    body = await res.json()
    const b = body as Record<string, unknown>
    if (typeof b?.detail === 'string') detail = b.detail
    else if (typeof b?.error === 'string')
      detail = `${b.error}${b.detail ? `: ${String(b.detail)}` : ''}`
    else if (Array.isArray(b?.detail)) detail = JSON.stringify(b.detail)
  } catch {
    try {
      detail = (await res.text()) || detail
    } catch {
      /* ignore */
    }
  }
  if (res.status === 401) detail = `Unauthorized — set API token in Settings. (${detail})`
  return new ApiError(detail, res.status, path, body)
}

export type ApiOptions = RequestInit & {
  query?: Record<string, QueryValue>
  timeoutMs?: number
  retries?: number
  skipAuth?: boolean
}

export async function apiFetch(path: string, init?: ApiOptions): Promise<Response> {
  const { query, timeoutMs = 30000, retries = 0, skipAuth = false, ...rest } = init ?? {}
  const url = apiUrl(path, query)
  const method = (rest.method ?? 'GET').toUpperCase()
  const maxAttempts = method === 'GET' ? Math.max(1, retries + 1) : 1

  let lastErr: unknown
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const controller = new AbortController()
    const userSignal = rest.signal
    const onAbort = () => controller.abort()
    userSignal?.addEventListener('abort', onAbort)
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const res = await fetch(url, {
        ...rest,
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
          'X-Request-ID': requestId(),
          ...(skipAuth ? {} : authHeaders()),
          ...rest.headers,
        },
      })
      clearTimeout(timer)
      userSignal?.removeEventListener('abort', onAbort)
      return res
    } catch (err) {
      clearTimeout(timer)
      userSignal?.removeEventListener('abort', onAbort)
      lastErr = err
      if (attempt < maxAttempts - 1) {
        await new Promise((r) => setTimeout(r, 250 * (attempt + 1)))
        continue
      }
    }
  }
  if (lastErr instanceof DOMException && lastErr.name === 'AbortError') {
    throw new ApiError('Request aborted or timed out', 0, path)
  }
  throw lastErr instanceof Error ? lastErr : new ApiError(String(lastErr), 0, path)
}

export async function apiJson<T>(path: string, init?: ApiOptions): Promise<T> {
  const headers: Record<string, string> = {
    ...(init?.body && !(init.body instanceof FormData)
      ? { 'Content-Type': 'application/json' }
      : {}),
  }
  const res = await apiFetch(path, {
    retries: init?.method && init.method !== 'GET' ? 0 : 2,
    ...init,
    headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
  })
  if (!res.ok) throw await parseError(res, path)
  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

/** Authenticated fetch of a static mount path; returns object URL (caller must revoke). */
export async function fetchAuthenticatedBlobUrl(staticPath: string): Promise<string> {
  const url = staticUrl(staticPath)
  const res = await fetch(url, {
    headers: {
      ...authHeaders(),
      'X-Request-ID': requestId(),
    },
  })
  if (!res.ok) throw new ApiError(`Failed to load file (${res.status})`, res.status, staticPath)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

/** Authenticated blob URL for a jailed output file (caller must revoke). */
export async function fetchOutputBlobUrl(filePath: string): Promise<string> {
  const res = await apiFetch('/outputs/file', { query: { path: filePath }, timeoutMs: 120000 })
  if (!res.ok) throw await parseError(res, '/outputs/file')
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

export async function downloadOutputFile(filePath: string, filename?: string): Promise<void> {
  const url = await fetchOutputBlobUrl(filePath)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename || filePath.split(/[\\/]/).pop() || 'download'
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}
