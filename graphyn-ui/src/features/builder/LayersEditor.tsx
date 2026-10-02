/** Structured editor for model_builder `layers` (replaces raw JSON textarea). */

import React from 'react'
import { ChevronDown, ChevronUp, Plus, Trash2 } from 'lucide-react'
import type { LayerSpec } from './modelBuilderPresets'

const LAYER_TYPES = [
  'conv2d',
  'depthwise_conv2d',
  'batch_norm',
  'relu',
  'relu6',
  'max_pool2d',
  'avg_pool2d',
  'global_avg_pool2d',
  'dropout',
  'dense',
  'inverted_residual',
  'ds_separable_block',
] as const

type LayerType = (typeof LAYER_TYPES)[number]

type FieldKind = 'number' | 'text' | 'boolean' | 'select'

type FieldDef = {
  key: string
  label: string
  kind: FieldKind
  options?: string[]
  placeholder?: string
}

const COMMON_PAD: FieldDef = {
  key: 'padding',
  label: 'Padding',
  kind: 'select',
  options: ['same', 'valid'],
}

const FIELDS_BY_TYPE: Record<LayerType, FieldDef[]> = {
  conv2d: [
    { key: 'filters', label: 'Filters', kind: 'number' },
    { key: 'kernel_size', label: 'Kernel', kind: 'number', placeholder: '3' },
    { key: 'strides', label: 'Stride', kind: 'number', placeholder: '1' },
    COMMON_PAD,
    { key: 'activation', label: 'Activation', kind: 'text', placeholder: 'relu (optional)' },
    { key: 'use_bias', label: 'Use bias', kind: 'boolean' },
  ],
  depthwise_conv2d: [
    { key: 'kernel_size', label: 'Kernel', kind: 'number', placeholder: '3' },
    { key: 'strides', label: 'Stride', kind: 'number', placeholder: '1' },
    COMMON_PAD,
    { key: 'use_bias', label: 'Use bias', kind: 'boolean' },
  ],
  batch_norm: [],
  relu: [],
  relu6: [],
  max_pool2d: [
    { key: 'pool_size', label: 'Pool size', kind: 'number', placeholder: '2' },
    { key: 'strides', label: 'Stride', kind: 'number', placeholder: 'same as pool' },
    COMMON_PAD,
  ],
  avg_pool2d: [
    { key: 'pool_size', label: 'Pool size', kind: 'number', placeholder: '2' },
    { key: 'strides', label: 'Stride', kind: 'number', placeholder: 'same as pool' },
    COMMON_PAD,
  ],
  global_avg_pool2d: [],
  dropout: [{ key: 'rate', label: 'Rate', kind: 'number', placeholder: '0.25' }],
  dense: [
    { key: 'units', label: 'Units', kind: 'number' },
    { key: 'activation', label: 'Activation', kind: 'text', placeholder: 'softmax' },
  ],
  inverted_residual: [
    { key: 'filters', label: 'Out filters', kind: 'number' },
    { key: 'expansion_factor', label: 'Expansion', kind: 'number', placeholder: '6' },
    { key: 'stride', label: 'Stride', kind: 'number', placeholder: '1' },
    { key: 'kernel_size', label: 'Kernel', kind: 'number', placeholder: '3' },
    { key: 'use_bias', label: 'Use bias', kind: 'boolean' },
  ],
  ds_separable_block: [
    { key: 'filters', label: 'Filters', kind: 'number' },
    { key: 'kernel_size', label: 'Kernel', kind: 'number', placeholder: '3' },
    COMMON_PAD,
    { key: 'use_bias', label: 'Use bias', kind: 'boolean' },
  ],
}

function asLayers(value: unknown): LayerSpec[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((x): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x))
    .map((x) => ({ ...x, type: String(x.type || 'conv2d') }))
}

function scalarDisplay(v: unknown): string {
  if (v == null) return ''
  if (Array.isArray(v)) return String(v[0] ?? '')
  return String(v)
}

function parseMaybeNumber(raw: string): number | string {
  const t = raw.trim()
  if (!t) return ''
  const n = Number(t)
  return Number.isFinite(n) ? n : t
}

function layerSummary(layer: LayerSpec): string {
  const t = String(layer.type || '?')
  const bits: string[] = [t]
  if (layer.filters != null) bits.push(`f=${layer.filters}`)
  if (layer.units != null) bits.push(`u=${layer.units}`)
  if (layer.rate != null) bits.push(`r=${layer.rate}`)
  if (layer.stride != null || layer.strides != null) bits.push(`s=${layer.stride ?? layer.strides}`)
  if (layer.expansion_factor != null) bits.push(`×${layer.expansion_factor}`)
  return bits.join(' · ')
}

function defaultLayer(type: LayerType = 'conv2d'): LayerSpec {
  const base: LayerSpec = { type }
  if (type === 'conv2d' || type === 'ds_separable_block') {
    return { ...base, filters: 64, kernel_size: 3, padding: 'same' }
  }
  if (type === 'inverted_residual') {
    return { ...base, filters: 64, expansion_factor: 6, stride: 1, kernel_size: 3, use_bias: false }
  }
  if (type === 'dropout') return { ...base, rate: 0.25 }
  if (type === 'dense') return { ...base, units: 6, activation: 'softmax' }
  if (type === 'max_pool2d' || type === 'avg_pool2d') return { ...base, pool_size: 2 }
  if (type === 'depthwise_conv2d') return { ...base, kernel_size: 3, padding: 'same' }
  return base
}

export function LayersEditor({
  value,
  onChange,
  invalid,
}: {
  value: unknown
  onChange: (v: unknown) => void
  invalid?: boolean
}) {
  const layers = asLayers(value)
  const [openIdx, setOpenIdx] = React.useState<number | null>(layers.length ? 0 : null)
  const [jsonMode, setJsonMode] = React.useState(false)
  const [jsonDraft, setJsonDraft] = React.useState('')
  const [jsonError, setJsonError] = React.useState<string | null>(null)

  const commit = (next: LayerSpec[]) => onChange(next)

  const updateAt = (i: number, patch: Record<string, unknown>) => {
    const next = layers.map((l, idx) => (idx === i ? { ...l, ...patch } : l))
    commit(next)
  }

  const setType = (i: number, type: LayerType) => {
    const next = layers.map((l, idx) => (idx === i ? defaultLayer(type) : l))
    commit(next)
  }

  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir
    if (j < 0 || j >= layers.length) return
    const next = layers.slice()
    const [row] = next.splice(i, 1)
    next.splice(j, 0, row)
    commit(next)
    setOpenIdx(j)
  }

  const remove = (i: number) => {
    const next = layers.filter((_, idx) => idx !== i)
    commit(next)
    setOpenIdx((cur) => {
      if (cur == null) return null
      if (next.length === 0) return null
      if (cur === i) return Math.min(i, next.length - 1)
      if (cur > i) return cur - 1
      return cur
    })
  }

  const add = () => {
    const next = [...layers, defaultLayer('conv2d')]
    commit(next)
    setOpenIdx(next.length - 1)
  }

  const enterJson = () => {
    setJsonDraft(JSON.stringify(layers, null, 2))
    setJsonError(null)
    setJsonMode(true)
  }

  const applyJson = () => {
    try {
      const parsed = JSON.parse(jsonDraft) as unknown
      if (!Array.isArray(parsed)) throw new Error('Root must be a JSON array')
      commit(asLayers(parsed))
      setJsonMode(false)
      setJsonError(null)
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : String(e))
    }
  }

  if (jsonMode) {
    return (
      <div className={`mt-1 space-y-1.5${invalid ? ' rounded-lg ring-1 ring-rose-300' : ''}`}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">JSON</span>
          <div className="flex gap-1.5">
            <button
              type="button"
              className="rounded border border-ink-200 bg-white px-1.5 py-0.5 text-[10px] font-medium text-ink-700 hover:bg-ink-50"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => setJsonMode(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rounded border border-ink-800 bg-ink-900 px-1.5 py-0.5 text-[10px] font-medium text-white hover:bg-ink-800"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={applyJson}
            >
              Apply JSON
            </button>
          </div>
        </div>
        <textarea
          className="field-control font-mono text-[10px] leading-4"
          rows={10}
          value={jsonDraft}
          onChange={(e) => setJsonDraft(e.target.value)}
          onMouseDown={(e) => e.stopPropagation()}
          spellCheck={false}
        />
        {jsonError ? (
          <p className="text-[10px] font-medium text-rose-700" role="alert">
            {jsonError}
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <div className={`mt-1 space-y-1.5${invalid ? ' rounded-lg ring-1 ring-rose-300 p-1' : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-ink-500">
          {layers.length} layer{layers.length === 1 ? '' : 's'}
          {layers.length === 0 ? ' — add one or Load from preset' : ''}
        </span>
        <button
          type="button"
          className="text-[10px] font-medium text-ink-500 underline-offset-2 hover:text-ink-800 hover:underline"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={enterJson}
        >
          Edit as JSON
        </button>
      </div>

      <ul className="max-h-[22rem] space-y-1 overflow-y-auto pr-0.5">
        {layers.map((layer, i) => {
          const t = (LAYER_TYPES.includes(layer.type as LayerType) ? layer.type : 'conv2d') as LayerType
          const open = openIdx === i
          const fields = FIELDS_BY_TYPE[t] ?? []
          return (
            <li key={i} className="rounded-lg border border-ink-200 bg-ink-50/60">
              <div className="flex items-center gap-1 px-1.5 py-1">
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate text-left text-[11px] font-medium text-ink-800"
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={() => setOpenIdx(open ? null : i)}
                  aria-expanded={open}
                >
                  <span className="mr-1 text-ink-400">{i + 1}.</span>
                  {layerSummary(layer)}
                </button>
                <button
                  type="button"
                  className="btn-icon !h-6 !w-6"
                  aria-label="Move up"
                  disabled={i === 0}
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={() => move(i, -1)}
                >
                  <ChevronUp className="h-3 w-3" />
                </button>
                <button
                  type="button"
                  className="btn-icon !h-6 !w-6"
                  aria-label="Move down"
                  disabled={i === layers.length - 1}
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={() => move(i, 1)}
                >
                  <ChevronDown className="h-3 w-3" />
                </button>
                <button
                  type="button"
                  className="btn-icon !h-6 !w-6 text-rose-600"
                  aria-label="Remove layer"
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={() => remove(i)}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
              {open ? (
                <div className="space-y-1.5 border-t border-ink-200 px-2 py-2">
                  <label className="block text-[10px] text-ink-600">
                    Type
                    <select
                      className="field-control mt-0.5 py-1 text-[11px]"
                      value={t}
                      onChange={(e) => setType(i, e.target.value as LayerType)}
                      onMouseDown={(e) => e.stopPropagation()}
                    >
                      {LAYER_TYPES.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  </label>
                  {fields.map((f) => {
                    if (f.kind === 'boolean') {
                      return (
                        <label key={f.key} className="flex items-center gap-2 text-[11px] text-ink-700">
                          <input
                            type="checkbox"
                            className="h-3.5 w-3.5 rounded border-ink-300"
                            checked={Boolean(layer[f.key])}
                            onChange={(e) => updateAt(i, { [f.key]: e.target.checked })}
                            onMouseDown={(e) => e.stopPropagation()}
                          />
                          {f.label}
                        </label>
                      )
                    }
                    if (f.kind === 'select') {
                      return (
                        <label key={f.key} className="block text-[10px] text-ink-600">
                          {f.label}
                          <select
                            className="field-control mt-0.5 py-1 text-[11px]"
                            value={String(layer[f.key] ?? f.options?.[0] ?? '')}
                            onChange={(e) => updateAt(i, { [f.key]: e.target.value })}
                            onMouseDown={(e) => e.stopPropagation()}
                          >
                            {(f.options ?? []).map((opt) => (
                              <option key={opt} value={opt}>
                                {opt}
                              </option>
                            ))}
                          </select>
                        </label>
                      )
                    }
                    return (
                      <label key={f.key} className="block text-[10px] text-ink-600">
                        {f.label}
                        <input
                          type={f.kind === 'number' ? 'number' : 'text'}
                          className="field-control mt-0.5 py-1 font-mono text-[11px]"
                          value={scalarDisplay(layer[f.key])}
                          placeholder={f.placeholder}
                          onChange={(e) => {
                            const raw = e.target.value
                            updateAt(i, {
                              [f.key]: f.kind === 'number' ? parseMaybeNumber(raw) : raw,
                            })
                          }}
                          onMouseDown={(e) => e.stopPropagation()}
                        />
                      </label>
                    )
                  })}
                </div>
              ) : null}
            </li>
          )
        })}
      </ul>

      <button
        type="button"
        className="inline-flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-ink-300 bg-white px-2 py-1.5 text-[11px] font-medium text-ink-700 hover:bg-ink-50"
        onMouseDown={(e) => e.stopPropagation()}
        onClick={add}
      >
        <Plus className="h-3.5 w-3.5" />
        Add layer
      </button>
    </div>
  )
}
