/**
 * App-wide Master | Detail (or stacked Container | Content) pane.
 * Divider width uses LAYOUT_KEYS.master by default so screens stay synced.
 * Optional collapse hides the master list so the detail pane can use full width.
 */
import React from 'react'
import clsx from 'clsx'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { SplitPane } from '../components/SplitPane'
import { LAYOUT_KEYS } from './keys'
import { useLayoutPrefs } from './useLayoutPrefs'

type MasterDetailProps = {
  master: React.ReactNode
  detail: React.ReactNode
  /** Override storage key (rare). Default: shared app master width. */
  storageKey?: string
  defaultSize?: number
  minSize?: number
  maxSize?: number
  className?: string
  masterClassName?: string
  detailClassName?: string
  /** Force orientation; otherwise follows layout mode. */
  orientation?: 'horizontal' | 'vertical'
  /** Allow collapsing the master list to give detail more room. */
  collapsible?: boolean
  /** Accessible name for the master list (collapse controls). */
  listLabel?: string
}

function readCollapsed(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

export function MasterDetail({
  master,
  detail,
  storageKey,
  defaultSize = 360,
  minSize = 280,
  maxSize = 640,
  className,
  masterClassName,
  detailClassName,
  orientation: orientationProp,
  collapsible = false,
  listLabel = 'list',
}: MasterDetailProps) {
  const { mode } = useLayoutPrefs()
  const stacked = mode === 'container-content'
  const orientation = orientationProp ?? (stacked ? 'vertical' : 'horizontal')
  const key =
    storageKey ?? (orientation === 'vertical' ? LAYOUT_KEYS.stack : LAYOUT_KEYS.master)
  const collapsedKey = `${key}.collapsed`
  const [collapsed, setCollapsed] = React.useState(() =>
    collapsible ? readCollapsed(collapsedKey) : false,
  )
  const sizeDefaults =
    orientation === 'vertical'
      ? { defaultSize: defaultSize === 360 ? 220 : defaultSize, minSize: Math.min(minSize, 120), maxSize: 420 }
      : { defaultSize, minSize, maxSize }

  React.useEffect(() => {
    if (!collapsible) return
    try {
      localStorage.setItem(collapsedKey, collapsed ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [collapsed, collapsedKey, collapsible])

  if (collapsible && collapsed && orientation === 'horizontal') {
    return (
      <div className={clsx('flex h-full min-h-0', className)}>
        <div className="flex w-9 shrink-0 flex-col items-center border-r border-ink-200/80 bg-white/60 py-2">
          <button
            type="button"
            className="btn-quiet !px-1.5 !py-1.5"
            aria-label={`Show ${listLabel}`}
            title={`Show ${listLabel}`}
            onClick={() => setCollapsed(false)}
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </div>
        <div className={clsx('h-full min-h-0 min-w-0 flex-1 space-y-2 overflow-y-auto p-3', detailClassName)}>
          {detail}
        </div>
      </div>
    )
  }

  return (
    <SplitPane
      className={clsx('h-full min-h-0', className)}
      orientation={orientation}
      storageKey={key}
      defaultSize={sizeDefaults.defaultSize}
      minSize={sizeDefaults.minSize}
      maxSize={sizeDefaults.maxSize}
      paneOverflow="hidden"
    >
      {[
        <div
          key="master"
          className={clsx(
            'relative h-full min-h-0 overflow-y-auto bg-white [scrollbar-gutter:stable]',
            stacked ? 'px-3 py-2' : 'p-3',
            collapsible && orientation === 'horizontal' && 'pr-9',
            masterClassName,
          )}
        >
          {collapsible && orientation === 'horizontal' ? (
            <button
              type="button"
              className="btn-quiet absolute right-1.5 top-1.5 z-[1] !px-1.5 !py-1"
              aria-label={`Hide ${listLabel}`}
              title={`Hide ${listLabel}`}
              onClick={() => setCollapsed(true)}
            >
              <PanelLeftClose className="h-3.5 w-3.5" />
            </button>
          ) : null}
          {master}
        </div>,
        <div
          key="detail"
          className={clsx(
            'h-full min-h-0 min-w-0 space-y-2 overflow-y-auto p-3 [scrollbar-gutter:stable]',
            detailClassName,
          )}
        >
          {detail}
        </div>,
      ]}
    </SplitPane>
  )
}
