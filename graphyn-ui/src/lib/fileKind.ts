/** Classify artifact / output paths for typed viewers. */
export type FileKind =
  | 'json'
  | 'audio'
  | 'image'
  | 'text'
  | 'model'
  | 'binary'

export function detectFileKind(nameOrPath: string): FileKind {
  const n = nameOrPath.trim().toLowerCase().replace(/\/$/, '')
  const base = n.split(/[/\\]/).pop() || n
  if (base.endsWith('.json') || base.endsWith('.jsonl')) return 'json'
  if (/\.(wav|mp3|ogg|flac|m4a|aac)$/.test(base)) return 'audio'
  if (/\.(png|jpe?g|webp|gif|svg)$/.test(base)) return 'image'
  if (/\.(txt|log|csv|md|ya?ml|toml|ini)$/.test(base)) return 'text'
  if (
    /\.(keras|h5|tflite|onnx|pb)$/.test(base) ||
    /(?:^|\/)saved_model$/.test(n) ||
    base === 'saved_model.pb'
  ) {
    return 'model'
  }
  return 'binary'
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}
