/** Classify artifact / output paths for typed viewers (extensible registry). */
export type FileKind =
  | 'json'
  | 'audio'
  | 'video'
  | 'image'
  | 'text'
  | 'model'
  | 'npy'
  | 'pickle'
  | 'binary'

const AUDIO_RE = /\.(wav|mp3|ogg|flac|m4a|aac)$/i
const VIDEO_RE = /\.(mp4|webm|mov|mkv|avi)$/i
const IMAGE_RE = /\.(png|jpe?g|webp|gif|svg|bmp)$/i
const TEXT_RE = /\.(txt|log|csv|md|ya?ml|toml|ini|html?)$/i
const MODEL_RE = /\.(keras|h5|tflite|onnx|pb|pt|pth)$/i
const NPY_RE = /\.(npy|npz|npzz)$/i
const PICKLE_RE = /\.(pkl|pickle)$/i

export function detectFileKind(nameOrPath: string): FileKind {
  const n = nameOrPath.trim().toLowerCase().replace(/\/$/, '')
  const base = n.split(/[/\\]/).pop() || n
  if (base.endsWith('.json') || base.endsWith('.jsonl')) return 'json'
  if (AUDIO_RE.test(base)) return 'audio'
  if (VIDEO_RE.test(base)) return 'video'
  if (IMAGE_RE.test(base)) return 'image'
  if (NPY_RE.test(base)) return 'npy'
  if (PICKLE_RE.test(base)) return 'pickle'
  if (TEXT_RE.test(base)) return 'text'
  if (
    MODEL_RE.test(base) ||
    /(?:^|\/)saved_model$/.test(n) ||
    base === 'saved_model.pb' ||
    base === 'variables.index'
  ) {
    return 'model'
  }
  return 'binary'
}

/** MIME guess for blob URLs when the server sends octet-stream. */
export function guessMimeType(nameOrPath: string): string | null {
  const base = (nameOrPath.split(/[/\\]/).pop() || '').toLowerCase()
  const map: Record<string, string> = {
    '.wav': 'audio/wav',
    '.mp3': 'audio/mpeg',
    '.flac': 'audio/flac',
    '.ogg': 'audio/ogg',
    '.m4a': 'audio/mp4',
    '.aac': 'audio/aac',
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.mov': 'video/quicktime',
    '.mkv': 'video/x-matroska',
    '.avi': 'video/x-msvideo',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
    '.bmp': 'image/bmp',
    '.json': 'application/json',
  }
  const dot = base.lastIndexOf('.')
  if (dot < 0) return null
  return map[base.slice(dot)] || null
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}
