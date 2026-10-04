import { errorMessageFromBody, humanizeErrorText } from '../lib/errorText'

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

/** Actor name configured in Admin → Access (localStorage `graphyn.actor`), or ''. */
export function configuredActor(): string {
  try {
    return localStorage.getItem('graphyn.actor')?.trim() ?? ''
  } catch {
    return ''
  }
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  const token = getApiToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const actor = configuredActor()
  if (actor) headers['X-Actor'] = actor
  return headers
}

function requestId(): string {
  return crypto.randomUUID()
}

export async function parseError(res: Response, path: string): Promise<ApiError> {
  let body: unknown
  let detail = `HTTP ${res.status}`
  // One readable line from any API error shape ({detail}, {detail:{code,message}},
  // {error:{code,message}}, {code,message}, pydantic lists) — never raw JSON.
  let text = ''
  try {
    text = await res.text()
  } catch {
    /* ignore */
  }
  if (text.trim()) {
    try {
      body = JSON.parse(text) as unknown
      detail = errorMessageFromBody(body) || detail
    } catch {
      // Plain-text / HTML error page: keep it short and readable.
      const plain = humanizeErrorText(text.trim())
      detail = /^\s*</.test(plain) ? detail : plain.slice(0, 500)
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

  const userSignal = rest.signal ?? undefined
  let lastErr: unknown
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (userSignal?.aborted) {
      lastErr = new DOMException('Aborted', 'AbortError')
      break
    }
    const controller = new AbortController()
    // Forward caller abort for the whole response lifetime (headers AND body
    // streaming). The listener is intentionally NOT removed once headers
    // arrive: callers reading an NDJSON/SSE body rely on abort() to stop it.
    // `once` + the controller going out of scope keeps this leak-free.
    const onAbort = () => controller.abort()
    userSignal?.addEventListener('abort', onAbort, { once: true })
    // Timeout applies to the headers phase only; long streams must not be cut.
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
      return res
    } catch (err) {
      clearTimeout(timer)
      userSignal?.removeEventListener('abort', onAbort)
      lastErr = err
      // Never retry a request the caller deliberately aborted.
      if (userSignal?.aborted) break
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

/** Authenticated blob URL for a jailed input dataset file (caller must revoke). */
export async function fetchInputBlobUrl(
  filePath: string,
  init?: { signal?: AbortSignal },
): Promise<string> {
  const res = await apiFetch('/data/inputs/file', {
    query: { path: filePath },
    timeoutMs: 120000,
    signal: init?.signal,
  })
  if (!res.ok) throw new ApiError(`Failed to load file (${res.status})`, res.status, filePath)
  return blobUrlWithMime(res, filePath)
}

/** Authenticated blob URL for a jailed output file (caller must revoke). */
export async function fetchOutputBlobUrl(
  filePath: string,
  init?: { signal?: AbortSignal },
): Promise<string> {
  const res = await apiFetch('/outputs/file', {
    query: { path: filePath },
    timeoutMs: 120000,
    signal: init?.signal,
  })
  if (!res.ok) throw await parseError(res, '/outputs/file')
  return blobUrlWithMime(res, filePath)
}

function preferGuessedMime(serverType: string, guessed: string | null): string {
  const server = (serverType || '').split(';')[0].trim().toLowerCase()
  if (!guessed) return server || 'application/octet-stream'
  if (
    !server ||
    server === 'application/octet-stream' ||
    server === 'binary/octet-stream' ||
    server === 'application/force-download' ||
    server === 'application/zip' // mislabeled media
  ) {
    return guessed
  }
  // Extension wins for media when the server type is a different family (e.g. text/html error body).
  const family = (t: string) => t.split('/')[0]
  if (
    (guessed.startsWith('audio/') || guessed.startsWith('video/') || guessed.startsWith('image/')) &&
    family(server) !== family(guessed)
  ) {
    return guessed
  }
  // Normalize common WAV aliases so Chromium can decode blob URLs.
  if (guessed === 'audio/wav' && (server === 'audio/x-wav' || server === 'audio/wave')) {
    return 'audio/wav'
  }
  return server || guessed
}

async function blobUrlWithMime(res: Response, filePath: string): Promise<string> {
  const { guessMimeType } = await import('../lib/fileKind')
  const buf = await res.arrayBuffer()
  if (buf.byteLength === 0) {
    throw new ApiError('Empty file — nothing to preview', res.status, filePath)
  }
  const guessed = guessMimeType(filePath)
  const type = preferGuessedMime(res.headers.get('Content-Type') || '', guessed)
  return URL.createObjectURL(new Blob([buf], { type }))
}

function triggerBlobDownload(url: string, filePath: string, filename?: string): void {
  const a = document.createElement('a')
  a.href = url
  a.download = filename || filePath.split(/[\\/]/).pop() || 'download'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

export async function downloadOutputFile(filePath: string, filename?: string): Promise<void> {
  const url = await fetchOutputBlobUrl(filePath)
  try {
    triggerBlobDownload(url, filePath, filename)
  } finally {
    URL.revokeObjectURL(url)
  }
}

/** Same as downloadOutputFile but for a jailed input dataset file. */
export async function downloadInputFile(filePath: string, filename?: string): Promise<void> {
  const url = await fetchInputBlobUrl(filePath)
  try {
    triggerBlobDownload(url, filePath, filename)
  } finally {
    URL.revokeObjectURL(url)
  }
}
