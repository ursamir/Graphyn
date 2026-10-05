/**
 * Responsive action row: never clips buttons.
 *
 *   <ActionBar
 *     primary={<button className="btn-primary">Run</button>}     // always visible
 *     secondary={<><button …>Export</button><button …>Share</button></>}
 *                       // inline when the bar is ≥ `collapseBelow` px wide,
 *                       // otherwise moved into the "More" (⋯) menu
 *     overflow={<button …>Delete</button>}                      // always in the menu
 *   />
 *
 * Without `overflow`/narrow width it is simply a wrapping flex row
 * (`.action-bar` in index.css), so it is safe as a drop-in for header action
 * slots (ViewShell / DetailChrome `actions`). Menu items keep their own
 * onClick; the menu closes after any button click inside it.
 */
import React from 'react'
import clsx from 'clsx'
import { MoreHorizontal } from 'lucide-react'
import { useElementWidth } from '../lib/viewport'
import { useMenuDismiss } from '../lib/menus'

type ActionBarProps = {
  primary?: React.ReactNode
  secondary?: React.ReactNode
  overflow?: React.ReactNode
  /** Container width (px) below which `secondary` moves into the menu. */
  collapseBelow?: number
  /** Accessible name of the overflow trigger. */
  moreLabel?: string
  className?: string
}

export function ActionBar({
  primary,
  secondary,
  overflow,
  collapseBelow = 420,
  moreLabel = 'More actions',
  className,
}: ActionBarProps) {
  const [ref, width] = useElementWidth<HTMLDivElement>()
  const [open, setOpen] = React.useState(false)
  const menuRef = React.useRef<HTMLDivElement>(null)
  const close = React.useCallback(() => setOpen(false), [])
  useMenuDismiss(open, close, menuRef)

  const secondaryInMenu = Boolean(secondary) && width > 0 && width < collapseBelow
  const hasMenu = Boolean(overflow) || secondaryInMenu

  return (
    <div ref={ref} className={clsx('action-bar', className)}>
      {secondary && !secondaryInMenu ? secondary : null}
      {primary}
      {hasMenu ? (
        <div ref={menuRef} className="relative">
          <button
            type="button"
            className="btn-quiet !px-1.5"
            aria-haspopup="menu"
            aria-expanded={open}
            aria-label={moreLabel}
            title={moreLabel}
            onClick={() => setOpen((o) => !o)}
          >
            <MoreHorizontal className="h-4 w-4" />
          </button>
          {open ? (
            <div
              role="menu"
              className="absolute right-0 top-full z-40 mt-1 flex min-w-[10rem] flex-col items-stretch gap-1 rounded-xl border border-ink-200 bg-white p-1.5 shadow-lg [&>button]:justify-start"
              onClick={(e) => {
                if ((e.target as HTMLElement).closest('button, a')) setOpen(false)
              }}
            >
              {secondaryInMenu ? secondary : null}
              {overflow}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
