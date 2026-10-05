/**
 * Datasets API helpers: upload batching (per-file progress), streamed zip
 * downloads, and the /data/capabilities shape. Pure planning helpers are
 * unit-tested in dataApi.test.ts.
 */
import { apiFetch, apiUrl, getApiToken, parseError } from '../../api/client'

export interface UploadLimits {
  max_request_bytes: number
  max_files: number
  max_extract_bytes: number
  max_archive_files: number
  allowed_extensions: string[]
  archive_extensions: string[]
}

export interface DataCapabilities {
  upload: UploadLimits
  ingest: {
    url: boolean
    huggingface: boolean
    huggingface_reason?: string | null
    huggingface_default_max_rows?: number
  }
}

export const DEFAULT_UPLOAD_LIMITS: UploadLimits = {
  max_request_bytes: 100 * 1024 * 1024,
  max_files: 1000,
  max_extract_bytes: 2 * 1024 ** 3,
  max_archive_files: 20000,
  allowed_extensions: ['.wav', '.mp3', '.m4a', '.ogg', '.webm', '.flac', '.csv', '.tsv', '.json', '.jsonl', '.txt', '.md', '.pdf', '.png', '.jpg', '.jpeg', '.parquet'],
  archive_extensions: ['.zip', '.tar', '.tar.gz', '.tgz'],
}

/** One file picked for upload; `name` may carry a folder path (webkitRelativePath). */
export interface PickedFile {
  name: string
  size: number
}

export type PickVerdict = 'ok' | 'archive' | 'unsupported' | 'too_large'

export function isArchiveName(name: string, limits: UploadLimits = DEFAULT_UPLOAD_LIMITS): boolean {
  const n = name.toLowerCase()
  return limits.archive_extensions.some((ext) => n.endsWith(ext))
}

/** Client-side pre-check; the server re-validates everything. */
export function classifyPick(file: PickedFile, limits: UploadLimits = DEFAULT_UPLOAD_LIMITS): PickVerdict {
  if (file.size > limits.max_request_bytes) return 'too_large'
  if (isArchiveName(file.name, limits)) return 'archive'
  const base = file.name.split('/').pop() ?? file.name
  if (base.startsWith('.')) return 'unsupported'
  const dot = base.lastIndexOf('.')
  const ext = dot >= 0 ? base.slice(dot).toLowerCase() : ''
  return limits.allowed_extensions.includes(ext) ? 'ok' : 'unsupported'
}

/**
 * Group file indexes into upload requests that respect the server's per-request
 * byte and file caps. Callers strip the picked folder once (`stripPickedRoot`)
 * and send `strip_root=false` so each batch keeps those paths as-is.
 */
export function planBatches(
  files: PickedFile[],
  limits: UploadLimits = DEFAULT_UPLOAD_LIMITS,
  maxPerBatch = 100,
): number[][] {
  const byteCap = Math.max(1, Math.floor(limits.max_request_bytes * 0.95))
  const countCap = Math.max(1, Math.min(maxPerBatch, limits.max_files))
  const batches: number[][] = []
  let cur: number[] = []
  let bytes = 0
  files.forEach((f, i) => {
    if (cur.length && (cur.length >= countCap || bytes + f.size > byteCap)) {
      batches.push(cur)
      cur = []
      bytes = 0
    }
    cur.push(i)
    bytes += f.size
  })
  if (cur.length) batches.push(cur)
  return batches
}

/**
 * Drop the folder the user picked (webkitdirectory prefixes every path with it)
 * so batches upload consistent relative paths. With `foldersAsLabels`, a pick
 * of the class folder itself (`yes/a.wav` only) keeps `yes` as the label.
 */
export function stripPickedRoot(names: string[], foldersAsLabels: boolean): string[] {
  const parts = names.map((n) => n.split('/').filter(Boolean))
  if (!parts.length || parts.some((p) => p.length < 2)) return names
  const top = parts[0][0]
  if (parts.some((p) => p[0] !== top)) return names
  if (foldersAsLabels && !parts.some((p) => p.length >= 3)) return names
  return parts.map((p) => p.slice(1).join('/'))
}

export interface UploadResult {
  count: number
  total_bytes: number
  labels: string[]
  content_hash?: string
  files: Array<{ path: string; label: string; size: number; sha256: string }>
  skipped: Array<{ name: string; reason: string }>
}

/** POST /data/inputs/upload with upload progress (XHR — fetch has no upload progress). */
export function uploadBatch(
  entries: Array<{ file: File; name: string }>,
  form: { label: string; foldersAsLabels?: boolean },
  onProgress: (loaded: number, total: number) => void,
  signal?: AbortSignal,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    fd.append('label', form.label)
    if (form.foldersAsLabels !== undefined) fd.append('folders_as_labels', form.foldersAsLabels ? 'true' : 'false')
    // Paths were already stripped client-side (stripPickedRoot); batches must not be re-stripped.
    fd.append('strip_root', 'false')
    for (const e of entries) fd.append('files', e.file, e.name)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', apiUrl('/data/inputs/upload'))
    const token = getApiToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) onProgress(ev.loaded, ev.total)
    }
    xhr.onload = () => {
      let body: unknown = null
      try {
        body = JSON.parse(xhr.responseText || 'null')
      } catch {
        body = xhr.responseText
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as UploadResult)
        return
      }
      const detail =
        body && typeof body === 'object' && 'detail' in (body as Record<string, unknown>)
          ? String((body as Record<string, unknown>).detail)
          : String(body || xhr.statusText)
      reject(new Error(xhr.status === 413 ? `Too large for the server limit — ${detail}` : `Upload failed (${xhr.status}): ${detail}`))
    }
    xhr.onerror = () => reject(new Error('Upload failed: network error'))
    xhr.onabort = () => reject(new Error('Upload cancelled'))
    signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(fd)
  })
}

/** API path of a zip download (input label or output version; `_inputs/<label>` keeps its slash). */
export function zipPath(target: { label: string } | { project: string; version: string }): string {
  if ('label' in target) return `/data/inputs/${encodeURIComponent(target.label)}/zip`
  const project = target.project.split('/').map(encodeURIComponent).join('/')
  return `/data/outputs/${project}/${encodeURIComponent(target.version)}/zip`
}

/**
 * Download a streamed zip. Without an API token the browser follows a plain
 * link (streams to disk, no memory cap); with a token the body is fetched into
 * a Blob because links cannot carry the Authorization header.
 */
export async function downloadZip(path: string, filename: string): Promise<void> {
  const a = document.createElement('a')
  a.download = filename
  if (!getApiToken()) {
    a.href = apiUrl(path)
    document.body.appendChild(a)
    a.click()
    a.remove()
    return
  }
  const res = await apiFetch(path, { timeoutMs: 10 * 60 * 1000 })
  if (!res.ok) throw await parseError(res, path)
  const url = URL.createObjectURL(await res.blob())
  try {
    a.href = url
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 30_000)
  }
}

/** Output project id helpers — frozen inputs are `_inputs/<label>`. */
export const INPUT_SNAPSHOT_PREFIX = '_inputs/'
export function isSnapshotProject(project: string): boolean {
  return project.startsWith(INPUT_SNAPSHOT_PREFIX) && project.split('/').length === 2
}
