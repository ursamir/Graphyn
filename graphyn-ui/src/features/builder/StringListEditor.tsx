/** Structured editor for string-array config fields (e.g. python_code `allowed_paths`). */

import React from 'react'
import { Plus, Trash2 } from 'lucide-react'

function asStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((x) => (x == null ? '' : String(x)))
}

export function StringListEditor({
  value,
  onChange,
  invalid,
  placeholder = 'path or glob',
  emptyHint = 'No entries — add a path or leave empty',
}: {
  value: unknown
  onChange: (v: unknown) => void
  invalid?: boolean
  placeholder?: string
  emptyHint?: string
}) {
  const items = asStrings(value)
  const [jsonMode, setJsonMode] = React.useState(false)
  const [jsonDraft, setJsonDraft] = React.useState('')
  const [jsonError, setJsonError] = React.useState<string | null>(null)

  const commit = (next: string[]) => onChange(next)

  const enterJson = () => {
    setJsonDraft(JSON.stringify(items, null, 2))
    setJsonError(null)
    setJsonMode(true)
  }

  const applyJson = () => {
    try {
      const parsed = JSON.parse(jsonDraft) as unknown
      if (!Array.isArray(parsed)) throw new Error('Root must be a JSON array of strings')
      commit(parsed.map((x) => (x == null ? '' : String(x))))
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

  return (
    <div className={`mt-1 space-y-1.5${invalid ? ' rounded-lg ring-1 ring-rose-300 p-1' : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-ink-500">
          {items.length} entr{items.length === 1 ? 'y' : 'ies'}
          {items.length === 0 ? ` — ${emptyHint}` : ''}
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

      <ul className="space-y-1">
        {items.map((item, i) => (
          <li key={i} className="flex items-center gap-1">
            <input
              type="text"
              className="field-control flex-1 py-1 font-mono text-[11px]"
              value={item}
              placeholder={placeholder}
              onChange={(e) => {
                const next = items.slice()
                next[i] = e.target.value
                commit(next)
              }}
              onMouseDown={(e) => e.stopPropagation()}
            />
            <button
              type="button"
              className="btn-icon !h-7 !w-7 text-rose-600"
              aria-label="Remove entry"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => commit(items.filter((_, idx) => idx !== i))}
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </li>
        ))}
      </ul>

      <button
        type="button"
        className="inline-flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-ink-300 bg-white px-2 py-1.5 text-[11px] font-medium text-ink-700 hover:bg-ink-50"
        onMouseDown={(e) => e.stopPropagation()}
        onClick={() => commit([...items, ''])}
      >
        <Plus className="h-3.5 w-3.5" />
        Add path
      </button>
    </div>
  )
}
