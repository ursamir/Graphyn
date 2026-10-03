/**
 * Typed artifact viewer shell — resolves a pluggable viewer by kind/extension.
 * Built-ins: JSON, audio, video, image, text, npy, pickle, model, binary.
 * Add-ons: `registerFileViewer` from `./viewers/registry`.
 */
import React from 'react'
import { Download, Expand, FileJson, Music, Image as ImageIcon, FileText, Box, Film, Binary } from 'lucide-react'
import {
  fetchOutputBlobUrl,
  fetchInputBlobUrl,
  downloadOutputFile,
  downloadInputFile,
  apiFetch,
} from '../api/client'
import { detectFileKind, formatBytes, type FileKind } from '../lib/fileKind'
import clsx from 'clsx'
import { useAppStore } from '../store/appStore'
import { ensureBuiltinViewers } from './viewers/builtins'
import { resolveFileViewer } from './viewers/registry'

const TEXT_MAX_BYTES = 3 * 1024 * 1024
const BINARY_PREVIEW_MAX = 8 * 1024 * 1024

function tooLargeMessage(bytes: number): string {
  return `File is ${(bytes / (1024 * 1024)).toFixed(1)} MB — download to open (preview capped at 3 MB).`
}

type FileViewerProps = {
  path: string
  name?: string
  size?: number
  className?: string
  source?: 'outputs' | 'inputs'
}

ensureBuiltinViewers()

export function FileViewer({ path, name, size, className, source = 'outputs' }: FileViewerProps) {
  const pushToast = useAppStore((s) => s.pushToast)
  const kind: FileKind = detectFileKind(name || path)
  const endpoint = source === 'inputs' ? '/data/inputs/file' : '/outputs/file'
  const fetchBlobUrl = source === 'inputs' ? fetchInputBlobUrl : fetchOutputBlobUrl
  const downloadFile = source === 'inputs' ? downloadInputFile : downloadOutputFile
  const label = name || path.split(/[/\\]/).pop() || path
  const plugin = resolveFileViewer(path, label)
  const [blobUrl, setBlobUrl] = React.useState<string | null>(null)
  const [text, setText] = React.useState<string | null>(null)
  const [jsonValue, setJsonValue] = React.useState<unknown>(null)
  const [arrayBuffer, setArrayBuffer] = React.useState<ArrayBuffer | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [popup, setPopup] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    let createdUrl: string | null = null
    setError(null)
    setBlobUrl(null)
    setText(null)
    setJsonValue(null)
    setArrayBuffer(null)
    if (!path.trim()) return

    void (async () => {
      setLoading(true)
      try {
        if (kind === 'image' || kind === 'audio' || kind === 'video') {
          const url = await fetchBlobUrl(path, { signal: controller.signal })
          if (cancelled) {
            URL.revokeObjectURL(url)
            return
          }
          createdUrl = url
          setBlobUrl(url)
          return
        }
        if (kind === 'json' || kind === 'text') {
          if (size != null && size > TEXT_MAX_BYTES) {
            setError(tooLargeMessage(size))
            return
          }
          const res = await apiFetch(endpoint, { query: { path }, signal: controller.signal })
          if (cancelled) return
          if (!res.ok) {
            const body = (await res.json().catch(() => ({}))) as { detail?: string }
            throw new Error(body.detail || `HTTP ${res.status}`)
          }
          const declared = Number(res.headers.get('Content-Length'))
          if (Number.isFinite(declared) && declared > TEXT_MAX_BYTES) {
            void res.body?.cancel().catch(() => {})
            setError(tooLargeMessage(declared))
            return
          }
          const buf = await res.arrayBuffer()
          if (cancelled) return
          if (buf.byteLength > TEXT_MAX_BYTES) {
            setError(tooLargeMessage(buf.byteLength))
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
        if (kind === 'npy' || kind === 'pickle') {
          if (size != null && size > BINARY_PREVIEW_MAX) {
            setError(`File is ${formatBytes(size)} — download to inspect (preview capped at 8 MB).`)
            return
          }
          const res = await apiFetch(endpoint, { query: { path }, signal: controller.signal })
          if (cancelled) return
          if (!res.ok) {
            const body = (await res.json().catch(() => ({}))) as { detail?: string }
            throw new Error(body.detail || `HTTP ${res.status}`)
          }
          const buf = await res.arrayBuffer()
          if (cancelled) return
          if (buf.byteLength > BINARY_PREVIEW_MAX) {
            setError(`File is ${formatBytes(buf.byteLength)} — download to inspect.`)
            return
          }
          setArrayBuffer(buf)
          return
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => {
      cancelled = true
      controller.abort()
      if (createdUrl) URL.revokeObjectURL(createdUrl)
    }
  }, [path, kind, endpoint, fetchBlobUrl, size])

  const download = () => {
    downloadFile(path, label).catch((err: unknown) => {
      pushToast(`Download failed: ${err instanceof Error ? err.message : String(err)}`, 'error')
    })
  }

  const Viewer = plugin?.component
  const bodyProps = {
    path,
    name: label,
    size,
    kind,
    source,
    blobUrl,
    text,
    jsonValue,
    arrayBuffer,
    error,
    loading,
  }

  const body = (
    <>
      {loading ? <p className="text-sm text-ink-500">Loading preview…</p> : null}
      {error ? <p className="text-sm text-rose-700">{error}</p> : null}
      {!loading && !error && Viewer ? <Viewer {...bodyProps} /> : null}
      {!path.trim() ? <p className="text-sm text-ink-500">Select a file to preview.</p> : null}
    </>
  )

  return (
    <>
      <div className={clsx('flex h-full min-h-[12rem] flex-col rounded-xl border border-ink-200 bg-white', className)}>
        <div className="flex flex-wrap items-center gap-1.5 border-b border-ink-100 px-2.5 py-1.5">
          <KindIcon kind={kind} />
          <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink-900" title={path}>
            {label}
          </span>
          {size != null ? (
            <span className="shrink-0 text-[11px] tabular-nums text-ink-500">{formatBytes(size)}</span>
          ) : null}
          <span className="shrink-0 rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-600">
            {plugin?.label || kind}
          </span>
          <button type="button" className="btn-quiet !px-1.5 !py-1" title="Open larger" onClick={() => setPopup(true)}>
            <Expand className="h-3.5 w-3.5" />
          </button>
          <button type="button" className="btn-quiet !px-1.5 !py-1" title="Download" onClick={download}>
            <Download className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-2.5">{body}</div>
      </div>
      {popup ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-label={`Preview ${label}`}
          onClick={() => setPopup(false)}
        >
          <div
            className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-ink-200 bg-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-2 border-b border-ink-100 px-4 py-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-ink-900">{label}</div>
                <div className="truncate font-mono text-[10px] text-ink-400">{path}</div>
              </div>
              <button type="button" className="btn-secondary" onClick={() => setPopup(false)}>
                Close
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-4">{body}</div>
          </div>
        </div>
      ) : null}
    </>
  )
}

function KindIcon({ kind }: { kind: FileKind }) {
  const cls = 'h-4 w-4 shrink-0 text-ink-500'
  if (kind === 'json') return <FileJson className={cls} />
  if (kind === 'audio') return <Music className={cls} />
  if (kind === 'video') return <Film className={cls} />
  if (kind === 'image') return <ImageIcon className={cls} />
  if (kind === 'text') return <FileText className={cls} />
  if (kind === 'model') return <Box className={cls} />
  if (kind === 'npy' || kind === 'pickle') return <Binary className={cls} />
  return <FileText className={cls} />
}
