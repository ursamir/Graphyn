import { Handle, Position, type NodeProps } from 'reactflow'
import clsx from 'clsx'
import type { NodePlacement, PortDef } from '../../types/graph'
import { AudioLines, Box, Brain, GitBranch, Pencil, Sparkles, X } from 'lucide-react'
import { schemaFieldHint } from '../../lib/format'

export type GraphynNodeData = {
  nodeType: string
  label: string
  category?: string
  config: Record<string, unknown>
  schemaProps?: Record<string, Record<string, unknown>>
  /** IR 1.2+ placement (Mode B). */
  placement?: NodePlacement | null
  inputs: PortDef[]
  outputs: PortDef[]
  status?: 'idle' | 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'cancelled' | 'success' | 'error'
  /** Last execution error snippet when status is failed */
  lastError?: string
  runtime?: string
  onChangeConfig?: (key: string, value: unknown) => void
  onChangePlacement?: (next: NodePlacement | null) => void
  onDelete?: () => void
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

export function ConfigFieldEditor(
  props: { fieldKey: string; def: Record<string, unknown>; value: unknown; onChange: (v: unknown) => void },
) {
  return fieldEditor(props.fieldKey, props.def, props.value, props.onChange)
}

function fieldEditor(
  key: string,
  def: Record<string, unknown>,
  value: unknown,
  onChange: (v: unknown) => void,
) {
  const type = schemaType(def)
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
        className="field-control"
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
      <input
        type="password"
        className="field-control font-mono"
        value={formatValue(def, value)}
        title={schemaFieldHint(def)}
        onChange={(e) => onChange(e.target.value)}
        onMouseDown={(e) => e.stopPropagation()}
      />
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
    return (
      <input
        type="number"
        step={type === 'integer' ? 1 : 'any'}
        className="field-control overflow-x-auto font-mono"
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
        className="field-control mt-1 font-mono text-[11px] leading-4"
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
    <input
      className={pathish ? 'field-control' : 'field-control overflow-x-auto font-mono'}
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
  )
}

export function categoryLook(cat?: string) {
  const c = (cat || '').toLowerCase()
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
  if (s === 'success' || s === 'complete' || s === 'completed' || s === 'ok') return 'succeeded'
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

export default function GraphynNode({ data, selected }: NodeProps<GraphynNodeData>) {
  const props = data.schemaProps ?? {}
  const entries = Object.entries(props)
  const inputs = data.inputs?.length ? data.inputs : [{ name: 'input' }]
  const outputs = data.outputs?.length ? data.outputs : [{ name: 'output' }]
  const status = normalizeExecStatus(data.status)
  const isolated = data.runtime === 'isolated' || data.nodeType.startsWith('Isolated_')
  const look = categoryLook(data.category)
  const Icon = look.Icon
  const failed = status === 'failed'
  const skipped = status === 'skipped'

  return (
    <div
      title={`${data.nodeType}${status !== 'idle' ? ` · ${status}` : ''}`}
      className={clsx(
        'graphyn-node relative w-[240px] overflow-visible rounded-[10px] border bg-white',
        selected ? 'is-selected border-ink-900' : 'border-ink-200',
        STATUS_RING[status],
        status === 'running' && 'border-accent-500',
        status === 'succeeded' && 'border-emerald-400',
        failed && 'border-rose-300 bg-rose-50/40 opacity-90',
        skipped && 'opacity-60',
        status === 'cancelled' && 'border-amber-300 opacity-80',
        status === 'pending' && 'border-ink-300',
      )}
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

      <div className="flex items-center gap-2.5 px-2.5 py-2.5">
        <div className={clsx('flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-white shadow-sm', look.bg)}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <div className={clsx('truncate text-[13px] font-semibold leading-tight', failed ? 'text-rose-900' : 'text-ink-950')}>
              {data.label || data.nodeType}
            </div>
            <span
              className={clsx('h-2 w-2 shrink-0 rounded-full ring-2 ring-white', STATUS_DOT[status] ?? STATUS_DOT.idle)}
              title={status}
              aria-label={`Status ${status}`}
            />
          </div>
          <div className={clsx('mt-0.5 truncate text-[11px]', failed ? 'text-rose-700' : 'text-ink-500')}>
            {status !== 'idle' ? `${status} · ` : ''}
            {data.category || 'node'}
            {isolated ? ' · isolated' : ''}
            {entries.length ? ` · ${entries.length} fields` : ''}
          </div>
        </div>
        <div className="flex shrink-0 flex-col gap-0.5 opacity-70 hover:opacity-100">
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
        const title = `Output “${p.name}”${p.data_type ? ` · ${p.data_type}` : ''} — drag to an input handle`
        return [
          <Handle key={`out-r-${p.name}`} id={p.name} type="source" position={Position.Right} style={{ top }} className="graphyn-handle graphyn-handle-out" title={title} aria-label={title} />,
          <Handle key={`out-b-${p.name}`} id={`${p.name}::bottom`} type="source" position={Position.Bottom} style={{ left }} className="graphyn-handle graphyn-handle-out" title={`${title} (bottom)`} aria-label={`${title} (bottom)`} />,
        ]
      })}
    </div>
  )
}
