/**
 * Sidebar information architecture (pure data — icons live in App.tsx).
 *
 *   Work     Home · Editor · Runs · Models · Ship · Datasets   (workspace-scoped)
 *   Library  Templates · Plugins
 *   Admin    Agent inbox · Worker fleet · Credentials · Ops · Access  (collapsed by default)
 */

import type { AppView } from '../store/appStore'

export type NavSectionId = 'work' | 'library' | 'admin'

export type NavSection = {
  id: NavSectionId
  title: string
  items: Array<{ id: AppView; label: string }>
  /** Collapsible section (closed by default unless it holds the active page). */
  collapsible?: boolean
}

export const NAV_SECTIONS: NavSection[] = [
  {
    id: 'work',
    title: 'Work',
    items: [
      { id: 'projects', label: 'Home' },
      { id: 'builder', label: 'Editor' },
      { id: 'runs', label: 'Runs' },
      { id: 'models', label: 'Models' },
      { id: 'edge', label: 'Ship' },
      { id: 'data', label: 'Datasets' },
    ],
  },
  {
    id: 'library',
    title: 'Library',
    items: [
      { id: 'templates', label: 'Templates' },
      { id: 'plugins', label: 'Plugins' },
    ],
  },
  {
    id: 'admin',
    title: 'Admin',
    collapsible: true,
    items: [
      { id: 'proposals', label: 'Agent inbox' },
      { id: 'workers', label: 'Worker fleet' },
      { id: 'credentials', label: 'Credentials' },
      { id: 'system', label: 'Ops' },
      { id: 'access', label: 'Access' },
    ],
  },
]

/**
 * Views that live *under* a sidebar entry rather than having their own row:
 * Compare runs (`/workspaces/:id/runs/compare`) highlights Runs, Ship → Devices
 * highlights Ship.
 */
const NESTED_VIEW_PARENT: Partial<Record<AppView, AppView>> = {
  experiments: 'runs',
  devices: 'edge',
}

/** Sidebar row to highlight for the current view (null → none, e.g. a 404). */
export function navHighlightFor(view: AppView | null | undefined): AppView | null {
  if (!view) return null
  return NESTED_VIEW_PARENT[view] ?? view
}

/** Section that owns a view's sidebar row (after nested-view mapping). */
export function navSectionFor(view: AppView | null | undefined): NavSectionId | null {
  const id = navHighlightFor(view)
  if (!id) return null
  return NAV_SECTIONS.find((s) => s.items.some((i) => i.id === id))?.id ?? null
}
