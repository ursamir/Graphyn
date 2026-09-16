/**
 * Horizontal or vertical resizable split pane. Width/height persisted when storageKey set.
 * Same storageKey instances stay in sync via localStorage + graphyn:layout-split.
 */
import React from 'react'
import clsx from 'clsx'
import { LAYOUT_SPLIT_EVENT } from '../layout/keys'

type SplitPaneProps = {
  children: [React.ReactNode, React.ReactNode]
  /** Primary pane size in px (left for horizontal, top for vertical). */
  defaultSize?: number
  minSize?: number
  maxSize?: number
  orientation?: 'horizontal' | 'vertical'
  storageKey?: string
  className?: string
  /** Extra class on the drag handle. */
  handleClassName?: string
  /**
   * Overflow for both panes. Use `hidden` when children manage their own scroll
   * (App shell, Builder) so the page never grows past the viewport.
   */
  paneOverflow?: 'auto' | 'hidden'
}

function readStored(key: string | undefined, fallback: number): number {
  if (!key) return fallback
  try {
    const raw = localStorage.getItem(key)
    const n = raw != null ? Number(raw) : NaN
    return Number.isFinite(n) && n > 0 ? n : fallback
  } catch {
    return fallback
  }
}

export function SplitPane({
  children,
  defaultSize = 320,
  minSize = 180,
  maxSize = 720,
  orientation = 'horizontal',
  storageKey,
  className,
  handleClassName,
  paneOverflow = 'auto',
}: SplitPaneProps) {
  const [size, setSize] = React.useState(() => readStored(storageKey, defaultSize))
  const dragging = React.useRef(false)
  const startPos = React.useRef(0)
  const startSize = React.useRef(size)
  const skipBroadcast = React.useRef(false)

  const clamp = React.useCallback(
    (n: number) => Math.max(minSize, Math.min(maxSize, n)),
    [minSize, maxSize],
  )

  React.useEffect(() => {
    if (!storageKey) return
    try {
      localStorage.setItem(storageKey, String(Math.round(size)))
    } catch {
      /* ignore */
    }
    if (skipBroadcast.current) {
      skipBroadcast.current = false
      return
    }
    window.dispatchEvent(
      new CustomEvent(LAYOUT_SPLIT_EVENT, { detail: { key: storageKey, size: Math.round(size) } }),
    )
  }, [size, storageKey])

  React.useEffect(() => {
    if (!storageKey) return
    const apply = (next: number) => {
      if (!Number.isFinite(next) || next <= 0) return
      const c = clamp(next)
      skipBroadcast.current = true
      setSize(c)
    }
    const onStorage = (e: StorageEvent) => {
      if (e.key === storageKey && e.newValue != null) apply(Number(e.newValue))
    }
    const onCustom = (e: Event) => {
      const detail = (e as CustomEvent<{ key?: string; size?: number }>).detail
      if (detail?.key === storageKey && typeof detail.size === 'number') apply(detail.size)
    }
    window.addEventListener('storage', onStorage)
    window.addEventListener(LAYOUT_SPLIT_EVENT, onCustom)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(LAYOUT_SPLIT_EVENT, onCustom)
    }
  }, [storageKey, clamp])

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    dragging.current = true
    startPos.current = orientation === 'horizontal' ? e.clientX : e.clientY
    startSize.current = size
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return
    const delta =
      orientation === 'horizontal' ? e.clientX - startPos.current : e.clientY - startPos.current
    setSize(clamp(startSize.current + delta))
  }

  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
  }

  const horizontal = orientation === 'horizontal'
  const [first, second] = children
  const paneOverflowClass = paneOverflow === 'hidden' ? 'overflow-hidden' : 'overflow-auto'

  return (
    <div
      className={clsx(
        'flex min-h-0 min-w-0 overflow-hidden',
        horizontal ? 'flex-row' : 'flex-col',
        className,
      )}
    >
      <div
        className={clsx('min-h-0 min-w-0', paneOverflowClass, horizontal ? 'shrink-0' : 'shrink-0')}
        style={horizontal ? { width: size } : { height: size }}
      >
        {first}
      </div>
      <div
        role="separator"
        aria-orientation={horizontal ? 'vertical' : 'horizontal'}
        aria-valuenow={Math.round(size)}
        tabIndex={0}
        title="Drag to resize"
        className={clsx(
          'shrink-0 bg-ink-200/80 hover:bg-accent-400/70 active:bg-accent-500 transition-colors',
          horizontal ? 'w-1 cursor-col-resize' : 'h-1 cursor-row-resize',
          handleClassName,
        )}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={(e) => {
          const step = e.shiftKey ? 40 : 16
          if (horizontal) {
            if (e.key === 'ArrowLeft') {
              e.preventDefault()
              setSize((s) => clamp(s - step))
            } else if (e.key === 'ArrowRight') {
              e.preventDefault()
              setSize((s) => clamp(s + step))
            }
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setSize((s) => clamp(s - step))
          } else if (e.key === 'ArrowDown') {
            e.preventDefault()
            setSize((s) => clamp(s + step))
          }
        }}
      />
      <div className={clsx('min-h-0 min-w-0 flex-1', paneOverflowClass)}>{second}</div>
    </div>
  )
}
