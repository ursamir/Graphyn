/**
 * Pluggable file viewers for Run outputs / Datasets.
 * Add-ons register via `registerFileViewer` (kind and/or extension).
 */
import type { ComponentType } from 'react'
import type { FileKind } from '../../lib/fileKind'
import { detectFileKind } from '../../lib/fileKind'

export type ViewerSource = 'outputs' | 'inputs'

export type FileViewerProps = {
  path: string
  name: string
  size?: number
  kind: FileKind
  source: ViewerSource
  /** Object URL when the shell already fetched a blob (audio/video/image). */
  blobUrl?: string | null
  text?: string | null
  jsonValue?: unknown
  arrayBuffer?: ArrayBuffer | null
  error?: string | null
  loading?: boolean
}

export type FileViewerPlugin = {
  id: string
  /** Human label shown in the kind badge / popup title. */
  label: string
  kinds?: FileKind[]
  /** Extra extensions (without leading logic) e.g. ['.npz']. */
  extensions?: string[]
  priority?: number
  component: ComponentType<FileViewerProps>
}

const plugins: FileViewerPlugin[] = []

export function registerFileViewer(plugin: FileViewerPlugin): () => void {
  plugins.push(plugin)
  plugins.sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))
  return () => {
    const i = plugins.findIndex((p) => p.id === plugin.id)
    if (i >= 0) plugins.splice(i, 1)
  }
}

export function listFileViewers(): readonly FileViewerPlugin[] {
  return plugins
}

export function resolveFileViewer(path: string, name?: string): FileViewerPlugin | null {
  const label = name || path
  const kind = detectFileKind(label)
  const base = (label.split(/[/\\]/).pop() || '').toLowerCase()
  const ext = base.includes('.') ? base.slice(base.lastIndexOf('.')) : ''
  for (const p of plugins) {
    if (p.extensions?.some((e) => e.toLowerCase() === ext)) return p
    if (p.kinds?.includes(kind)) return p
  }
  return null
}
