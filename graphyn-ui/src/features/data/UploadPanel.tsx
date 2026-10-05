import React from 'react'
import { FolderUp, Upload, X } from 'lucide-react'
import clsx from 'clsx'
import { formatBytes } from '../../lib/format'
import {
  DEFAULT_UPLOAD_LIMITS,
  classifyPick,
  planBatches,
  stripPickedRoot,
  uploadBatch,
  type PickVerdict,
  type UploadLimits,
  type UploadResult,
} from './dataApi'

const LABEL_RE = /^[\w-]{1,64}$/
const NEW_LABEL = '__new__'

type RowStatus =
  | { state: 'queued' }
  | { state: 'uploading'; pct: number }
  | { state: 'done'; note?: string }
  | { state: 'skipped'; reason: string }
  | { state: 'error'; message: string }

interface Row {
  file: File
  name: string
  verdict: PickVerdict
  status: RowStatus
}

function relName(file: File): string {
  const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath
  return rel && rel.trim() ? rel : file.name
}

/**
 * Upload files, a folder (webkitdirectory) or zip/tar archives into an existing
 * or new input label. Files go up in batches under the server's per-request
 * caps, with per-file progress; the server unpacks archives, filters types and
 * records sha256 + an audit event per request.
 */
export function UploadPanel({
  labels,
  initialLabel,
  limits = DEFAULT_UPLOAD_LIMITS,
  onDone,
  onClose,
}: {
  labels: string[]
  initialLabel?: string
  limits?: UploadLimits
  onDone: (labels: string[]) => void
  onClose?: () => void
}) {
  const [target, setTarget] = React.useState(() =>
    initialLabel && labels.includes(initialLabel) ? initialLabel : labels.includes('uploads') ? 'uploads' : NEW_LABEL,
  )
  const [newLabel, setNewLabel] = React.useState('')
  const [foldersAsLabels, setFoldersAsLabels] = React.useState(false)
  const [rows, setRows] = React.useState<Row[]>([])
  const [busy, setBusy] = React.useState(false)
  const [summary, setSummary] = React.useState<string | null>(null)
  const abortRef = React.useRef<AbortController | null>(null)
  const fileInput = React.useRef<HTMLInputElement>(null)
  const folderInput = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    // webkitdirectory is not in React's typed attributes.
    folderInput.current?.setAttribute('webkitdirectory', '')
    folderInput.current?.setAttribute('directory', '')
  }, [])
  React.useEffect(() => () => abortRef.current?.abort(), [])

  const label = target === NEW_LABEL ? newLabel.trim() : target
  const labelValid = LABEL_RE.test(label)
  const sendable = rows.filter((r) => r.verdict === 'ok' || r.verdict === 'archive')
  const sendBytes = sendable.reduce((n, r) => n + r.file.size, 0)

  const addFiles = (list: FileList | null) => {
    if (!list || !list.length) return
    setSummary(null)
    const picked = Array.from(list)
    const names = stripPickedRoot(picked.map(relName), foldersAsLabels)
    setRows((prev) => [
      ...prev.filter((r) => r.status.state !== 'done'),
      ...picked.map((file, i) => ({
        file,
        name: names[i],
        verdict: classifyPick({ name: names[i], size: file.size }, limits),
        status: { state: 'queued' } as RowStatus,
      })),
    ])
  }

  const setStatus = (indexes: Set<number>, status: (row: Row) => RowStatus) =>
    setRows((prev) => prev.map((r, i) => (indexes.has(i) ? { ...r, status: status(r) } : r)))

  const start = async () => {
    if (!labelValid || !sendable.length || busy) return
    setBusy(true)
    setSummary(null)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    const queue = rows.map((r, i) => ({ r, i })).filter(({ r }) => r.verdict === 'ok' || r.verdict === 'archive')
    const batches = planBatches(queue.map(({ r }) => ({ name: r.name, size: r.file.size })), limits)
    let stored = 0
    let bytes = 0
    const touched = new Set<string>()
    let failed = 0
    try {
      for (const batch of batches) {
        const items = batch.map((b) => queue[b])
        const idx = new Set(items.map((x) => x.i))
        setStatus(idx, () => ({ state: 'uploading', pct: 0 }))
        try {
          const res: UploadResult = await uploadBatch(
            items.map(({ r }) => ({ file: r.file, name: r.name })),
            { label, foldersAsLabels },
            (loaded, total) => {
              const pct = total ? Math.round((100 * loaded) / total) : 0
              setStatus(idx, () => ({ state: 'uploading', pct }))
            },
            ctrl.signal,
          )
          stored += res.count
          bytes += res.total_bytes
          res.labels.forEach((l) => touched.add(l))
          const skippedBy = new Map(res.skipped.map((s) => [s.name, s.reason]))
          setStatus(idx, (row) => {
            const reason = skippedBy.get(row.name)
            if (reason) return { state: 'skipped', reason }
            if (row.verdict === 'archive') {
              const inner = res.skipped.filter((s) => s.name.startsWith(`${row.name}:`)).length
              return { state: 'done', note: inner ? `unpacked · ${inner} member(s) skipped` : 'unpacked' }
            }
            return { state: 'done' }
          })
        } catch (err) {
          failed += items.length
          const message = err instanceof Error ? err.message : String(err)
          setStatus(idx, () => ({ state: 'error', message }))
          if (ctrl.signal.aborted) break
        }
      }
    } finally {
      abortRef.current = null
      setBusy(false)
    }
    const labelsTouched = [...touched].sort()
    setSummary(
      `Stored ${stored} file${stored === 1 ? '' : 's'} (${formatBytes(bytes)})` +
        (labelsTouched.length ? ` in ${labelsTouched.join(', ')}` : '') +
        (failed ? ` · ${failed} failed` : ''),
    )
    if (stored > 0) onDone(labelsTouched.length ? labelsTouched : [label])
  }

  const statusCell = (r: Row) => {
    if (r.verdict === 'unsupported') return <span className="text-amber-700">type not allowed</span>
    if (r.verdict === 'too_large') return <span className="text-amber-700">over {formatBytes(limits.max_request_bytes)}</span>
    const s = r.status
    if (s.state === 'queued') return <span className="text-ink-400">queued</span>
    if (s.state === 'uploading')
      return (
        <span className="inline-flex items-center gap-1.5">
          <span className="h-1.5 w-16 overflow-hidden rounded bg-ink-100">
            <span className="block h-full bg-accent-600" style={{ width: `${s.pct}%` }} />
          </span>
          <span className="tabular-nums">{s.pct}%</span>
        </span>
      )
    if (s.state === 'done') return <span className="text-emerald-700">{s.note ?? 'stored'}</span>
    if (s.state === 'skipped') return <span className="text-amber-700" title={s.reason}>skipped — {s.reason}</span>
    return <span className="text-red-700" title={s.message}>{s.message}</span>
  }

  return (
    <section className="surface-card space-y-3 p-3" aria-label="Upload files">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Upload into an input label</h3>
        {onClose ? (
          <button type="button" className="btn-icon" aria-label="Close upload" onClick={onClose} disabled={busy}>
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>
      <div className="flex flex-wrap items-end gap-2 text-[12px]">
        <label className="flex flex-col gap-1">
          <span className="text-ink-500">Target label</span>
          <select
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="field-control text-sm"
            disabled={busy}
          >
            {labels.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
            <option value={NEW_LABEL}>New label…</option>
          </select>
        </label>
        {target === NEW_LABEL ? (
          <label className="flex flex-col gap-1">
            <span className="text-ink-500">New label name</span>
            <input
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="e.g. keywords"
              className={clsx('field-control text-sm', newLabel && !labelValid && 'border-red-400')}
              disabled={busy}
              aria-invalid={Boolean(newLabel) && !labelValid}
            />
          </label>
        ) : null}
        <label
          className="flex items-center gap-1.5 pb-1.5"
          title="Off (default): yes/a.wav is stored as <dataset>/yes/a.wav — class folders stay inside the chosen dataset. On: each top-level folder becomes its own dataset (yes/a.wav → dataset “yes”). Applies to folders and zip/tar archives."
        >
          <input
            type="checkbox"
            checked={foldersAsLabels}
            onChange={(e) => setFoldersAsLabels(e.target.checked)}
            disabled={busy}
          />
          Split top folders into separate datasets
        </label>
      </div>
      {target === NEW_LABEL && newLabel && !labelValid ? (
        <p className="text-[11px] text-red-700">Use letters, digits, “_” or “-” (max 64).</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn-secondary" onClick={() => fileInput.current?.click()} disabled={busy}>
          <Upload className="h-3.5 w-3.5" /> Choose files or archives
        </button>
        <button type="button" className="btn-secondary" onClick={() => folderInput.current?.click()} disabled={busy}>
          <FolderUp className="h-3.5 w-3.5" /> Choose folder
        </button>
        <input
          ref={fileInput}
          type="file"
          multiple
          hidden
          accept={[...limits.allowed_extensions, ...limits.archive_extensions].join(',')}
          onChange={(e) => {
            addFiles(e.target.files)
            e.target.value = ''
          }}
        />
        <input
          ref={folderInput}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            addFiles(e.target.files)
            e.target.value = ''
          }}
        />
        <span className="text-[11px] text-ink-500">
          Audio, CSV/TSV, JSON/JSONL, TXT, MD, PDF, PNG/JPG, Parquet; .zip/.tar(.gz) are unpacked. Up to{' '}
          {formatBytes(limits.max_request_bytes)} per request.
        </span>
      </div>
      {rows.length ? (
        <div className="max-h-64 overflow-auto rounded-lg border border-ink-200">
          <table className="w-full text-left text-[11px]">
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.name}-${i}`} className="border-b border-ink-50 last:border-b-0">
                  <td className="max-w-0 truncate px-2 py-1 font-mono" title={r.name}>
                    {r.name}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1 text-right tabular-nums text-ink-500">{formatBytes(r.file.size)}</td>
                  <td className="whitespace-nowrap px-2 py-1">{statusCell(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={busy || !labelValid || sendable.length === 0}
          onClick={() => void start()}
        >
          {busy ? 'Uploading…' : `Upload ${sendable.length} file${sendable.length === 1 ? '' : 's'} (${formatBytes(sendBytes)})`}
        </button>
        {busy ? (
          <button type="button" className="btn-quiet" onClick={() => abortRef.current?.abort()}>
            Cancel
          </button>
        ) : rows.length ? (
          <button type="button" className="btn-quiet" onClick={() => setRows([])}>
            Clear list
          </button>
        ) : null}
        {summary ? <span className="text-[12px] text-ink-600">{summary}</span> : null}
      </div>
    </section>
  )
}
