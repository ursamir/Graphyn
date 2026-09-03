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
  const type = String(def.type ?? 'string')
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
  const type = String(def.type ?? 'string')
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

function fieldEditor(
  _key: string,
  def: Record<string, unknown>,
  value: unknown,
  onChange: (v: unknown) => void,
) {
  const type = String(def.type ?? 'string')
  if (type === 'boolean') {
    return (
      <input
        type="checkbox"
        checked={Boolean(value)}
        onChange={(e) => onChange(e.target.checked)}
        onMouseDown={(e) => e.stopPropagation()}
      />
    )
  }
  if (Array.isArray(def.enum)) {
    return (
      <select
        className="mt-0.5 w-full rounded border border-ink-200 bg-ink-50 px-1.5 py-0.5 text-[11px]"
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {(def.enum as unknown[]).map((opt) => (
          <option key={String(opt)} value={String(opt)}>
            {String(opt)}
          </option>
        ))}
      </select>
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

  return (
    <input
      className="mt-0.5 w-full rounded border border-ink-200 bg-ink-50 px-1.5 py-0.5 font-mono text-[11px] text-ink-800"
      value={formatValue(def, value)}
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
  const inputs = data.inputs?.length ? data.inputs : [{ name: 'input' }]
  const outputs = data.outputs?.length ? data.outputs : [{ name: 'output' }]
  const status = data.status ?? 'idle'
  const isolated = data.runtime === 'isolated' || data.nodeType.startsWith('Isolated_')

  return (
    <div
      title={data.nodeType}
      className={clsx(
        'min-w-[196px] max-w-[248px] overflow-hidden rounded-lg border bg-white shadow-sm',
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

          <div className="max-h-40 space-y-1 overflow-y-auto border-t border-ink-100 px-2.5 py-1.5">
            {entries.length === 0 ? (
              <div className="text-[11px] text-ink-400">No config</div>
            ) : (
              entries.map(([key, def]) => (
                <label key={key} className="block text-[11px] text-ink-600" title={schemaFieldHint(def)}>
                  <span className="font-medium">{schemaFieldLabel(key, def)}</span>
                  {fieldEditor(key, def, data.config?.[key] ?? def.default, (v) =>
                    data.onChangeConfig?.(key, v),
                  )}
                </label>
              ))
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
