import React from 'react'
import { Check, ChevronDown } from 'lucide-react'

/**
 * Editor toolbar document identity: the editable pipeline name (Save / Run
 * slug) with a chevron that opens the workspace's saved pipelines — one place
 * for "which pipeline is this" instead of a workspace chip + Open dropdown +
 * Name field.
 */
export function PipelineSwitcher({
  name,
  onNameChange,
  onNameCommit,
  pipelines,
  current,
  onOpen,
}: {
  name: string
  onNameChange: (next: string) => void
  onNameCommit: () => void
  /** Saved pipeline names in the workspace. */
  pipelines: string[]
  /** Saved pipeline currently open on the canvas ('' = not a saved pipeline). */
  current: string
  onOpen: (name: string) => void
}) {
  const [open, setOpen] = React.useState(false)
  const rootRef = React.useRef<HTMLDivElement | null>(null)

  React.useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as HTMLElement)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  // Grow with the name (no fixed tiny box), within sane limits.
  const widthCh = Math.min(32, Math.max(8, name.length + 1))

  return (
    <div ref={rootRef} className="relative flex min-w-0 items-center">
      <div className="flex min-w-0 items-center rounded-lg border border-transparent hover:border-ink-200/80 focus-within:border-accent-400 focus-within:bg-white focus-within:ring-2 focus-within:ring-accent-200/70">
        <input
          value={name}
          onChange={(e) => onNameChange(e.target.value.replace(/[^A-Za-z0-9_-]/g, '-'))}
          onBlur={onNameCommit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
          }}
          placeholder="pipeline-name"
          style={{ width: `${widthCh}ch` }}
          className="min-w-0 max-w-[40vw] rounded-lg bg-transparent px-2 py-1 text-[15px] font-semibold text-ink-950 outline-none"
          title={
            current
              ? `Pipeline name (Save and Run use it) — saved pipeline “${current}”`
              : 'Pipeline name (Save and Run use it) — not saved in this workspace yet'
          }
          aria-label="Pipeline name"
        />
        <button
          type="button"
          className="btn-icon h-7 w-7 shrink-0"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label="Switch pipeline"
          title="Open another saved pipeline"
          onClick={() => setOpen((v) => !v)}
        >
          <ChevronDown className="h-4 w-4" />
        </button>
      </div>
      {open ? (
        <div
          className="absolute left-0 top-full z-50 mt-1 w-64 rounded-xl border border-ink-200 bg-white p-1.5 shadow-soft"
          role="listbox"
          aria-label="Saved pipelines"
        >
          <div className="px-2 pb-1 pt-0.5 text-[11px] font-medium text-ink-400">Open pipeline</div>
          {pipelines.length === 0 ? (
            <div className="px-2 py-2 text-[12px] text-ink-500">No saved pipelines yet — Save to create one.</div>
          ) : (
            <div className="max-h-72 overflow-y-auto">
              {pipelines.map((p) => (
                <button
                  key={p}
                  type="button"
                  role="option"
                  aria-selected={p === current}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] text-ink-800 hover:bg-ink-50"
                  onClick={() => {
                    setOpen(false)
                    onOpen(p)
                  }}
                >
                  <span className="min-w-0 flex-1 truncate">{p}</span>
                  {p === current ? <Check className="h-3.5 w-3.5 shrink-0 text-accent-700" /> : null}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
