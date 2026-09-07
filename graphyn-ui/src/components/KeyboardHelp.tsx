import React from 'react'
import { X } from 'lucide-react'

const SECTIONS: Array<{ title: string; rows: Array<{ keys: string; action: string }> }> = [
  {
    title: 'Navigation',
    rows: [
      { keys: 'B', action: 'Builder' },
      { keys: 'T', action: 'Templates' },
      { keys: 'P', action: 'Proposals' },
      { keys: 'R', action: 'Runs' },
      { keys: 'O', action: 'Trace' },
      { keys: 'E', action: 'Experiments' },
      { keys: 'A', action: 'Artifacts' },
      { keys: 'D', action: 'Data' },
      { keys: 'G', action: 'Edge deploy' },
      { keys: 'W', action: 'Workers' },
      { keys: 'L', action: 'Plugins' },
      { keys: 'S', action: 'System' },
    ],
  },
  {
    title: 'Builder',
    rows: [
      { keys: '/ or ⌘/Ctrl+K', action: 'Focus node catalog search' },
      { keys: 'Drag from handle', action: 'Connect nodes (ports show type on hover)' },
      { keys: 'Delete / Backspace', action: 'Remove selected node or edge' },
      { keys: 'Click canvas', action: 'Clear selection / show graph settings' },
      { keys: 'Esc', action: 'Close menus / disarm Confirm' },
    ],
  },
  {
    title: 'General',
    rows: [
      { keys: '?', action: 'Show this keyboard help' },
      { keys: 'Esc', action: 'Close this overlay / Settings' },
    ],
  },
]

export function KeyboardHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  React.useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center bg-ink-950/40 p-4 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="keyboard-help-title"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-ink-200 bg-white p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 id="keyboard-help-title" className="text-type-page text-ink-950">
              Keyboard shortcuts
            </h2>
            <p className="mt-1 text-type-secondary text-ink-500">
              Jump keys work when you are not typing in a field. Press Esc to close.
            </p>
          </div>
          <button type="button" className="btn-icon" aria-label="Close keyboard help" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-4">
          {SECTIONS.map((section) => (
            <section key={section.title}>
              <h3 className="mb-2 text-type-section text-ink-800">{section.title}</h3>
              <ul className="divide-y divide-ink-100 overflow-hidden rounded-xl border border-ink-100">
                {section.rows.map((row) => (
                  <li
                    key={`${section.title}-${row.keys}`}
                    className="flex items-center justify-between gap-3 bg-white px-3 py-2 text-type-body"
                  >
                    <span className="text-ink-700">{row.action}</span>
                    <kbd className="shrink-0 rounded-md border border-ink-200 bg-ink-50 px-2 py-0.5 font-mono text-type-mono text-ink-800">
                      {row.keys}
                    </kbd>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        <p className="mt-4 text-type-meta text-ink-400">
          Tip: press <kbd className="rounded border border-ink-200 bg-ink-50 px-1 font-mono">?</kbd> anytime to
          reopen this overlay.
        </p>
      </div>
    </div>
  )
}
