/**
 * Typed artifact viewer — JSON tree, audio, image, text, model card, binary fallback.
 * No extra npm deps; loads via fetchOutputBlobUrl / text fetch.
 */
import React from 'react'
import { Download, FileJson, Music, Image as ImageIcon, FileText, Box } from 'lucide-react'
import { fetchOutputBlobUrl, downloadOutputFile, apiFetch } from '../api/client'
import { detectFileKind, formatBytes, type FileKind } from '../lib/fileKind'
import { CopyableMono } from './ui'
import clsx from 'clsx'

const TEXT_MAX_BYTES = 3 * 1024 * 1024

type FileViewerProps = {
  path: string
  name?: string
  size?: number
  className?: string
}

function JsonTree({ value, path = '$', depth = 0 }: { value: unknown; path?: string; depth?: number }) {
  const [open, setOpen] = React.useState(depth < 2)
  if (value == null || typeof value !== 'object') {
    return (
      <span className="font-mono text-[11px] text-emerald-200">
        {typeof value === 'string' ? JSON.stringify(value) : String(value)}
      </span>
    )
  }
  const entries = Array.isArray(value)
    ? value.map((v, i) => [String(i), v] as const)
    : Object.entries(value as Record<string, unknown>)
  return (
    <div className={clsx(depth > 0 && 'ml-3 border-l border-ink-700 pl-2')}>
      <button
        type="button"
        className="inline-flex items-center gap-1 font-mono text-[11px] text-accent-300 hover:text-accent-200"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="w-3 text-ink-500">{open ? '▼' : '▶'}</span>
        {Array.isArray(value) ? `Array(${entries.length})` : `Object(${entries.length})`}
      </button>
      {open
        ? entries.map(([k, v]) => (
            <div key={`${path}.${k}`} className="mt-0.5">
              <span className="font-mono text-[11px] text-sky-300">{k}</span>
              <span className="mx-1 text-ink-500">:</span>
              {v != null && typeof v === 'object' ? (
                <JsonTree value={v} path={`${path}.${k}`} depth={depth + 1} />
              ) : (
                <span className="font-mono text-[11px] text-emerald-200">
                  {typeof v === 'string' ? JSON.stringify(v) : String(v)}
                </span>
              )}
            </div>
          ))
        : null}
    </div>
  )
}

export function FileViewer({ path, name, size, className }: FileViewerProps) {
  const kind: FileKind = detectFileKind(name || path)
  const label = name || path.split(/[/\\]/).pop() || path
  const [blobUrl, setBlobUrl] = React.useState<string | null>(null)
  const [text, setText] = React.useState<string | null>(null)
  const [jsonValue, setJsonValue] = React.useState<unknown>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    let createdUrl: string | null = null
    setError(null)
    setBlobUrl(null)
    setText(null)
    setJsonValue(null)
    if (!path.trim()) return

    void (async () => {
      setLoading(true)
      try {
        if (kind === 'image' || kind === 'audio') {
          const url = await fetchOutputBlobUrl(path)
          if (cancelled) {
            URL.revokeObjectURL(url)
            return
          }
          createdUrl = url
          setBlobUrl(url)
          return
        }
        if (kind === 'json' || kind === 'text') {
          const res = await apiFetch('/outputs/file', { query: { path } })
          if (!res.ok) {
            const body = (await res.json().catch(() => ({}))) as { detail?: string }
            throw new Error(body.detail || `HTTP ${res.status}`)
          }
          const buf = await res.arrayBuffer()
          if (buf.byteLength > TEXT_MAX_BYTES) {
            setError(`File is ${(buf.byteLength / (1024 * 1024)).toFixed(1)} MB — download to open (preview capped at 3 MB).`)
            return
          }
          const raw = new TextDecoder().decode(buf)
          if (cancelled) return
          if (kind === 'json') {
            try {
              if (path.toLowerCase().endsWith('.jsonl')) {
                const lines = raw
                  .split('\n')
                  .map((l) => l.trim())
                  .filter(Boolean)
                  .slice(0, 200)
                  .map((l) => JSON.parse(l) as unknown)
                setJsonValue(lines)
                setText(raw.slice(0, 50_000))
              } else {
                setJsonValue(JSON.parse(raw) as unknown)
              }
            } catch {
              setText(raw)
            }
          } else {
            setText(raw)
          }
          return
        }
        // model / binary — no inline payload
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => {
      cancelled = true
      if (createdUrl) URL.revokeObjectURL(createdUrl)
    }
  }, [path, kind])

  const download = () => {
    void downloadOutputFile(path, label)
  }

  return (
    <div className={clsx('flex h-full min-h-[12rem] flex-col rounded-xl border border-ink-200 bg-white', className)}>
      <div className="flex flex-wrap items-center gap-2 border-b border-ink-100 px-3 py-2">
        <KindIcon kind={kind} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-ink-900">{label}</div>
          <div className="truncate font-mono text-[10px] text-ink-400">{path}</div>
        </div>
        {size != null ? (
          <span className="text-[11px] tabular-nums text-ink-500">{formatBytes(size)}</span>
        ) : null}
        <span className="rounded-md bg-ink-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-600">
          {kind}
        </span>
        <button type="button" className="btn-secondary" onClick={download}>
          <Download className="h-3.5 w-3.5" /> Download
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {loading ? <p className="text-sm text-ink-500">Loading preview…</p> : null}
        {error ? <p className="text-sm text-rose-700">{error}</p> : null}
        {!loading && !error && kind === 'image' && blobUrl ? (
          <img src={blobUrl} alt={label} className="max-h-[28rem] w-full rounded-lg border border-ink-100 object-contain bg-ink-50" />
        ) : null}
        {!loading && !error && kind === 'audio' && blobUrl ? (
          <audio controls className="w-full" src={blobUrl}>
            Your browser does not support audio playback.
          </audio>
        ) : null}
        {!loading && !error && kind === 'json' && jsonValue != null ? (
          <div className="rounded-lg bg-ink-950 p-3 text-ink-100">
            <JsonTree value={jsonValue} />
          </div>
        ) : null}
        {!loading && !error && (kind === 'text' || (kind === 'json' && jsonValue == null && text)) && text ? (
          <pre className="max-h-[28rem] overflow-auto rounded-lg bg-ink-950 p-3 font-mono text-[11px] leading-5 text-ink-100 whitespace-pre-wrap">
            {text}
          </pre>
        ) : null}
        {!loading && !error && kind === 'model' ? (
          <div className="rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-3 text-sm text-ink-700">
            <div className="font-medium text-ink-900">Model artifact</div>
            <p className="mt-1 text-xs text-ink-500">
              Keras SavedModel directory or weight file — download or open from disk; no inline graph viewer.
            </p>
            <div className="mt-2">
              <CopyableMono value={path} />
            </div>
          </div>
        ) : null}
        {!loading && !error && kind === 'binary' ? (
          <p className="text-sm text-ink-500">No inline preview for this type — download to open.</p>
        ) : null}
        {!path.trim() ? <p className="text-sm text-ink-500">Select a file to preview.</p> : null}
      </div>
    </div>
  )
}

function KindIcon({ kind }: { kind: FileKind }) {
  const cls = 'h-4 w-4 shrink-0 text-ink-500'
  if (kind === 'json') return <FileJson className={cls} />
  if (kind === 'audio') return <Music className={cls} />
  if (kind === 'image') return <ImageIcon className={cls} />
  if (kind === 'text') return <FileText className={cls} />
  if (kind === 'model') return <Box className={cls} />
  return <FileText className={cls} />
}
