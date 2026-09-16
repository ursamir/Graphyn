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
  minSize = 260,
  maxSize = 640,
  className,
  masterClassName,
  detailClassName,
  orientation: orientationProp,
  collapsible = false,
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
            aria-label="Show run list"
            title="Show run list"
            onClick={() => setCollapsed(false)}
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </div>
        <div className={clsx('h-full min-h-0 min-w-0 flex-1 space-y-3 overflow-y-auto p-5', detailClassName)}>
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
            'relative h-full min-h-0 overflow-y-auto bg-white/40',
            stacked ? 'px-5 py-3' : 'p-5',
            masterClassName,
          )}
        >
          {collapsible && orientation === 'horizontal' ? (
            <button
              type="button"
              className="btn-quiet absolute right-2 top-2 z-[1] !px-1.5 !py-1"
              aria-label="Hide run list"
              title="Hide run list"
              onClick={() => setCollapsed(true)}
            >
              <PanelLeftClose className="h-3.5 w-3.5" />
            </button>
          ) : null}
          {master}
        </div>,
        <div
          key="detail"
          className={clsx('h-full min-h-0 space-y-3 overflow-y-auto p-5', detailClassName)}
        >
          {detail}
        </div>,
      ]}
    </SplitPane>
  )
}
