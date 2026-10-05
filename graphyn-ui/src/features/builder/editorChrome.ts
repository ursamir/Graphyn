/**
 * Editor chrome text helpers (pure — unit-tested in editorChrome.test.ts):
 * node-card summary line, sentence-case headings, the collapsed execution-log
 * bar text. (Catalog default / inspector mode / fit: editorLayout.ts.)
 */
import { prettyArchitecture } from '../runs/runResults'

/** "audio_processing" → "Audio processing"; all-caps acronyms ("ML", "RAG") stay as-is. */
export function sentenceCase(raw: string | null | undefined): string {
  const s = String(raw ?? '')
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim()
  if (!s) return ''
  const words = s.split(' ').map((w, i) => {
    if (w.length > 1 && w === w.toUpperCase() && /[A-Z]/.test(w)) return w // acronym
    const lower = w.toLowerCase()
    return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower
  })
  return words.join(' ')
}

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

function num(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string' && v.trim() && Number.isFinite(Number(v))) return Number(v)
  return null
}

/** Compact number: 0.002 → "0.002", 1e-4 → "1e-4", 0.00030000001 → "0.0003". */
function compactNumber(n: number): string {
  if (n !== 0 && Math.abs(n) < 0.001) {
    const [m, e] = n.toExponential().split('e')
    return `${Number(Number(m).toPrecision(3))}e${Number(e)}`
  }
  return String(Number(n.toPrecision(4)))
}

/** Last path segment, without a trailing slash. */
function baseName(p: string): string {
  const parts = p.replace(/[\\/]+$/, '').split(/[\\/]/)
  return parts[parts.length - 1] || p
}

export type NodeSummaryInput = {
  nodeType: string
  category?: string
  config?: Record<string, unknown> | null
  /** Effective learning rate when another node decides it (Trainer overrides Model builder). */
  learningRate?: number | null
}

/**
 * User-meaningful secondary line for a canvas node: the 1–2 settings a person
 * would recognise ("MobileNet · lr 0.002", "50 epochs · batch 32",
 * "speech_commands"), else the category ("Audio"). Never a field count.
 */
export function nodeSummary(input: NodeSummaryInput, maxBits = 2): string {
  const cfg = input.config ?? {}
  const bits: string[] = []
  const push = (b: string) => {
    if (b && bits.length < maxBits && !bits.includes(b)) bits.push(b)
  }
  const arch = str(cfg.architecture)
  if (arch) push(prettyArchitecture(arch))
  const model = str(cfg.model_name) || str(cfg.model) || str(cfg.model_id)
  if (model && !arch) push(baseName(model))
  const epochs = num(cfg.epochs)
  if (epochs != null) push(`${epochs} epoch${epochs === 1 ? '' : 's'}`)
  const lr = input.learningRate ?? num(cfg.learning_rate ?? cfg.lr)
  if (lr != null) push(`lr ${compactNumber(lr)}`)
  const batch = num(cfg.batch_size)
  if (batch != null && bits.length > 0) push(`batch ${batch}`)
  const sr = num(cfg.sample_rate ?? cfg.target_sample_rate ?? cfg.sr)
  if (sr != null && sr >= 1000) push(`${compactNumber(sr / 1000)} kHz`)
  const fmt = str(cfg.target_format) || str(cfg.format) || str(cfg.export_format)
  if (fmt && fmt.length <= 16) push(fmt)
  for (const k of ['dataset_path', 'input_path', 'path', 'manifest_path', 'source_path', 'dataset']) {
    const p = str(cfg[k])
    if (p) {
      push(baseName(p))
      break
    }
  }
  if (bits.length) return bits.join(' · ')
  return prettyCategory(input.category)
}

/** "ml" → "ML", "audio_processing" → "Audio processing", '' → ''. */
export function prettyCategory(category: string | null | undefined): string {
  const c = str(category)
  if (!c) return ''
  if (/^(ml|ai|io|rag|llm|tinyml|mlops)$/i.test(c)) {
    const lower = c.toLowerCase()
    return lower === 'tinyml' ? 'TinyML' : lower === 'mlops' ? 'MLOps' : c.toUpperCase()
  }
  return sentenceCase(c)
}

export type LogBarInput = {
  isRunning: boolean
  logs: Array<{ message: string; level?: string }>
  /** Server-derived badge for the linked run (e.g. "succeeded", "failed"). */
  runStatus?: string | null
}

/** Text after "Execution log · " on the collapsed log bar. */
export function logBarSummary({ isRunning, logs, runStatus }: LogBarInput): string {
  const last = [...logs].reverse().find((l) => str(l.message))
  const line = last ? str(last.message).replace(/\s+/g, ' ') : ''
  if (isRunning) return line ? `running — ${line}` : 'running…'
  if (line) return line
  const st = str(runStatus)
  if (st && st !== 'loading' && st !== 'unknown' && st !== 'missing') return `last run ${st}`
  return 'idle'
}
