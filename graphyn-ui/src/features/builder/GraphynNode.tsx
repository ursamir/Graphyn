import { Handle, Position, type NodeProps } from 'reactflow'
import clsx from 'clsx'
import type { PortDef } from '../../types/graph'
import { AudioLines, Box, Brain, GitBranch, Pencil, Sparkles, X } from 'lucide-react'
import { schemaFieldHint } from '../../lib/format'

export type GraphynNodeData = {
  nodeType: string
  label: string
  category?: string
  config: Record<string, unknown>
  schemaProps?: Record<string, Record<string, unknown>>
  inputs: PortDef[]
  outputs: PortDef[]
  status?: 'idle' | 'running' | 'success' | 'error'
  runtime?: string
  onChangeConfig?: (key: string, value: unknown) => void
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

function parseValue(def: Record<string, unknown>, raw: string): unknown {
  const type = schemaType(def)
  if (type === 'number' || type === 'integer') return raw === '' ? 0 : Number(raw)
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
  _key: string,
  def: Record<string, unknown>,
  value: unknown,
  onChange: (v: unknown) => void,
) {
  const type = schemaType(def)
  if (type === 'boolean') {
    return (
      <input
        type="checkbox"
        checked={Boolean(value)}
        title={schemaFieldHint(def)}
        onChange={(e) => onChange(e.target.checked)}
        onMouseDown={(e) => e.stopPropagation()}
      />
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
    return (
      <input
        type="number"
        step={type === 'integer' ? 1 : 'any'}
        className="field-control overflow-x-auto font-mono"
        value={value == null || value === '' ? '' : Number(value)}
        title={formatValue(def, value)}
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

  return (
    <input
      className="field-control overflow-x-auto font-mono"
      value={formatValue(def, value)}
      title={formatValue(def, value)}
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

const STATUS_DOT: Record<string, string> = {
  idle: 'bg-ink-300',
  running: 'bg-accent-500 animate-pulse',
  success: 'bg-emerald-500',
  error: 'bg-rose-500',
}

export default function GraphynNode({ data, selected }: NodeProps<GraphynNodeData>) {
  const props = data.schemaProps ?? {}
  const entries = Object.entries(props)
  const inputs = data.inputs?.length ? data.inputs : [{ name: 'input' }]
  const outputs = data.outputs?.length ? data.outputs : [{ name: 'output' }]
  const status = data.status ?? 'idle'
  const isolated = data.runtime === 'isolated' || data.nodeType.startsWith('Isolated_')
  const look = categoryLook(data.category)
  const Icon = look.Icon

  return (
    <div
      title={data.nodeType}
      className={clsx(
        'graphyn-node relative w-[240px] overflow-visible rounded-[10px] border bg-white',
        selected ? 'is-selected border-ink-900' : 'border-ink-200',
        status === 'running' && 'border-accent-500',
        status === 'success' && 'border-emerald-500',
        status === 'error' && 'border-rose-500',
      )}
    >
      {inputs.map((p, i) => {
        const top = `${((i + 1) / (inputs.length + 1)) * 100}%`
        const left = `${((i + 1) / (inputs.length + 1)) * 100}%`
        const title = `${p.name}${p.data_type ? ` (${p.data_type})` : ''}`
        return (
          <span key={`in-${p.name}`}>
            <Handle id={p.name} type="target" position={Position.Left} style={{ top }} className="graphyn-handle graphyn-handle-in" title={title} />
            <Handle id={`${p.name}::top`} type="target" position={Position.Top} style={{ left }} className="graphyn-handle graphyn-handle-in" title={`${title} (top)`} />
          </span>
        )
      })}

      <div className="flex items-center gap-2.5 px-2.5 py-2.5">
        <div className={clsx('flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-white shadow-sm', look.bg)}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <div className="truncate text-[13px] font-semibold leading-tight text-ink-950">
              {data.label || data.nodeType}
            </div>
            <span className={clsx('h-1.5 w-1.5 shrink-0 rounded-full', STATUS_DOT[status] ?? STATUS_DOT.idle)} />
          </div>
          <div className="mt-0.5 truncate text-[11px] text-ink-400">
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

      {outputs.map((p, i) => {
        const top = `${((i + 1) / (outputs.length + 1)) * 100}%`
        const left = `${((i + 1) / (outputs.length + 1)) * 100}%`
        const title = `${p.name}${p.data_type ? ` (${p.data_type})` : ''}`
        return (
          <span key={`out-${p.name}`}>
            <Handle id={p.name} type="source" position={Position.Right} style={{ top }} className="graphyn-handle graphyn-handle-out" title={title} />
            <Handle id={`${p.name}::bottom`} type="source" position={Position.Bottom} style={{ left }} className="graphyn-handle graphyn-handle-out" title={`${title} (bottom)`} />
          </span>
        )
      })}
    </div>
  )
}
