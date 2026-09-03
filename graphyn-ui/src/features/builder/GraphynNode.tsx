import { Handle, Position, type NodeProps } from 'reactflow'
import clsx from 'clsx'
import type { PortDef } from '../../types/graph'
import { schemaFieldHint, schemaFieldLabel } from '../../lib/format'

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
        className="mt-0.5 w-full rounded border border-ink-200 bg-ink-50 px-1.5 py-0.5 text-[11px]"
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
      <textarea
        className="mt-0.5 w-full rounded border border-ink-200 bg-ink-50 px-1.5 py-1 font-mono text-[10px] text-ink-800"
        rows={3}
        defaultValue={formatValue(def, value)}
        title={schemaFieldHint(def)}
        onBlur={(e) => onChange(parseValue(def, e.target.value))}
        onMouseDown={(e) => e.stopPropagation()}
        spellCheck={false}
      />
    )
  }
  if (widget === 'password' || widget === 'secret') {
    return (
      <input
        type="password"
        className="mt-0.5 w-full rounded border border-ink-200 bg-ink-50 px-1.5 py-0.5 font-mono text-[11px] text-ink-800"
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
      <textarea
        className="mt-0.5 w-full rounded border border-ink-200 bg-ink-50 px-1.5 py-1 font-mono text-[10px] text-ink-800"
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
    )
  }

  if (type === 'number' || type === 'integer') {
    return (
      <input
        type="number"
        step={type === 'integer' ? 1 : 'any'}
        className="mt-0.5 w-full overflow-x-auto rounded border border-ink-200 bg-ink-50 px-1.5 py-0.5 font-mono text-[11px] text-ink-800"
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
      className="mt-0.5 w-full overflow-x-auto rounded border border-ink-200 bg-ink-50 px-1.5 py-0.5 font-mono text-[11px] text-ink-800"
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

const STATUS_EDGE: Record<string, string> = {
  idle: 'bg-ink-300',
  running: 'bg-accent-500',
  success: 'bg-emerald-500',
  error: 'bg-rose-500',
}

export default function GraphynNode({ data, selected }: NodeProps<GraphynNodeData>) {
  const props = data.schemaProps ?? {}
  const entries = Object.entries(props)
  const shown = entries.length <= 6 ? entries : entries.slice(0, 5)
  const hiddenCount = Math.max(0, entries.length - shown.length)
  const inputs = data.inputs?.length ? data.inputs : [{ name: 'input' }]
  const outputs = data.outputs?.length ? data.outputs : [{ name: 'output' }]
  const status = data.status ?? 'idle'
  const isolated = data.runtime === 'isolated' || data.nodeType.startsWith('Isolated_')

  return (
    <div
      title={data.nodeType}
      className={clsx(
        'min-w-[300px] max-w-[380px] overflow-visible rounded-lg border bg-white shadow-sm',
        selected ? 'border-accent-500 shadow-md ring-2 ring-accent-200' : 'border-ink-200',
        status === 'running' && 'border-accent-400',
        status === 'success' && 'border-emerald-500',
        status === 'error' && 'border-rose-500',
      )}
    >
      {inputs.map((p, i) => (
        <Handle
          key={`in-${p.name}`}
          id={p.name}
          type="target"
          position={Position.Top}
          style={{ left: `${((i + 1) / (inputs.length + 1)) * 100}%` }}
          className="!h-3 !w-3 !border-2 !border-white !bg-ink-700"
          title={`${p.name}${p.data_type ? ` (${p.data_type})` : ''}`}
        />
      ))}

      <div className="flex">
        <div className={clsx('w-1 shrink-0 self-stretch', STATUS_EDGE[status] ?? STATUS_EDGE.idle)} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2 px-2.5 py-1.5">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <div className="truncate font-display text-[13px] font-bold leading-tight text-ink-950">
                  {data.label || data.nodeType}
                </div>
                {isolated && (
                  <span className="shrink-0 rounded bg-ink-100 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-ink-600">
                    Iso
                  </span>
                )}
              </div>
              {data.category && (
                <div className="truncate text-[10px] text-ink-400">{data.category}</div>
              )}
            </div>
            <div className="flex shrink-0 gap-1">
              {data.onOpenInspector && entries.length > 0 && (
                <button
                  type="button"
                  className="text-[10px] text-accent-700 hover:underline"
                  onClick={(e) => {
                    e.stopPropagation()
                    data.onOpenInspector?.()
                  }}
                >
                  edit
                </button>
              )}
              {data.onValidateConfig && (
                <button
                  type="button"
                  className="text-[10px] text-accent-700 hover:underline"
                  onClick={(e) => {
                    e.stopPropagation()
                    data.onValidateConfig?.()
                  }}
                >
                  check
                </button>
              )}
              {data.onDelete && (
                <button
                  type="button"
                  className="text-[10px] text-ink-400 hover:text-rose-600"
                  onClick={(e) => {
                    e.stopPropagation()
                    data.onDelete?.()
                  }}
                >
                  remove
                </button>
              )}
            </div>
          </div>

          <div className="max-h-40 space-y-1 overflow-x-auto overflow-y-auto border-t border-ink-100 px-2.5 py-1.5">
            {entries.length === 0 ? (
              <div className="text-[11px] text-ink-400">No config</div>
            ) : (
              shown.map(([key, def]) => (
                <label key={key} className="block text-[11px] text-ink-600" title={schemaFieldHint(def)}>
                  <span className="font-medium">{schemaFieldLabel(key, def)}</span>
                  {fieldEditor(key, def, data.config?.[key] ?? def.default, (v) =>
                    data.onChangeConfig?.(key, v),
                  )}
                </label>
              ))
            )}
            {hiddenCount > 0 && (
              <button
                type="button"
                className="text-[10px] text-accent-700 hover:underline"
                onClick={(e) => {
                  e.stopPropagation()
                  data.onOpenInspector?.()
                }}
              >
                +{hiddenCount} more — edit all
              </button>
            )}
          </div>
        </div>
      </div>

      {outputs.map((p, i) => (
        <Handle
          key={`out-${p.name}`}
          id={p.name}
          type="source"
          position={Position.Bottom}
          style={{ left: `${((i + 1) / (outputs.length + 1)) * 100}%` }}
          className="!h-3 !w-3 !border-2 !border-white !bg-accent-600"
          title={`${p.name}${p.data_type ? ` (${p.data_type})` : ''}`}
        />
      ))}
    </div>
  )
}
