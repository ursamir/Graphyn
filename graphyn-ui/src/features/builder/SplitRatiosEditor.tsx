/** Structured editor for `split_ratios` ({train,val,test} or custom weight map). */

import React from 'react'
import { Plus, Trash2 } from 'lucide-react'

const STANDARD = ['train', 'val', 'test'] as const

function asRatios(value: unknown): Record<string, number> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { train: 0.7, val: 0.15, test: 0.15 }
  }
  const out: Record<string, number> = {}
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    const n = typeof v === 'number' ? v : Number(v)
    out[k] = Number.isFinite(n) ? n : 0
  }
  return Object.keys(out).length ? out : { train: 0.7, val: 0.15, test: 0.15 }
}

function sumOf(ratios: Record<string, number>): number {
  return Object.values(ratios).reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0)
}

export function SplitRatiosEditor({
  value,
  onChange,
  invalid,
}: {
  value: unknown
  onChange: (v: unknown) => void
  invalid?: boolean
}) {
  const ratios = asRatios(value)
  const keys = Object.keys(ratios)
  const hasCustom = keys.some((k) => !STANDARD.includes(k as (typeof STANDARD)[number]))
  const [jsonMode, setJsonMode] = React.useState(false)
  const [jsonDraft, setJsonDraft] = React.useState('')
  const [jsonError, setJsonError] = React.useState<string | null>(null)
  const [customMode, setCustomMode] = React.useState(hasCustom)

  const sum = sumOf(ratios)
  const sumOk = Math.abs(sum - 1) < 0.011

  const setKey = (key: string, raw: string) => {
    const n = Number(raw)
    onChange({ ...ratios, [key]: Number.isFinite(n) ? n : 0 })
  }

  const renameKey = (oldKey: string, nextKey: string) => {
    const k = nextKey.trim()
    if (!k || k === oldKey) return
    if (k in ratios && k !== oldKey) return
    const next: Record<string, number> = {}
    for (const [kk, vv] of Object.entries(ratios)) {
      next[kk === oldKey ? k : kk] = vv
    }
    onChange(next)
  }

  const removeKey = (key: string) => {
    const next = { ...ratios }
    delete next[key]
    onChange(next)
  }

  const addKey = () => {
    let i = 1
    let name = `split_${i}`
    while (name in ratios) {
      i += 1
      name = `split_${i}`
    }
    onChange({ ...ratios, [name]: 0 })
  }

  const toStandard = () => {
    setCustomMode(false)
    onChange({
      train: ratios.train ?? 0.7,
      val: ratios.val ?? 0.15,
      test: ratios.test ?? 0.15,
    })
  }

  const enterJson = () => {
    setJsonDraft(JSON.stringify(ratios, null, 2))
    setJsonError(null)
    setJsonMode(true)
  }

  const applyJson = () => {
    try {
      const parsed = JSON.parse(jsonDraft) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Root must be a JSON object')
      }
      const next = asRatios(parsed)
      onChange(next)
      setCustomMode(Object.keys(next).some((k) => !STANDARD.includes(k as (typeof STANDARD)[number])))
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
          rows={6}
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

  const showCustom = customMode || hasCustom

  return (
    <div className={`mt-1 space-y-1.5${invalid ? ' rounded-lg ring-1 ring-rose-300 p-1' : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <span className={`text-[10px] ${sumOk ? 'text-ink-500' : 'font-medium text-amber-800'}`}>
          Sum {sum.toFixed(3)}
          {sumOk ? ' · OK' : ' · should be ≈ 1.0'}
        </span>
        <div className="flex items-center gap-2">
          {showCustom ? (
            <button
              type="button"
              className="text-[10px] font-medium text-ink-500 underline-offset-2 hover:text-ink-800 hover:underline"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={toStandard}
            >
              Use train/val/test
            </button>
          ) : (
            <button
              type="button"
              className="text-[10px] font-medium text-ink-500 underline-offset-2 hover:text-ink-800 hover:underline"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => setCustomMode(true)}
            >
              Custom keys
            </button>
          )}
          <button
            type="button"
            className="text-[10px] font-medium text-ink-500 underline-offset-2 hover:text-ink-800 hover:underline"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={enterJson}
          >
            Edit as JSON
          </button>
        </div>
      </div>

      {!showCustom ? (
        <div className="grid grid-cols-3 gap-1.5">
          {STANDARD.map((k) => (
            <label key={k} className="block text-[10px] text-ink-600">
              {k}
              <input
                type="number"
                step={0.01}
                min={0}
                max={1}
                className="field-control mt-0.5 py-1 font-mono text-[11px]"
                value={ratios[k] ?? 0}
                onChange={(e) => setKey(k, e.target.value)}
                onMouseDown={(e) => e.stopPropagation()}
              />
            </label>
          ))}
        </div>
      ) : (
        <ul className="space-y-1">
          {keys.map((k) => (
            <li key={k} className="flex items-center gap-1">
              <input
                type="text"
                className="field-control max-w-[7rem] py-1 font-mono text-[11px]"
                value={k}
                onChange={(e) => renameKey(k, e.target.value)}
                onMouseDown={(e) => e.stopPropagation()}
                aria-label="Split name"
              />
              <input
                type="number"
                step={0.01}
                min={0}
                className="field-control flex-1 py-1 font-mono text-[11px]"
                value={ratios[k] ?? 0}
                onChange={(e) => setKey(k, e.target.value)}
                onMouseDown={(e) => e.stopPropagation()}
                aria-label={`Weight for ${k}`}
              />
              <button
                type="button"
                className="btn-icon !h-7 !w-7 text-rose-600"
                aria-label={`Remove ${k}`}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => removeKey(k)}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </li>
          ))}
          <li>
            <button
              type="button"
              className="inline-flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-ink-300 bg-white px-2 py-1 text-[11px] font-medium text-ink-700 hover:bg-ink-50"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={addKey}
            >
              <Plus className="h-3.5 w-3.5" />
              Add split
            </button>
          </li>
        </ul>
      )}
    </div>
  )
}
