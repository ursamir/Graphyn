/**
 * Shared responsive breakpoints for the console (one source of truth).
 *
 *   phone    < 768   — single column; sidebar and lists become drawers/overlays
 *   tablet   768–1023 — sidebar collapses to an icon rail; master lists overlay
 *   laptop   1024–1439 — icon rail optional; secondary panes collapsible
 *   desktop  ≥ 1440   — everything side by side
 *
 * Use `useViewport()` in components that must change layout (not just CSS) and
 * the matching Tailwind prefixes (`md:` 768, `lg:` 1024, `xl:` 1280,
 * `2xl:` 1536) for pure styling. Prefer the container's own width
 * (`useElementWidth`) for panes whose width depends on sibling panels.
 */
import * as React from 'react'

export const BREAKPOINTS = { tablet: 768, laptop: 1024, desktop: 1440 } as const

export type ViewportSize = 'phone' | 'tablet' | 'laptop' | 'desktop'

export function viewportSizeFor(width: number): ViewportSize {
  if (width < BREAKPOINTS.tablet) return 'phone'
  if (width < BREAKPOINTS.laptop) return 'tablet'
  if (width < BREAKPOINTS.desktop) return 'laptop'
  return 'desktop'
}

function currentWidth(): number {
  return typeof window === 'undefined' ? BREAKPOINTS.desktop : window.innerWidth
}

/** Viewport width + named size; re-renders only when the width changes. */
export function useViewport(): { width: number; size: ViewportSize } {
  const [width, setWidth] = React.useState(currentWidth)
  React.useEffect(() => {
    let frame = 0
    const onResize = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => setWidth(currentWidth()))
    }
    window.addEventListener('resize', onResize)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', onResize)
    }
  }, [])
  return { width, size: viewportSizeFor(width) }
}

/** Live content-box width of an element (ResizeObserver); 0 until measured. */
export function useElementWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = React.useRef<T | null>(null)
  const [width, setWidth] = React.useState(0)
  React.useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0
      setWidth((prev) => (Math.abs(prev - w) < 1 ? prev : w))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}

/* ── Shell + master–detail layout rules (pure; unit-tested) ─────────────── */

/** How the primary sidebar renders. */
export type SidebarMode = 'full' | 'rail' | 'hidden'

/**
 * Sidebar mode for a viewport width + the user's stored preference.
 *
 *   ≥ 1024 (laptop/desktop): full unless the user collapsed it (`'collapsed'`
 *                            → rail). `null` (no choice yet) → full.
 *   768–1023 (tablet):       always the icon rail — a stored "open" preference
 *                            never forces the full sidebar here.
 *   < 768 (phone):           hidden; opened as an overlay drawer from the
 *                            header menu button (not a persisted preference).
 */
export function sidebarModeFor(width: number, pref: 'open' | 'collapsed' | null): SidebarMode {
  const size = viewportSizeFor(width)
  if (size === 'phone') return 'hidden'
  if (size === 'tablet') return 'rail'
  return pref === 'collapsed' ? 'rail' : 'full'
}

/** How a MasterDetail lays out its list (master) and detail panes. */
export type MasterDetailMode = 'split' | 'overlay' | 'stack'

/**
 *   ≥ 1024: `split`   — list | detail side by side (list user-collapsible)
 *   768–1023: `overlay` — detail full width; list is an overlay drawer
 *   < 768: `stack`   — list OR detail (list first; back button in detail)
 */
export function masterDetailModeFor(width: number): MasterDetailMode {
  if (width < BREAKPOINTS.tablet) return 'stack'
  if (width < BREAKPOINTS.laptop) return 'overlay'
  return 'split'
}

/**
 * In `stack` mode, whether the detail pane (not the list) is showing.
 * `hasSelection` undefined → the page did not tell us (no `selectedKey`):
 * show the detail and let the user open the list as an overlay.
 */
export function stackShowsDetail(hasSelection: boolean | undefined, listRequested: boolean): boolean {
  if (listRequested) return false
  return hasSelection !== false
}
