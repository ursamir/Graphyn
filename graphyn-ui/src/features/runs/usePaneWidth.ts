/**
 * Width of a pane that may mount / unmount (callback ref + ResizeObserver).
 * `lib/viewport.ts` `useElementWidth` attaches once on mount; the run detail
 * pane only exists while a run is selected, so Runs measures through a
 * callback ref that re-attaches whenever the element changes. 0 until measured.
 */
import * as React from 'react'

export function usePaneWidth<T extends HTMLElement>(): [(el: T | null) => void, number] {
  const [el, setEl] = React.useState<T | null>(null)
  const [width, setWidth] = React.useState(0)
  React.useEffect(() => {
    if (!el || typeof ResizeObserver === 'undefined') return
    setWidth(el.getBoundingClientRect().width)
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0
      setWidth((prev) => (Math.abs(prev - w) < 1 ? prev : w))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [el])
  return [setEl, width]
}
