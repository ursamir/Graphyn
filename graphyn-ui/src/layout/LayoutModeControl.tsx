/**
 * Header control: switch Master–Detail ↔ Container–Content for the console.
 */
import { Columns2, Rows2 } from 'lucide-react'
import clsx from 'clsx'
import { useLayoutPrefs } from './useLayoutPrefs'

export function LayoutModeControl({ className }: { className?: string }) {
  const { mode, setMode } = useLayoutPrefs()

  return (
    <div
      className={clsx(
        'inline-flex items-center rounded-full border border-ink-200 bg-white p-0.5',
        className,
      )}
      role="group"
      aria-label="Content layout"
      title="Master–Detail (side-by-side) or Container–Content (stacked). Divider width is remembered."
    >
      <button
        type="button"
        className={clsx(
          'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium transition',
          mode === 'master-detail'
            ? 'bg-ink-900 text-white'
            : 'text-ink-500 hover:text-ink-800',
        )}
        aria-pressed={mode === 'master-detail'}
        onClick={() => setMode('master-detail')}
      >
        <Columns2 className="h-3 w-3" />
        <span className="hidden lg:inline">Master</span>
      </button>
      <button
        type="button"
        className={clsx(
          'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium transition',
          mode === 'container-content'
            ? 'bg-ink-900 text-white'
            : 'text-ink-500 hover:text-ink-800',
        )}
        aria-pressed={mode === 'container-content'}
        onClick={() => setMode('container-content')}
      >
        <Rows2 className="h-3 w-3" />
        <span className="hidden lg:inline">Stack</span>
      </button>
    </div>
  )
}
