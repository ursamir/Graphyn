/**
 * Built-in viewers + npy/pickle/model helpers.
 * Third-party addons: `registerFileViewer({...})` from `./registry`.
 */
import React from 'react'
import { Box, FileWarning } from 'lucide-react'
import { CopyableMono } from '../ui'
import { formatBytes, type FileKind } from '../../lib/fileKind'
import { registerFileViewer, type FileViewerProps } from './registry'

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
    <div className={depth > 0 ? 'ml-3 border-l border-ink-700 pl-2' : undefined}>
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

function ImageViewer(props: FileViewerProps) {
  if (!props.blobUrl) return <p className="text-sm text-ink-500">No image preview.</p>
  return (
    <img
      src={props.blobUrl}
      alt={props.name}
      className="max-h-[28rem] w-full rounded-lg border border-ink-100 object-contain bg-ink-50"
    />
  )
}

function AudioViewer(props: FileViewerProps) {
  const [playUrl, setPlayUrl] = React.useState<string | null>(null)
  const [failed, setFailed] = React.useState(false)
  const [converting, setConverting] = React.useState(false)

  React.useEffect(() => {
    let revoked: string | null = null
    let cancelled = false
    setFailed(false)
    setPlayUrl(null)
    if (!props.blobUrl) return

    const sourceUrl = props.blobUrl
    const name = (props.name || props.path || '').toLowerCase()
    const looksWav = name.endsWith('.wav')
    if (!looksWav) {
      setPlayUrl(sourceUrl)
      return
    }

    setConverting(true)
    void (async () => {
      try {
        const { wavBufferToPlayableObjectUrl } = await import('../../lib/wavPlayable')
        const res = await fetch(sourceUrl)
        const buf = await res.arrayBuffer()
        if (cancelled) return
        const converted = wavBufferToPlayableObjectUrl(buf)
        if (converted) {
          revoked = converted
          setPlayUrl(converted)
        } else {
          setPlayUrl(sourceUrl)
        }
      } catch {
        if (!cancelled) setPlayUrl(sourceUrl)
      } finally {
        if (!cancelled) setConverting(false)
      }
    })()

    return () => {
      cancelled = true
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [props.blobUrl, props.name, props.path])

  if (!props.blobUrl) return <p className="text-sm text-ink-500">No audio preview.</p>
  if (converting && !playUrl) return <p className="text-sm text-ink-500">Preparing audio…</p>
  if (!playUrl) return <p className="text-sm text-ink-500">No audio preview.</p>
  return (
    <div className="space-y-2">
      <audio
        key={playUrl}
        controls
        preload="auto"
        className="w-full"
        src={playUrl}
        onError={() => setFailed(true)}
      >
        Your browser does not support audio playback.
      </audio>
      {failed ? (
        <p className="text-[11px] text-rose-700">
          Playback failed — use Download. This file may use an unsupported codec.
        </p>
      ) : (
        <p className="text-[11px] text-ink-400">
          Float32 / wide PCM WAVs are converted for browser playback when possible.
        </p>
      )}
    </div>
  )
}

function VideoViewer(props: FileViewerProps) {
  if (!props.blobUrl) return <p className="text-sm text-ink-500">No video preview.</p>
  return (
    <video controls preload="metadata" className="max-h-[28rem] w-full rounded-lg bg-ink-950" src={props.blobUrl}>
      Your browser does not support video playback.
    </video>
  )
}

function JsonViewer(props: FileViewerProps) {
  if (props.jsonValue != null) {
    return (
      <div className="rounded-lg bg-ink-950 p-3 text-ink-100">
        <JsonTree value={props.jsonValue} />
      </div>
    )
  }
  if (props.text) {
    return (
      <pre className="max-h-[28rem] overflow-auto rounded-lg bg-ink-950 p-3 font-mono text-[11px] leading-5 text-ink-100 whitespace-pre-wrap">
        {props.text}
      </pre>
    )
  }
  return <p className="text-sm text-ink-500">Empty JSON.</p>
}

function TextViewerBody(props: FileViewerProps) {
  if (!props.text) return <p className="text-sm text-ink-500">Empty text.</p>
  return (
    <pre className="max-h-[28rem] overflow-auto rounded-lg bg-ink-950 p-3 font-mono text-[11px] leading-5 text-ink-100 whitespace-pre-wrap">
      {props.text}
    </pre>
  )
}

/** Minimal .npy header parser (v1/v2) — shape + dtype, optional first values. */
function parseNpyHeader(buf: ArrayBuffer): {
  descr: string
  fortran: boolean
  shape: number[]
  dataOffset: number
} | null {
  const u8 = new Uint8Array(buf)
  if (u8.length < 10 || u8[0] !== 0x93 || String.fromCharCode(u8[1], u8[2], u8[3], u8[4], u8[5]) !== 'NUMPY') {
    return null
  }
  const major = u8[6]
  const headerLen = major === 1 ? u8[8] + (u8[9] << 8) : new DataView(buf, 8, 4).getUint32(0, true)
  const headerOffset = major === 1 ? 10 : 12
  const header = new TextDecoder().decode(u8.subarray(headerOffset, headerOffset + headerLen))
  const descr = /'descr'\s*:\s*'([^']+)'/.exec(header)?.[1] || '?'
  const fortran = /'fortran_order'\s*:\s*(True|False)/.exec(header)?.[1] === 'True'
  const shapeMatch = /'shape'\s*:\s*\(([^)]*)\)/.exec(header)
  const shape = (shapeMatch?.[1] || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => Number(s))
    .filter((n) => Number.isFinite(n))
  return { descr, fortran, shape, dataOffset: headerOffset + headerLen }
}

function sampleNpyValues(buf: ArrayBuffer, meta: { descr: string; shape: number[]; dataOffset: number }): string {
  const view = new DataView(buf)
  const n = Math.min(32, meta.shape.reduce((a, b) => a * b, 1) || 0)
  if (!n || meta.dataOffset >= buf.byteLength) return ''
  const vals: string[] = []
  const little = meta.descr.startsWith('<') || meta.descr.startsWith('|')
  const code = meta.descr.replace(/^[<>|=]/, '')
  try {
    for (let i = 0; i < n; i++) {
      const off = meta.dataOffset + i * (code.includes('f8') ? 8 : code.includes('f4') || code.includes('i4') || code.includes('u4') ? 4 : code.includes('f2') || code.includes('i2') ? 2 : 1)
      if (off + 8 > buf.byteLength) break
      if (code.startsWith('f8')) vals.push(String(view.getFloat64(off, little)))
      else if (code.startsWith('f4')) vals.push(String(view.getFloat32(off, little)))
      else if (code.startsWith('i4')) vals.push(String(view.getInt32(off, little)))
      else if (code.startsWith('i2')) vals.push(String(view.getInt16(off, little)))
      else if (code.startsWith('u1') || code === 'b' || code === 'B') vals.push(String(view.getUint8(off)))
      else break
    }
  } catch {
    return ''
  }
  return vals.length ? vals.join(', ') + (n < (meta.shape.reduce((a, b) => a * b, 1) || 0) ? ', …' : '') : ''
}

function NpyViewer(props: FileViewerProps) {
  const meta = props.arrayBuffer ? parseNpyHeader(props.arrayBuffer) : null
  if (!meta) {
    return (
      <div className="rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-3 text-sm text-ink-700">
        <div className="font-medium text-ink-900">NumPy array</div>
        <p className="mt-1 text-xs text-ink-500">Could not parse header — download to open in Python.</p>
        <div className="mt-2">
          <CopyableMono value={props.path} />
        </div>
      </div>
    )
  }
  const sample = props.arrayBuffer ? sampleNpyValues(props.arrayBuffer, meta) : ''
  return (
    <div className="space-y-2 rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-3 text-sm text-ink-700">
      <div className="font-medium text-ink-900">NumPy array (.npy)</div>
      <dl className="grid grid-cols-[7rem_1fr] gap-x-2 gap-y-1 text-xs">
        <dt className="text-ink-400">dtype</dt>
        <dd className="font-mono text-ink-800">{meta.descr}</dd>
        <dt className="text-ink-400">shape</dt>
        <dd className="font-mono text-ink-800">({meta.shape.join(', ')})</dd>
        <dt className="text-ink-400">order</dt>
        <dd className="text-ink-800">{meta.fortran ? 'Fortran' : 'C'}</dd>
        {props.size != null ? (
          <>
            <dt className="text-ink-400">size</dt>
            <dd className="text-ink-800">{formatBytes(props.size)}</dd>
          </>
        ) : null}
      </dl>
      {sample ? (
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">Sample</div>
          <pre className="mt-1 max-h-40 overflow-auto rounded-lg bg-ink-950 p-2 font-mono text-[11px] text-emerald-200">
            [{sample}]
          </pre>
        </div>
      ) : null}
    </div>
  )
}

function PickleViewer(props: FileViewerProps) {
  const head = props.arrayBuffer
    ? Array.from(new Uint8Array(props.arrayBuffer.slice(0, 64)))
        .map((b) => b.toString(16).padStart(2, '0'))
        .join(' ')
    : ''
  return (
    <div className="space-y-2 rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-3 text-sm text-ink-700">
      <div className="flex items-center gap-2 font-medium text-ink-900">
        <FileWarning className="h-4 w-4" /> Pickle binary
      </div>
      <p className="text-xs text-ink-500">
        Pickle is not executed in the browser (unsafe). Download and inspect with Python{' '}
        <code className="font-mono">pickletools.dis</code> or a trusted loader.
      </p>
      {props.size != null ? <p className="text-xs text-ink-500">Size: {formatBytes(props.size)}</p> : null}
      {head ? (
        <pre className="overflow-auto rounded-lg bg-ink-950 p-2 font-mono text-[10px] text-ink-300">{head}</pre>
      ) : null}
      <CopyableMono value={props.path} />
    </div>
  )
}

function ModelViewer(props: FileViewerProps) {
  const base = props.name.toLowerCase()
  const fmt = base.endsWith('.tflite')
    ? 'TFLite'
    : base.endsWith('.keras') || base.endsWith('.h5')
      ? 'Keras'
      : base.endsWith('.onnx')
        ? 'ONNX'
        : base.endsWith('.pt') || base.endsWith('.pth')
          ? 'PyTorch'
          : 'Model'
  return (
    <div className="space-y-2 rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-3 text-sm text-ink-700">
      <div className="flex items-center gap-2 font-medium text-ink-900">
        <Box className="h-4 w-4" /> {fmt} artifact
      </div>
      <p className="text-xs text-ink-500">
        Weights / graph binaries are not rendered inline. Download or open from disk. For trained
        models, packaging and promotion live under Ship / Models.
      </p>
      {props.size != null ? <p className="text-xs text-ink-500">Size: {formatBytes(props.size)}</p> : null}
      <CopyableMono value={props.path} />
    </div>
  )
}

function BinaryViewer(props: FileViewerProps) {
  return (
    <div className="rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-3 text-sm text-ink-700">
      <div className="font-medium text-ink-900">Binary file</div>
      <p className="mt-1 text-xs text-ink-500">No built-in preview for this type — download to open.</p>
      {props.size != null ? <p className="mt-1 text-xs text-ink-500">{formatBytes(props.size)}</p> : null}
      <div className="mt-2">
        <CopyableMono value={props.path} />
      </div>
    </div>
  )
}

let builtinsRegistered = false

/** Register platform built-ins once (safe to call repeatedly). */
export function ensureBuiltinViewers(): void {
  if (builtinsRegistered) return
  builtinsRegistered = true
  const add = (id: string, label: string, kinds: FileKind[], component: React.ComponentType<FileViewerProps>, priority = 0) =>
    registerFileViewer({ id, label, kinds, component, priority })

  add('graphyn.image', 'Image', ['image'], ImageViewer, 10)
  add('graphyn.audio', 'Audio', ['audio'], AudioViewer, 10)
  add('graphyn.video', 'Video', ['video'], VideoViewer, 10)
  add('graphyn.json', 'JSON', ['json'], JsonViewer, 10)
  add('graphyn.text', 'Text', ['text'], TextViewerBody, 10)
  add('graphyn.npy', 'NumPy', ['npy'], NpyViewer, 10)
  add('graphyn.pickle', 'Pickle', ['pickle'], PickleViewer, 10)
  add('graphyn.model', 'Model', ['model'], ModelViewer, 10)
  add('graphyn.binary', 'Binary', ['binary'], BinaryViewer, 0)
}

export { JsonTree }
