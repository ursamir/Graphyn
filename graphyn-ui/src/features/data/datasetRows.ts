/**
 * Normalize dataset listing payloads into the flat row list the Datasets file
 * table renders (`{ path, split?, label?, size_bytes?, modified_at? }`).
 *
 * `GET /data/outputs/{project}/{version}` changed from a bare row array to a
 * detail object `{ project, version, files, content_hash, created_at, samples }`
 * (DATA-VER-002). Treating that object as an array crashed the whole console
 * (`rows.filter is not a function`). Accept every shape we have seen:
 *   - bare array of rows
 *   - API-PAGE-001 envelope `{ items: [...] }`
 *   - detail object with `samples` (preferred — carries split/label) and/or
 *     `files` (manifest entries `{ path, sha256, size }`, relative to the version dir)
 * Anything else yields `[]`.
 */
export type DatasetRow = Record<string, unknown>

function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v)
}

function recordsOnly(list: unknown[]): DatasetRow[] {
  return list.filter(isRecord)
}

export function normalizeDatasetRows(
  raw: unknown,
  scope?: { project?: string; version?: string },
): DatasetRow[] {
  if (Array.isArray(raw)) return recordsOnly(raw)
  if (!isRecord(raw)) return []
  if (Array.isArray(raw.items)) return recordsOnly(raw.items)

  const project = scope?.project ?? (typeof raw.project === 'string' ? raw.project : '')
  const version = scope?.version ?? (typeof raw.version === 'string' ? raw.version : '')
  const prefix = project && version ? `${project}/${version}/` : ''
  const qualify = (p: string) => (prefix && !p.startsWith(prefix) ? `${prefix}${p.replace(/^\/+/, '')}` : p)

  const files = Array.isArray(raw.files) ? recordsOnly(raw.files) : []
  const sizeByPath = new Map<string, number>()
  for (const f of files) {
    const p = typeof f.path === 'string' ? qualify(f.path) : ''
    const size = typeof f.size === 'number' ? f.size : typeof f.size_bytes === 'number' ? f.size_bytes : null
    if (p && size != null) sizeByPath.set(p, size)
  }

  const samples = Array.isArray(raw.samples) ? recordsOnly(raw.samples) : []
  if (samples.length > 0) {
    return samples.map((s) => {
      const p = typeof s.path === 'string' ? qualify(s.path) : ''
      const size = typeof s.size_bytes === 'number' ? s.size_bytes : sizeByPath.get(p)
      return { ...s, path: p, ...(size != null ? { size_bytes: size } : {}) }
    })
  }
  return files.map((f) => {
    const p = typeof f.path === 'string' ? qualify(f.path) : ''
    const size = typeof f.size === 'number' ? f.size : typeof f.size_bytes === 'number' ? f.size_bytes : undefined
    const out: DatasetRow = { path: p }
    if (size != null) out.size_bytes = size
    if (typeof f.modified_at === 'string') out.modified_at = f.modified_at
    if (typeof f.label === 'string') out.label = f.label
    if (typeof f.split === 'string') out.split = f.split
    return out
  })
}
