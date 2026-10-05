import { Handle, Position, type NodeProps } from 'reactflow'
import clsx from 'clsx'
import type { NodePlacement, PortDef } from '../../types/graph'
import { AudioLines, Box, Brain, Copy, GitBranch, Pencil, Sparkles, X, Zap } from 'lucide-react'
import { schemaFieldHint } from '../../lib/format'
import { progressBadgeText, type NodeProgress } from '../runs/runProgress'
import { numberInputAttrs } from './configValidation'
import { nodeSummary } from './editorChrome'
import { AugmentationsEditor } from './AugmentationsEditor'
import { LayersEditor } from './LayersEditor'
import { SplitRatiosEditor } from './SplitRatiosEditor'
import { StringListEditor } from './StringListEditor'
import { outputsWithErrorPort, portCaptions, type NodeOnError, type NodeRetry } from './workflowIr'

export type GraphynNodeData = {
  nodeType: string
  label: string
  category?: string
  config: Record<string, unknown>
  schemaProps?: Record<string, Record<string, unknown>>
  /** IR 1.2+ placement (Mode B). */
  placement?: NodePlacement | null
  /** IR 1.3 failure policy (null = fail the run). Route adds a red `error` output handle. */
  onError?: NodeOnError | null
  /** IR 1.3 retry policy (null = node default). */
  retry?: NodeRetry | null
  /** Opaque IR fields the Builder doesn't edit yet — preserved verbatim through load/save. */
  capabilityMetadata?: unknown
  eventTrigger?: unknown
  inputs: PortDef[]
  outputs: PortDef[]
  status?: 'idle' | 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'cancelled' | 'success' | 'error'
  /** Last execution error snippet when status is failed */
  lastError?: string
  runtime?: string
  /** True once catalog data (category / schema / ports) has been applied (see builderRunState.decorateNodeData). */
  catalogDecorated?: boolean
  /** View-only: number of invalid config fields (schema bounds etc.); never saved. */
  configIssues?: number
  /** View-only: parallel branch this node sits on (fork graphs); never saved. */
  pathBadge?: { letter: string; description: string } | null
  /** View-only: label disambiguated by path ("Trainer · Path B"); never saved. */
  displayLabel?: string
  /** View-only: title line when several unlabeled nodes share a type (the node id); never saved. */
  displayTitle?: string
  /** View-only: secondary type text under `displayTitle` ("Set / Map"); never saved. */
  displaySubtitle?: string
  /** View-only: learning rate training actually uses when another node decides it (Trainer wins over Model builder). */
  effectiveLr?: number | null
  /** View-only: latest node_progress while running; never saved. */
  progress?: NodeProgress | null
  onChangeConfig?: (key: string, value: unknown) => void
  onChangePlacement?: (next: NodePlacement | null) => void
  onChangeErrorPolicy?: (next: { onError: NodeOnError | null; retry: NodeRetry | null }) => void
  onDelete?: () => void
  onDuplicate?: () => void
  onValidateConfig?: () => void
  onOpenInspector?: () => void
}

function unwrapSchema(def: Record<string, unknown>): Record<string, unknown> {
  if (def.enum || def.type) return def
  const anyOf = def.anyOf as Record<string, unknown>[] | undefined
  if (!Array.isArray(anyOf)) return def
  const useful = anyOf.find((x) => x && x.type !== 'null')
  if (!useful) return def
  return { ...def, ...useful }
}

function schemaType(def: Record<string, unknown>): string {
  const t = unwrapSchema(def).type
  if (Array.isArray(t)) {
    const nonNull = t.find((x) => x !== 'null')
    return String(nonNull ?? 'string')
  }
  return String(t ?? 'string')
}

function isObjectSchema(def: Record<string, unknown>): boolean {
  const t = def.type
  if (t === 'object') return true
  if (Array.isArray(t) && t.includes('object')) return true
  if (t === 'array') {
    const items = def.items as Record<string, unknown> | undefined
    if (items && (items.type === 'object' || items.type === undefined)) return true
  }
  return false
}

function formatValue(def: Record<string, unknown>, value: unknown): string {
  if (value == null) return ''
  const type = schemaType(def)
  if (type === 'object' || isObjectSchema(def) || (type === 'array' && typeof value === 'object')) {
    try {
      return JSON.stringify(value, null, 0)
    } catch {
      return ''
    }
  }
  if (Array.isArray(value) && type === 'array') {
    if (value.every((v) => typeof v !== 'object' || v == null)) return value.join(',')
    return JSON.stringify(value)
  }
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function isNullableSchema(def: Record<string, unknown>): boolean {
  const t = def.type
  if (Array.isArray(t) && t.includes('null')) return true
  const anyOf = def.anyOf as Record<string, unknown>[] | undefined
  if (Array.isArray(anyOf) && anyOf.some((x) => x && x.type === 'null')) return true
  if (def.default === null || def.default === undefined) {
    // Optional ints/numbers often omit default in overlay; treat empty as null when title/desc imply optional device
    return false
  }
  return false
}

function parseValue(def: Record<string, unknown>, raw: string): unknown {
  const type = schemaType(def)
  if (type === 'number' || type === 'integer') {
    if (raw === '') return isNullableSchema(def) ? null : type === 'integer' ? 0 : 0
    return Number(raw)
  }
  if (type === 'boolean') return raw === 'true'
  if (type === 'object' || isObjectSchema(def)) {
    if (!raw.trim()) return type === 'array' ? [] : {}
    return JSON.parse(raw)
  }
  if (type === 'array') {
    const trimmed = raw.trim()
    if (!trimmed) return []
    if (trimmed.startsWith('[')) return JSON.parse(trimmed)
    return trimmed.split(',').map((s) => s.trim()).filter(Boolean)
  }
  return raw
}

/** String config keys that look secret-like (prefer connection_id / Credentials). */
export function isSecretLikeConfigKey(key: string, title?: string): boolean {
  const hay = `${key} ${title || ''}`.toLowerCase()
  if (/timeout|retries?|max_|min_|count|length|status|path|dir|file|url_path/.test(hay)) {
    return false
  }
  return /secret|credential|password|token|api[_-]?key/.test(hay)
}

export type CredentialOption = { id: string; name: string; kind: string; is_default?: boolean }

export function ConfigFieldEditor(props: {
  fieldKey: string
  def: Record<string, unknown>
  value: unknown
  onChange: (v: unknown) => void
  /** Platform credential connections from GET /credentials (redacted). */
  credentials?: CredentialOption[]
  /** Value fails schema validation — red border + aria-invalid. */
  invalid?: boolean
}) {
  return fieldEditor(
    props.fieldKey,
    props.def,
    props.value,
    props.onChange,
    props.credentials,
    props.invalid,
  )
}

function isConnectionIdField(key: string, title: string): boolean {
  const hay = `${key} ${title}`.toLowerCase()
  return key === 'connection_id' || /credential connection id|connection id/.test(hay)
}

function CredentialConnectionSelect({
  credentials,
  value,
  onPick,
}: {
  credentials: CredentialOption[]
  value: unknown
  onPick: (id: string) => void
}) {
  const current = String(value ?? '')
  const ids = credentials.map((c) => c.id)
  return (
    <select
      className="field-control mt-1"
      value={ids.includes(current) ? current : ''}
      title="Bind a platform credential connection (Admin → Credentials). Empty → workspace default → env."
      data-testid="connection-id-picker"
      onChange={(e) => onPick(e.target.value)}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <option value="">Default / env bootstrap…</option>
      {credentials.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name} ({c.kind}){c.is_default ? ' · default' : ''} — {c.id.slice(0, 8)}…
        </option>
      ))}
    </select>
  )
}

function fieldEditor(
  key: string,
  def: Record<string, unknown>,
  value: unknown,
  onChange: (v: unknown) => void,
  credentials?: CredentialOption[],
  invalid?: boolean,
) {
  const type = schemaType(def)
  const invalidCls = invalid ? ' !border-rose-400 bg-rose-50/60' : ''
  if (type === 'boolean') {
    return (
      <label className="mt-1 inline-flex items-center gap-2 text-[12px] text-ink-700">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 rounded border-ink-300"
          checked={Boolean(value)}
          title={schemaFieldHint(def)}
          onChange={(e) => onChange(e.target.checked)}
          onMouseDown={(e) => e.stopPropagation()}
        />
        <span className="text-ink-500">{value ? 'On' : 'Off'}</span>
      </label>
    )
  }
  if (Array.isArray(unwrapSchema(def).enum)) {
    return (
      <select
        className={`field-control${invalidCls}`}
        aria-invalid={invalid || undefined}
        value={String(value ?? '')}
        title={schemaFieldHint(def)}
        onChange={(e) => onChange(e.target.value)}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {((unwrapSchema(def).enum as unknown[]) ?? []).map((opt) => (
          <option key={String(opt)} value={String(opt)}>
            {String(opt)}
          </option>
        ))}
      </select>
    )
  }

  const widget = String(unwrapSchema(def).widget ?? '')
  const title = String(unwrapSchema(def).title ?? '')
  const secretLike =
    type === 'string' &&
    (widget === 'password' || widget === 'secret' || isSecretLikeConfigKey(key, title))
  const secretHint = secretLike ? (
    <p className="mt-1 text-[10px] leading-snug text-ink-400">
      Prefer Admin → Credentials (<span className="font-mono">connection_id</span>). Env bootstrap
      resolves at runtime — never paste keys into Graph IR.
    </p>
  ) : null

  if (isConnectionIdField(key, title) && credentials && credentials.length > 0) {
    return (
      <div>
        <input
          type="text"
          className="field-control font-mono text-[11px]"
          value={formatValue(def, value)}
          placeholder="connection id (or pick below)"
          title={schemaFieldHint(def)}
          onChange={(e) => onChange(e.target.value)}
          onMouseDown={(e) => e.stopPropagation()}
        />
        <CredentialConnectionSelect
          credentials={credentials}
          value={value}
          onPick={(id) => onChange(id)}
        />
        <p className="mt-1 text-[10px] leading-snug text-ink-400">
          Stores connection id only — never the secret. Create connections under Admin → Credentials.
        </p>
      </div>
    )
  }

  // Structured Job-A editors for known widget=json shapes; others keep the textarea.
  if (key === 'layers' && (widget === 'json' || type === 'array' || Array.isArray(value))) {
    return <LayersEditor value={value} onChange={onChange} invalid={invalid} />
  }
  if (key === 'augmentations' && (widget === 'json' || type === 'array' || Array.isArray(value))) {
    return <AugmentationsEditor value={value} onChange={onChange} invalid={invalid} />
  }
  if (key === 'split_ratios' && (widget === 'json' || type === 'object' || (value != null && typeof value === 'object' && !Array.isArray(value)))) {
    return <SplitRatiosEditor value={value} onChange={onChange} invalid={invalid} />
  }
  if (key === 'allowed_paths' && (widget === 'json' || type === 'array' || Array.isArray(value))) {
    return <StringListEditor value={value} onChange={onChange} invalid={invalid} placeholder="path or glob" />
  }

  if (widget === 'textarea' || widget === 'json') {
    return (
      <div className="code-field">
        <span className="code-field-tag">JSON</span>
        <textarea
          className="field-control mt-0 rounded-t-none font-mono text-[10px] leading-4"
          rows={3}
          defaultValue={formatValue(def, value)}
          title={schemaFieldHint(def)}
          onBlur={(e) => onChange(parseValue(def, e.target.value))}
          onMouseDown={(e) => e.stopPropagation()}
          spellCheck={false}
        />
      </div>
    )
  }
  if (widget === 'password' || widget === 'secret') {
    return (
      <div>
        <input
          type="password"
          className="field-control font-mono"
          value={formatValue(def, value)}
          title={schemaFieldHint(def)}
          onChange={(e) => onChange(e.target.value)}
          onMouseDown={(e) => e.stopPropagation()}
        />
        {secretHint}
      </div>
    )
  }

  // Multi-select for array fields with items.enum (e.g. caption formats)
  if (type === 'array') {
    const items = (unwrapSchema(def).items ?? def.items) as Record<string, unknown> | undefined
    const itemEnum = items && Array.isArray(items.enum) ? (items.enum as unknown[]) : null
    if (itemEnum && itemEnum.length) {
      const selected = Array.isArray(value) ? value.map(String) : []
      return (
        <div className="mt-1 flex flex-wrap gap-2" title={schemaFieldHint(def)}>
          {itemEnum.map((opt) => {
            const s = String(opt)
            const checked = selected.includes(s)
            return (
              <label key={s} className="inline-flex items-center gap-1.5 rounded border border-ink-200 bg-ink-50 px-2 py-1 text-[11px] text-ink-700">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 rounded border-ink-300"
                  checked={checked}
                  onChange={() => {
                    const next = checked ? selected.filter((x) => x !== s) : [...selected, s]
                    onChange(next)
                  }}
                  onMouseDown={(e) => e.stopPropagation()}
                />
                {s}
              </label>
            )
          })}
        </div>
      )
    }
  }

  const complex =
    type === 'object' ||
    isObjectSchema(def) ||
    (type === 'array' &&
      (typeof value === 'object' ||
        (Array.isArray(value) && value.some((v) => typeof v === 'object' && v != null))))

  if (complex) {
    return (
      <div className="code-field">
        <span className="code-field-tag">JSON</span>
        <textarea
        className="field-control mt-0 rounded-t-none font-mono text-[10px] leading-4"
        rows={3}
        defaultValue={formatValue(def, value)}
        onBlur={(e) => {
          try {
            onChange(parseValue(def, e.target.value))
            e.target.classList.remove('border-rose-400')
          } catch {
            e.target.classList.add('border-rose-400')
          }
        }}
        onMouseDown={(e) => e.stopPropagation()}
        spellCheck={false}
      />
      </div>
    )
  }

  if (type === 'number' || type === 'integer') {
    const nullable =
      isNullableSchema(def) ||
      def.default === null ||
      (Array.isArray(def.type) && (def.type as unknown[]).includes('null'))
    const bounds = numberInputAttrs(def)
    return (
      <input
        type="number"
        step={bounds.step}
        min={bounds.min}
        max={bounds.max}
        aria-invalid={invalid || undefined}
        className={`field-control overflow-x-auto font-mono${invalidCls}`}
        value={value == null || value === '' ? '' : Number(value)}
        title={schemaFieldHint(def) || formatValue(def, value)}
        placeholder={nullable ? 'default / empty' : undefined}
        onChange={(e) => {
          try {
            const raw = e.target.value
            if (raw === '' && nullable) onChange(null)
            else onChange(parseValue(def, raw))
          } catch {
            /* keep typing */
          }
        }}
        onMouseDown={(e) => e.stopPropagation()}
      />
    )
  }

  const k = key.toLowerCase()
  const longText =
    k.includes('code') ||
    k.includes('expression') ||
    k.includes('prompt') ||
    k.includes('body') ||
    k.includes('template') ||
    k.includes('script') ||
    k.includes('jsonpath')
  if (longText || widget === 'code') {
    return (
      <textarea
        className={`field-control mt-1 font-mono text-[11px] leading-4${invalidCls}`}
        aria-invalid={invalid || undefined}
        rows={4}
        value={formatValue(def, value)}
        title={schemaFieldHint(def)}
        onChange={(e) => onChange(e.target.value)}
        onMouseDown={(e) => e.stopPropagation()}
        spellCheck={false}
      />
    )
  }
  const pathish =
    k.includes('path') || k.includes('dir') || k.includes('file') || k.endsWith('_url') || k === 'url'
  return (
    <div>
      <input
        className={`${pathish ? 'field-control' : 'field-control overflow-x-auto font-mono'}${invalidCls}`}
        aria-invalid={invalid || undefined}
        value={formatValue(def, value)}
        title={schemaFieldHint(def) || formatValue(def, value)}
        placeholder={pathish ? 'workspace/ relative path' : undefined}
        onChange={(e) => {
          try {
            onChange(parseValue(def, e.target.value))
          } catch {
            /* keep typing */
          }
        }}
        onMouseDown={(e) => e.stopPropagation()}
      />
      {secretHint}
    </div>
  )
}

export function categoryLook(cat?: string, nodeType?: string) {
  const c = (cat || '').toLowerCase()
  // Triggers (webhook / schedule) are pipeline entry points, not audio inputs.
  if (c.includes('trigger') || /(^|_)trigger$/i.test(nodeType || '')) {
    return { bg: 'bg-[#475569]', Icon: Zap }
  }
  if (c.includes('audio') || c.includes('input') || c.includes('speech')) {
    return { bg: 'bg-[#ff6d5a]', Icon: AudioLines }
  }
  if (c.includes('ml') || c.includes('model') || c.includes('train') || c.includes('plugin')) {
    return { bg: 'bg-[#7c5cff]', Icon: Brain }
  }
  if (c.includes('logic') || c.includes('flow')) {
    return { bg: 'bg-[#20b8a0]', Icon: GitBranch }
  }
  if (c.includes('augment') || c.includes('detect')) {
    return { bg: 'bg-[#f5a524]', Icon: Sparkles }
  }
  return { bg: 'bg-[#2c3641]', Icon: Box }
}

export type NodeExecStatus =
  | 'idle'
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'skipped'
  | 'cancelled'
  | 'success'
  | 'error'

/** Normalize legacy success/error aliases used during streaming. */
export function normalizeExecStatus(status?: string): NodeExecStatus {
  const s = (status || 'idle').toLowerCase()
  if (
    s === 'success' ||
    s === 'succeeded' ||
    s === 'complete' ||
    s === 'completed' ||
    s === 'ok'
  )
    return 'succeeded'
  if (s === 'error' || s === 'fail' || s === 'failed') return 'failed'
  if (s === 'skip' || s === 'skipped') return 'skipped'
  if (s === 'cancel' || s === 'cancelled' || s === 'canceled') return 'cancelled'
  if (s === 'run' || s === 'running') return 'running'
  if (s === 'pending' || s === 'queued' || s === 'waiting') return 'pending'
  if (s === 'idle') return 'idle'
  return 'idle'
}

const STATUS_DOT: Record<string, string> = {
  idle: 'bg-ink-300',
  pending: 'bg-ink-400',
  running: 'bg-accent-500 animate-pulse',
  succeeded: 'bg-emerald-500',
  success: 'bg-emerald-500',
  failed: 'bg-rose-500',
  error: 'bg-rose-500',
  skipped: 'bg-ink-400',
  cancelled: 'bg-amber-500',
}

const PATH_BADGE: Record<string, string> = {
  A: 'bg-sky-50 text-sky-800 ring-sky-200',
  B: 'bg-teal-50 text-teal-800 ring-teal-200',
  C: 'bg-amber-50 text-amber-900 ring-amber-200',
  X: 'bg-violet-50 text-violet-800 ring-violet-200',
}

const PATH_EDGE: Record<string, string> = {
  A: 'border-l-4 border-l-sky-400',
  B: 'border-l-4 border-l-teal-400',
  C: 'border-l-4 border-l-amber-400',
  X: 'border-l-4 border-l-violet-400',
}

const STATUS_RING: Record<string, string> = {
  pending: 'ring-1 ring-ink-300/80',
  running: 'ring-2 ring-accent-400/80 ring-offset-1 ring-offset-white',
  succeeded: 'ring-1 ring-emerald-400/70',
  success: 'ring-1 ring-emerald-400/70',
  failed: 'ring-2 ring-rose-400/60',
  error: 'ring-2 ring-rose-400/60',
  skipped: 'ring-1 ring-dashed ring-ink-300',
  cancelled: 'ring-1 ring-amber-400/70',
}

export default function GraphynNode({ id, data, selected }: NodeProps<GraphynNodeData>) {
  const cfg = data.config ?? {}
  const inputs = data.inputs?.length ? data.inputs : [{ name: 'input' }]
  const outputs = outputsWithErrorPort(data.outputs?.length ? data.outputs : [{ name: 'output' }], data.onError)
  const captions = portCaptions(data.nodeType, outputs)
  const status = normalizeExecStatus(data.status)
  const isolated = data.runtime === 'isolated' || data.nodeType.startsWith('Isolated_')
  const look = categoryLook(data.category, data.nodeType)
  const Icon = look.Icon
  const failed = status === 'failed'
  const skipped = status === 'skipped'
  const path = data.pathBadge ?? null
  const prog = status === 'running' ? data.progress ?? null : null
  const statusWord =
    status === 'succeeded' ? 'Done' : status === 'skipped' ? 'Skipped (not run)' : status === 'pending' ? 'Waiting' : status === 'running' ? 'Running' : status === 'cancelled' ? 'Cancelled' : status === 'failed' ? 'Failed' : ''
  const summary = nodeSummary({ nodeType: data.nodeType, category: data.category, config: cfg, learningRate: data.effectiveLr })
  // Quiet secondary line: status during/after a run, else a key-config summary (or category).
  const secondary = status !== 'idle' ? statusWord : summary
  const label = data.displayTitle || data.label || data.nodeType

  return (
    <div
      title={`${data.displayLabel || label}${path ? ` · Path ${path.letter}${path.description ? ` (${path.description})` : ''}` : ''} — ${data.nodeType}${id ? ` · id ${id}` : ''}${summary ? ` · ${summary}` : ''}${isolated ? ' · isolated runtime' : ''}${status !== 'idle' ? ` · ${statusWord.toLowerCase()}` : ''}`}
      className={clsx(
        'graphyn-node group relative w-[272px] overflow-visible rounded-[10px] border bg-white',
        selected ? 'is-selected border-ink-900' : 'border-ink-200',
        STATUS_RING[status],
        status === 'running' && 'border-accent-500',
        status === 'succeeded' && 'border-emerald-400',
        failed && 'border-rose-300 bg-rose-50/40 opacity-90',
        skipped && 'opacity-60',
        status === 'cancelled' && 'border-amber-300 opacity-80',
        status === 'pending' && 'border-ink-300',
        data.configIssues ? 'border-rose-400' : null,
        path ? PATH_EDGE[path.letter] ?? PATH_EDGE.X : null,
      )}
      style={captions ? { minHeight: Math.max(64, outputs.length * 18 + 14) } : undefined}
    >
      {inputs.flatMap((p, i) => {
        const top = `${((i + 1) / (inputs.length + 1)) * 100}%`
        const left = `${((i + 1) / (inputs.length + 1)) * 100}%`
        const title = `Input “${p.name}”${p.data_type ? ` · ${p.data_type}` : ''} — drop a wire here`
        return [
          <Handle key={`in-l-${p.name}`} id={p.name} type="target" position={Position.Left} style={{ top }} className="graphyn-handle graphyn-handle-in" title={title} aria-label={title} />,
          <Handle key={`in-t-${p.name}`} id={`${p.name}::top`} type="target" position={Position.Top} style={{ left }} className="graphyn-handle graphyn-handle-in" title={`${title} (top)`} aria-label={`${title} (top)`} />,
        ]
      })}

      <div className="flex items-start gap-2.5 px-2.5 py-2.5">
        <div className={clsx('mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-white shadow-sm', look.bg)}>
          <Icon className="h-[18px] w-[18px]" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-1.5">
            {/* Full step name — wraps to two lines instead of truncating to "Model …". */}
            <div
              className={clsx(
                'line-clamp-2 min-w-0 flex-1 break-words text-[14px] font-semibold leading-snug',
                failed ? 'text-rose-900' : 'text-ink-950',
              )}
            >
              {label}
            </div>
            <span
              className={clsx('mt-1.5 h-2 w-2 shrink-0 rounded-full ring-2 ring-white', STATUS_DOT[status] ?? STATUS_DOT.idle)}
              title={status}
              aria-label={`Status ${status}`}
            />
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-1.5">
            {path ? (
              <span
                className={clsx('shrink-0 rounded px-1.5 py-px text-[10px] font-semibold ring-1', PATH_BADGE[path.letter] ?? PATH_BADGE.X)}
                title={path.description ? `Path ${path.letter} — ${path.description}` : `Path ${path.letter}`}
              >
                Path {path.letter}
              </span>
            ) : null}
            {data.configIssues ? (
              <span
                className="shrink-0 rounded-full bg-rose-100 px-1.5 text-[10px] font-semibold text-rose-800"
                title={`${data.configIssues} invalid config field${data.configIssues === 1 ? '' : 's'} — open the inspector`}
              >
                {data.configIssues} invalid
              </span>
            ) : null}
            {data.displaySubtitle ? (
              <span className="shrink-0 text-[11.5px] text-ink-500" title={data.nodeType}>
                {data.displaySubtitle}
                {secondary ? <span className="text-ink-300"> ·</span> : null}
              </span>
            ) : null}
            {secondary ? (
              <span className={clsx('min-w-0 truncate text-[11.5px]', failed ? 'text-rose-700' : 'text-ink-400')}>
                {secondary}
              </span>
            ) : null}
          </div>
          {prog ? (
            <div className="mt-1" aria-live="polite">
              {prog.pct != null ? (
                <div className="h-1.5 overflow-hidden rounded-full bg-ink-100">
                  <div
                    className="h-full rounded-full bg-accent-500 transition-[width]"
                    style={{ width: `${Math.max(2, prog.pct)}%` }}
                  />
                </div>
              ) : null}
              <div className="mt-0.5 truncate text-[11px] tabular-nums text-ink-600">{progressBadgeText(prog)}</div>
            </div>
          ) : null}
        </div>
        {/* Node actions: quiet until hover / focus / selection (keeps the card readable). */}
        <div
          className={clsx(
            'flex shrink-0 flex-col gap-0.5 transition-opacity',
            selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-within:opacity-100',
          )}
        >
          {data.onOpenInspector && (
            <button
              type="button"
              className="btn-icon h-6 w-6"
              title="Configure"
              aria-label="Configure"
              onClick={(e) => {
                e.stopPropagation()
                data.onOpenInspector?.()
              }}
            >
              <Pencil className="h-3 w-3" />
            </button>
          )}
          {data.onDuplicate && (
            <button
              type="button"
              className="btn-icon h-6 w-6"
              title="Copy node"
              aria-label="Copy node"
              onClick={(e) => {
                e.stopPropagation()
                data.onDuplicate?.()
              }}
            >
              <Copy className="h-3 w-3" />
            </button>
          )}
          {data.onDelete && (
            <button
              type="button"
              className="btn-icon h-6 w-6 hover:bg-rose-50 hover:text-rose-600"
              title="Remove"
              aria-label="Remove"
              onClick={(e) => {
                e.stopPropagation()
                data.onDelete?.()
              }}
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {outputs.flatMap((p, i) => {
        const top = `${((i + 1) / (outputs.length + 1)) * 100}%`
        const left = `${((i + 1) / (outputs.length + 1)) * 100}%`
        const title = p.isError
          ? `Error branch “${p.name}” — runs when this step fails (on_error = route)`
          : `Output “${p.name}”${p.data_type ? ` · ${p.data_type}` : ''} — drag to an input handle`
        const cls = clsx('graphyn-handle graphyn-handle-out', p.isError && 'graphyn-handle-error')
        return [
          <Handle key={`out-r-${p.name}`} id={p.name} type="source" position={Position.Right} style={{ top }} className={cls} title={title} aria-label={title} />,
          <Handle key={`out-b-${p.name}`} id={`${p.name}::bottom`} type="source" position={Position.Bottom} style={{ left }} className={cls} title={`${title} (bottom)`} aria-label={`${title} (bottom)`} />,
        ]
      })}
      {captions
        ? captions.map((c, i) => (
            <span
              key={`cap-${c.name}`}
              aria-hidden
              className={clsx(
                'pointer-events-none absolute left-full ml-2 -translate-y-full whitespace-nowrap rounded px-1 font-mono text-[9.5px] leading-[14px]',
                c.tone === 'ok' && 'bg-emerald-50 text-emerald-800',
                c.tone === 'bad' && 'bg-rose-50 text-rose-700',
                c.tone === 'neutral' && 'bg-white/90 text-ink-500',
              )}
              style={{ top: `${((i + 1) / (captions.length + 1)) * 100}%` }}
            >
              {c.name}
            </span>
          ))
        : null}
    </div>
  )
}
