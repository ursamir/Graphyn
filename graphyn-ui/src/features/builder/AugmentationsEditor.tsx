/** Structured editor for augmentation_pipeline `augmentations` (replaces raw JSON textarea). */

import React from 'react'
import { ChevronDown, ChevronUp, Plus, Trash2 } from 'lucide-react'

const AUG_TYPES = [
  'gain',
  'pitch_shift',
  'time_stretch',
  'speed_perturb',
  'reverb',
  'noise_inject',
  'codec_degrade',
  'eq',
  'audiomentations',
] as const

type AugType = (typeof AUG_TYPES)[number]

type AugSpec = Record<string, unknown> & { type: string; apply_prob?: number }

type FieldKind = 'number' | 'text' | 'range2' | 'select'

type FieldDef = {
  key: string
  label: string
  kind: FieldKind
  options?: string[]
  placeholder?: string
}

const FIELDS_BY_TYPE: Record<AugType, FieldDef[]> = {
  gain: [{ key: 'gain_db', label: 'Gain dB [min, max]', kind: 'range2', placeholder: '-6, 6' }],
  pitch_shift: [
    { key: 'semitones', label: 'Semitones [min, max]', kind: 'range2', placeholder: '-2, 2' },
  ],
  time_stretch: [{ key: 'rate', label: 'Rate [min, max]', kind: 'range2', placeholder: '0.9, 1.1' }],
  speed_perturb: [
    { key: 'speed_factor', label: 'Speed [min, max]', kind: 'range2', placeholder: '0.9, 1.1' },
  ],
  reverb: [
    {
      key: 'impulse_response_path',
      label: 'IR directory',
      kind: 'text',
      placeholder: '/path/to/irs',
    },
  ],
  noise_inject: [{ key: 'snr_db', label: 'SNR dB [min, max]', kind: 'range2', placeholder: '5, 20' }],
  codec_degrade: [
    { key: 'codec', label: 'Codec', kind: 'select', options: ['mp3', 'ogg', 'opus'] },
    { key: 'bitrate', label: 'Bitrate', kind: 'number', placeholder: '32' },
  ],
  eq: [], // bands edited separately
  audiomentations: [
    {
      key: 'transform',
      label: 'Transform class',
      kind: 'text',
      placeholder: 'AddGaussianNoise',
    },
  ],
}

function asAugs(value: unknown): AugSpec[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((x): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x))
    .map((x) => ({ ...x, type: String(x.type || 'gain') }))
}

function defaultAug(type: AugType = 'gain'): AugSpec {
  const base: AugSpec = { type, apply_prob: 0.5 }
  switch (type) {
    case 'gain':
      return { ...base, gain_db: [-6, 6] }
    case 'pitch_shift':
      return { ...base, apply_prob: 0.3, semitones: [-2, 2] }
    case 'time_stretch':
      return { ...base, apply_prob: 0.3, rate: [0.9, 1.1] }
    case 'speed_perturb':
      return { ...base, apply_prob: 0.3, speed_factor: [0.9, 1.1] }
    case 'reverb':
      return { ...base, apply_prob: 0.3, impulse_response_path: '' }
    case 'noise_inject':
      return { ...base, apply_prob: 0.3, snr_db: [5, 20] }
    case 'codec_degrade':
      return { ...base, apply_prob: 0.2, codec: 'mp3', bitrate: 32 }
    case 'eq':
      return {
        ...base,
        apply_prob: 0.2,
        bands: [{ freq: 1000, gain_db: 3, q: 1.0 }],
      }
    case 'audiomentations':
      return {
        ...base,
        transform: 'AddGaussianNoise',
        min_amplitude: 0.001,
        max_amplitude: 0.015,
      }
    default:
      return base
  }
}

function rangeDisplay(v: unknown): string {
  if (Array.isArray(v) && v.length >= 2) return `${v[0]}, ${v[1]}`
  if (v == null) return ''
  return String(v)
}

function parseRange2(raw: string): [number, number] | string {
  const parts = raw.split(/[\s,]+/).filter(Boolean)
  if (parts.length < 2) return raw
  const a = Number(parts[0])
  const b = Number(parts[1])
  if (!Number.isFinite(a) || !Number.isFinite(b)) return raw
  return [a, b]
}

function augSummary(aug: AugSpec): string {
  const t = String(aug.type || '?')
  const p = aug.apply_prob != null ? `p=${aug.apply_prob}` : ''
  const bits = [t, p].filter(Boolean)
  if (Array.isArray(aug.gain_db)) bits.push(`dB=${aug.gain_db[0]}…${aug.gain_db[1]}`)
  if (Array.isArray(aug.semitones)) bits.push(`st=${aug.semitones[0]}…${aug.semitones[1]}`)
  if (Array.isArray(aug.rate)) bits.push(`rate=${aug.rate[0]}…${aug.rate[1]}`)
  if (Array.isArray(aug.speed_factor)) bits.push(`spd=${aug.speed_factor[0]}…${aug.speed_factor[1]}`)
  if (Array.isArray(aug.snr_db)) bits.push(`snr=${aug.snr_db[0]}…${aug.snr_db[1]}`)
  if (aug.codec != null) bits.push(String(aug.codec))
  if (aug.transform != null) bits.push(String(aug.transform))
  if (Array.isArray(aug.bands)) bits.push(`${aug.bands.length} band${aug.bands.length === 1 ? '' : 's'}`)
  return bits.join(' · ')
}

type EqBand = { freq: number; gain_db: number; q: number }

function asBands(v: unknown): EqBand[] {
  if (!Array.isArray(v)) return []
  return v
    .filter((x): x is Record<string, unknown> => !!x && typeof x === 'object')
    .map((x) => ({
      freq: Number(x.freq) || 1000,
      gain_db: Number(x.gain_db) || 0,
      q: Number(x.q) || 1,
    }))
}

export function AugmentationsEditor({
  value,
  onChange,
  invalid,
}: {
  value: unknown
  onChange: (v: unknown) => void
  invalid?: boolean
}) {
  const augs = asAugs(value)
  const [openIdx, setOpenIdx] = React.useState<number | null>(augs.length ? 0 : null)
  const [jsonMode, setJsonMode] = React.useState(false)
  const [jsonDraft, setJsonDraft] = React.useState('')
  const [jsonError, setJsonError] = React.useState<string | null>(null)

  const commit = (next: AugSpec[]) => onChange(next)

  const updateAt = (i: number, patch: Record<string, unknown>) => {
    commit(augs.map((a, idx) => (idx === i ? { ...a, ...patch } : a)))
  }

  const setType = (i: number, type: AugType) => {
    commit(augs.map((a, idx) => (idx === i ? defaultAug(type) : a)))
  }

  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir
    if (j < 0 || j >= augs.length) return
    const next = augs.slice()
    const [row] = next.splice(i, 1)
    next.splice(j, 0, row)
    commit(next)
    setOpenIdx(j)
  }

  const remove = (i: number) => {
    const next = augs.filter((_, idx) => idx !== i)
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
    const next = [...augs, defaultAug('gain')]
    commit(next)
    setOpenIdx(next.length - 1)
  }

  const enterJson = () => {
    setJsonDraft(JSON.stringify(augs, null, 2))
    setJsonError(null)
    setJsonMode(true)
  }

  const applyJson = () => {
    try {
      const parsed = JSON.parse(jsonDraft) as unknown
      if (!Array.isArray(parsed)) throw new Error('Root must be a JSON array')
      commit(asAugs(parsed))
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
          {augs.length} augmentation{augs.length === 1 ? '' : 's'}
          {augs.length === 0 ? ' — empty list keeps copies unmodified' : ''}
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
        {augs.map((aug, i) => {
          const t = (AUG_TYPES.includes(aug.type as AugType) ? aug.type : 'gain') as AugType
          const open = openIdx === i
          const fields = FIELDS_BY_TYPE[t] ?? []
          const bands = t === 'eq' ? asBands(aug.bands) : []
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
                  {augSummary(aug)}
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
                  disabled={i === augs.length - 1}
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={() => move(i, 1)}
                >
                  <ChevronDown className="h-3 w-3" />
                </button>
                <button
                  type="button"
                  className="btn-icon !h-6 !w-6 text-rose-600"
                  aria-label="Remove augmentation"
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
                      className="field-control mt-0.5"
                      value={t}
                      onChange={(e) => setType(i, e.target.value as AugType)}
                      onMouseDown={(e) => e.stopPropagation()}
                    >
                      {AUG_TYPES.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-[10px] text-ink-600">
                    Apply probability
                    <input
                      type="number"
                      className="field-control mt-0.5"
                      min={0}
                      max={1}
                      step={0.05}
                      value={aug.apply_prob ?? 0.5}
                      onChange={(e) => {
                        const n = Number(e.target.value)
                        updateAt(i, { apply_prob: Number.isFinite(n) ? n : 0.5 })
                      }}
                      onMouseDown={(e) => e.stopPropagation()}
                    />
                  </label>
                  {fields.map((f) => (
                    <label key={f.key} className="block text-[10px] text-ink-600">
                      {f.label}
                      {f.kind === 'select' ? (
                        <select
                          className="field-control mt-0.5"
                          value={String(aug[f.key] ?? f.options?.[0] ?? '')}
                          onChange={(e) => updateAt(i, { [f.key]: e.target.value })}
                          onMouseDown={(e) => e.stopPropagation()}
                        >
                          {(f.options ?? []).map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      ) : f.kind === 'range2' ? (
                        <input
                          type="text"
                          className="field-control mt-0.5 font-mono text-[11px]"
                          value={rangeDisplay(aug[f.key])}
                          placeholder={f.placeholder}
                          onChange={(e) => {
                            const parsed = parseRange2(e.target.value)
                            updateAt(i, { [f.key]: parsed })
                          }}
                          onMouseDown={(e) => e.stopPropagation()}
                        />
                      ) : f.kind === 'number' ? (
                        <input
                          type="number"
                          className="field-control mt-0.5"
                          value={aug[f.key] == null ? '' : String(aug[f.key])}
                          placeholder={f.placeholder}
                          onChange={(e) => {
                            const n = Number(e.target.value)
                            updateAt(i, { [f.key]: Number.isFinite(n) ? n : e.target.value })
                          }}
                          onMouseDown={(e) => e.stopPropagation()}
                        />
                      ) : (
                        <input
                          type="text"
                          className="field-control mt-0.5 font-mono text-[11px]"
                          value={aug[f.key] == null ? '' : String(aug[f.key])}
                          placeholder={f.placeholder}
                          onChange={(e) => updateAt(i, { [f.key]: e.target.value })}
                          onMouseDown={(e) => e.stopPropagation()}
                        />
                      )}
                    </label>
                  ))}
                  {t === 'eq' ? (
                    <div className="space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-medium text-ink-600">EQ bands</span>
                        <button
                          type="button"
                          className="text-[10px] font-medium text-ink-600 hover:underline"
                          onMouseDown={(e) => e.stopPropagation()}
                          onClick={() =>
                            updateAt(i, {
                              bands: [...bands, { freq: 1000, gain_db: 3, q: 1.0 }],
                            })
                          }
                        >
                          + band
                        </button>
                      </div>
                      {bands.map((band, bi) => (
                        <div key={bi} className="flex items-end gap-1">
                          <label className="block flex-1 text-[10px] text-ink-500">
                            Freq
                            <input
                              type="number"
                              className="field-control mt-0.5 py-1"
                              value={band.freq}
                              onChange={(e) => {
                                const next = bands.slice()
                                next[bi] = { ...band, freq: Number(e.target.value) || 0 }
                                updateAt(i, { bands: next })
                              }}
                              onMouseDown={(e) => e.stopPropagation()}
                            />
                          </label>
                          <label className="block flex-1 text-[10px] text-ink-500">
                            Gain dB
                            <input
                              type="number"
                              className="field-control mt-0.5 py-1"
                              value={band.gain_db}
                              onChange={(e) => {
                                const next = bands.slice()
                                next[bi] = { ...band, gain_db: Number(e.target.value) || 0 }
                                updateAt(i, { bands: next })
                              }}
                              onMouseDown={(e) => e.stopPropagation()}
                            />
                          </label>
                          <label className="block flex-1 text-[10px] text-ink-500">
                            Q
                            <input
                              type="number"
                              className="field-control mt-0.5 py-1"
                              value={band.q}
                              step={0.1}
                              onChange={(e) => {
                                const next = bands.slice()
                                next[bi] = { ...band, q: Number(e.target.value) || 1 }
                                updateAt(i, { bands: next })
                              }}
                              onMouseDown={(e) => e.stopPropagation()}
                            />
                          </label>
                          <button
                            type="button"
                            className="btn-icon !h-7 !w-7 text-rose-600"
                            aria-label="Remove band"
                            onMouseDown={(e) => e.stopPropagation()}
                            onClick={() =>
                              updateAt(i, { bands: bands.filter((_, idx) => idx !== bi) })
                            }
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {t === 'audiomentations' ? (
                    <p className="text-[10px] leading-snug text-ink-400">
                      Extra transform kwargs (min_amplitude, etc.) stay in the object — use Edit as
                      JSON for advanced params.
                    </p>
                  ) : null}
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
        Add augmentation
      </button>
    </div>
  )
}
