/**
 * Workflow features of the Graph IR in the Editor — pure, unit-tested
 * (workflowIr.test.ts):
 *
 *  - per-node `on_error` / `retry` (IR 1.3) ⇄ canvas node data;
 *  - the synthetic `error` output port a node exposes in Route mode;
 *  - branch port captions for if_switch / hitl_approve / error_catch;
 *  - edge `condition` chip text + a light client check that mirrors the
 *    server whitelist (`app/core/execution/conditions.py`);
 *  - run inputs: webhook_trigger bodies + declared IR `parameters` →
 *    `{inputs, parameters}` for POST /pipelines/run{,-async}.
 */
import type { PortDef } from '../../types/graph'

// ── Error handling (IR 1.3) ──────────────────────────────────────────────

export type OnErrorMode = 'fail' | 'continue' | 'route'
export type NodeOnError = { mode: OnErrorMode; port?: string }
export type NodeRetry = {
  max_attempts: number
  backoff_s?: number
  max_backoff_s?: number
  on?: Array<'exception' | 'timeout'>
}

export const ERROR_PORT_DEFAULT = 'error'
const PORT_RE = /^[A-Za-z0-9_-]{1,64}$/

type Rec = Record<string, unknown>
const rec = (v: unknown): Rec | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null)

function clampNum(v: unknown, lo: number, hi: number): number | null {
  const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN
  if (!Number.isFinite(n)) return null
  return Math.min(hi, Math.max(lo, n))
}

/** IR `on_error` → node data (null = default "fail"). */
export function onErrorFromIr(raw: unknown): NodeOnError | null {
  const r = rec(raw)
  if (!r) return null
  const mode = String(r.mode ?? 'fail') as OnErrorMode
  if (mode !== 'continue' && mode !== 'route') return null
  const port = String(r.port ?? '').trim()
  return mode === 'route' ? { mode, port: PORT_RE.test(port) ? port : ERROR_PORT_DEFAULT } : { mode }
}

/** Node data → IR `on_error` (omitted for the default "fail"). */
export function onErrorToIr(v: NodeOnError | null | undefined): { mode: OnErrorMode; port?: string } | null {
  if (!v || v.mode === 'fail') return null
  if (v.mode === 'route') {
    const port = String(v.port ?? '').trim()
    return { mode: 'route', port: PORT_RE.test(port) ? port : ERROR_PORT_DEFAULT }
  }
  return { mode: 'continue' }
}

/** IR `retry` → node data (null = node default policy). */
export function retryFromIr(raw: unknown): NodeRetry | null {
  const r = rec(raw)
  if (!r) return null
  const attempts = clampNum(r.max_attempts, 1, 20)
  if (attempts == null) return null
  const out: NodeRetry = { max_attempts: Math.round(attempts) }
  const b = clampNum(r.backoff_s, 0, 3600)
  if (b != null) out.backoff_s = b
  const mb = clampNum(r.max_backoff_s, 0, 3600)
  if (mb != null) out.max_backoff_s = mb
  const on = Array.isArray(r.on) ? r.on : typeof r.on === 'string' ? [r.on] : null
  if (on) {
    const kinds = on.filter((x): x is 'exception' | 'timeout' => x === 'exception' || x === 'timeout')
    if (kinds.length) out.on = kinds
  }
  return out
}

/** Node data → IR `retry` (omitted when unset). */
export function retryToIr(v: NodeRetry | null | undefined): NodeRetry | null {
  if (!v) return null
  const attempts = clampNum(v.max_attempts, 1, 20)
  if (attempts == null) return null
  const out: NodeRetry = { max_attempts: Math.round(attempts) }
  const b = clampNum(v.backoff_s, 0, 3600)
  if (b != null && b > 0) out.backoff_s = b
  const mb = clampNum(v.max_backoff_s, 0, 3600)
  if (mb != null && mb !== 60) out.max_backoff_s = mb
  if (v.on && v.on.length && !(v.on.length === 1 && v.on[0] === 'exception')) out.on = [...v.on]
  return out
}

/** Routed error port name, or null when the node is not in Route mode. */
export function errorPortOf(v: NodeOnError | null | undefined): string | null {
  return v?.mode === 'route' ? onErrorToIr(v)?.port ?? ERROR_PORT_DEFAULT : null
}

export type CanvasPort = PortDef & { isError?: boolean }

/**
 * Ports a node draws: the catalog outputs, plus the routed `error` port
 * (flagged `isError`) when on_error.mode is route. A catalog port with the
 * same name (error_catch has a native `error` output) is flagged instead of
 * duplicated.
 */
export function outputsWithErrorPort(outputs: PortDef[], onError: NodeOnError | null | undefined): CanvasPort[] {
  const port = errorPortOf(onError)
  const base: CanvasPort[] = outputs.map((p) => ({ ...p }))
  if (!port) return base
  const hit = base.find((p) => p.name === port)
  if (hit) {
    hit.isError = true
    return base
  }
  return [...base, { name: port, data_type: 'error', isError: true }]
}

/** Inspector summary: "Fail run" / "Continue · retry 3×" / "Route to error · retry 2× (5 s)". */
export function errorHandlingSummary(onError: NodeOnError | null | undefined, retry: NodeRetry | null | undefined): string {
  const mode = onError?.mode ?? 'fail'
  const head = mode === 'route' ? 'Route to error branch' : mode === 'continue' ? 'Continue' : 'Fail run'
  if (!retry || retry.max_attempts <= 1) return head
  const wait = retry.backoff_s ? ` (${retry.backoff_s} s back-off)` : ''
  return `${head} · up to ${retry.max_attempts} attempts${wait}`
}

/** Schema version for a canvas graph: 1.3 when any node uses on_error / retry. */
export function irVersionFor(hasPlacement: boolean, hasErrorPolicy: boolean): string {
  if (hasErrorPolicy) return '1.3'
  return hasPlacement ? '1.2' : '1.1'
}

// ── Branch ports ─────────────────────────────────────────────────────────

/** Branch nodes whose output ports get visible captions on the card. */
const BRANCH_TONES: Record<string, Record<string, 'ok' | 'bad' | 'neutral'>> = {
  if_switch: { true: 'ok', false: 'bad', cases: 'neutral', output: 'neutral' },
  hitl_approve: { approved: 'ok', rejected: 'bad' },
  error_catch: { output: 'ok', error: 'bad' },
}

export function isBranchNode(nodeType: string): boolean {
  return Object.prototype.hasOwnProperty.call(BRANCH_TONES, nodeType)
}

export type PortCaption = { name: string; tone: 'ok' | 'bad' | 'neutral' }

/**
 * Captions for a node's output handles: branch nodes always; other nodes only
 * when they show more than one output or a routed error port.
 */
export function portCaptions(nodeType: string, outputs: CanvasPort[]): PortCaption[] | null {
  const tones = BRANCH_TONES[nodeType]
  const showAll = Boolean(tones) || outputs.length > 1
  if (!showAll) return null
  return outputs.map((p) => ({
    name: p.name,
    tone: p.isError ? 'bad' : (tones?.[p.name] ?? 'neutral'),
  }))
}

// ── Edge conditions ──────────────────────────────────────────────────────

export const CONDITION_MAX_LENGTH = 500

/** Window event (detail = edge id) the canvas condition chip fires so the Editor opens the edge inspector. */
export const SELECT_EDGE_EVENT = 'graphyn:select-edge'

export const CONDITION_HELP =
  'Python-style boolean over the source step’s outputs: output["port"] (and output["port"]["key"]), ' +
  'comparisons == != < > <= >=, and / or / not, + - * / %, len(), and string / number / True / False / None literals. ' +
  'Example: len(output["output"]) > 10 and output["score"] >= 0.8'

/** Short chip label for an edge condition (≤ max chars, ellipsis). */
export function conditionChipText(expr: string | null | undefined, max = 28): string {
  const t = String(expr ?? '').replace(/\s+/g, ' ').trim()
  if (!t) return ''
  const compact = t.replace(/output\[("|')([^"']+)\1\]/g, '$2')
  return compact.length > max ? `${compact.slice(0, max - 1)}…` : compact
}

const ALLOWED_NAMES = new Set(['output', 'len', 'and', 'or', 'not', 'True', 'False', 'None'])

/**
 * Light client check mirroring the server whitelist; returns an error
 * message or null. The server (`validate_condition_syntax`) stays the
 * authority — this only catches the obvious mistakes on blur.
 */
export function checkCondition(expr: string | null | undefined): string | null {
  const t = String(expr ?? '').trim()
  if (!t) return null
  if (t.length > CONDITION_MAX_LENGTH) return `Too long (max ${CONDITION_MAX_LENGTH} characters)`
  const stack: string[] = []
  const pairs: Record<string, string> = { ')': '(', ']': '[' }
  let i = 0
  while (i < t.length) {
    const c = t[i]
    if (c === '"' || c === "'") {
      const end = t.indexOf(c, i + 1)
      if (end < 0) return 'Unclosed string'
      i = end + 1
      continue
    }
    if (c === '(' || c === '[') stack.push(c)
    else if (c === ')' || c === ']') {
      if (stack.pop() !== pairs[c]) return `Unbalanced “${c}”`
    } else if (c === '{') return 'Dicts are not allowed'
    else if (c === '=' && t[i + 1] !== '=' && !'!<>='.includes(t[i - 1] ?? '')) return 'Use == to compare (= is assignment)'
    else if (c === ';') return 'Only one expression is allowed'
    else if (/[A-Za-z_]/.test(c)) {
      let j = i
      while (j < t.length && /[A-Za-z0-9_]/.test(t[j])) j++
      const word = t.slice(i, j)
      if (!ALLOWED_NAMES.has(word)) {
        return word === 'lambda' || word === 'import'
          ? `“${word}” is not allowed`
          : `Unknown name “${word}” — only output, len() and literals are allowed`
      }
      if (t[i - 1] === '.') return 'Attribute access is not allowed — use output["key"]'
      i = j
      continue
    } else if (c === '.' && !/[0-9]/.test(t[i + 1] ?? '')) {
      return 'Attribute access is not allowed — use output["key"]'
    }
    i++
  }
  if (stack.length) return 'Unclosed bracket'
  if (/(^|[^=!<>])==?\s*$/.test(t) || /(and|or|not|[<>+\-*/%])\s*$/.test(t)) return 'Expression is incomplete'
  return null
}

// ── Run inputs ───────────────────────────────────────────────────────────

export type RunParamSpec = { name: string; type: string; default: unknown; description: string }
export type RunInputsSpec = {
  webhooks: Array<{ nodeId: string; label: string; sampleBody: unknown }>
  parameters: RunParamSpec[]
}

/** What the Run dialog must ask for (webhook bodies, declared parameters). */
export function runInputsSpec(graph: { nodes?: unknown; parameters?: unknown } | null | undefined): RunInputsSpec {
  const webhooks: RunInputsSpec['webhooks'] = []
  for (const n of Array.isArray(graph?.nodes) ? graph!.nodes : []) {
    const node = rec(n)
    if (!node || node.node_type !== 'webhook_trigger') continue
    const cfg = rec(node.config) || {}
    webhooks.push({
      nodeId: String(node.id ?? ''),
      label: String(node.label ?? '') || String(node.id ?? ''),
      sampleBody: cfg.sample_body ?? {},
    })
  }
  const parameters: RunParamSpec[] = []
  for (const [name, def] of Object.entries(rec(graph?.parameters) || {})) {
    if (name === 'ui') continue
    const d = rec(def)
    if (!d || typeof d.type !== 'string') continue
    parameters.push({ name, type: d.type, default: d.default, description: String(d.description ?? '') })
  }
  return { webhooks, parameters }
}

export function needsRunDialog(spec: RunInputsSpec): boolean {
  return spec.webhooks.length > 0 || spec.parameters.length > 0
}

/** Text shown in a parameter field for its value. */
export function paramText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** Field text → typed value by the IR parameter type; throws on a bad value. */
export function coerceParam(type: string, raw: string): unknown {
  const t = type.trim().toLowerCase()
  const s = raw.trim()
  if (t === 'bool' || t === 'boolean') {
    if (/^(true|1|yes|on)$/i.test(s)) return true
    if (/^(false|0|no|off|)$/i.test(s)) return false
    throw new Error('expected true or false')
  }
  if (t === 'int' || t === 'integer') {
    if (!/^-?\d+$/.test(s)) throw new Error('expected a whole number')
    return Number(s)
  }
  if (t === 'float' || t === 'number') {
    const n = Number(s)
    if (s === '' || !Number.isFinite(n)) throw new Error('expected a number')
    return n
  }
  if (t === 'list' || t === 'array' || t === 'dict' || t === 'object' || t === 'json') {
    try {
      return JSON.parse(s || (t === 'list' || t === 'array' ? '[]' : '{}'))
    } catch {
      throw new Error('expected JSON')
    }
  }
  return raw
}

/**
 * Dialog state → POST body extras. Only parameters the user changed from the
 * declared default are sent; webhook bodies must be valid JSON.
 */
export function buildRunExtras(
  spec: RunInputsSpec,
  bodies: Record<string, string>,
  params: Record<string, string>,
): { extras: { inputs?: Record<string, Record<string, unknown>>; parameters?: Record<string, unknown> }; errors: Record<string, string> } {
  const errors: Record<string, string> = {}
  const inputs: Record<string, Record<string, unknown>> = {}
  for (const w of spec.webhooks) {
    const text = bodies[w.nodeId]
    if (text == null) continue
    try {
      inputs[w.nodeId] = { body: text.trim() ? JSON.parse(text) : {} }
    } catch (err) {
      errors[`body:${w.nodeId}`] = `Invalid JSON: ${err instanceof Error ? err.message : String(err)}`
    }
  }
  const parameters: Record<string, unknown> = {}
  for (const p of spec.parameters) {
    const text = params[p.name]
    if (text == null || text === paramText(p.default)) continue
    try {
      parameters[p.name] = coerceParam(p.type, text)
    } catch (err) {
      errors[`param:${p.name}`] = err instanceof Error ? err.message : String(err)
    }
  }
  const extras: { inputs?: Record<string, Record<string, unknown>>; parameters?: Record<string, unknown> } = {}
  if (Object.keys(inputs).length) extras.inputs = inputs
  if (Object.keys(parameters).length) extras.parameters = parameters
  return { extras, errors }
}
