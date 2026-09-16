/**
 * Shared layout storage keys — one master divider width across the console.
 * Views should use these instead of page-local keys so History/Live/Compare
 * and Library screens stay visually aligned.
 */
export const LAYOUT_KEYS = {
  /** App primary nav width */
  nav: 'graphyn.layout.nav',
  /** Default master pane (list) width — synced app-wide */
  master: 'graphyn.layout.master',
  /** Vertical stack size when layout mode is container-content */
  stack: 'graphyn.layout.stack',
  /** Nested list|preview inside a detail pane (e.g. Run outputs) */
  nested: 'graphyn.layout.nested',
} as const

export type ContentLayoutMode = 'master-detail' | 'container-content'

export const LAYOUT_MODE_KEY = 'graphyn.layout.mode'

export const LAYOUT_SPLIT_EVENT = 'graphyn:layout-split'
