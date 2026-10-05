/**
 * MasterDetail context + `useMasterDetail()` hook (split out of MasterDetail.tsx
 * so that file only exports components — fast refresh). See MasterDetail.tsx
 * for the API and responsive rules.
 */
import React from 'react'
import type { MasterDetailMode } from '../lib/viewport'

export type MasterDetailContextValue = {
  /** False when called outside a MasterDetail (all actions are no-ops). */
  inMasterDetail: boolean
  mode: MasterDetailMode
  /** Split mode: the user hid the list. */
  collapsed: boolean
  setCollapsed: (next: boolean | ((prev: boolean) => boolean)) => void
  collapsible: boolean
  /** True below 1024: the list is a drawer (overlay) or a separate screen (stack). */
  isOverlay: boolean
  /** Overlay drawer open / stack list showing. */
  listOpen: boolean
  openList: () => void
  closeList: () => void
  /** split → toggle collapsed; overlay → toggle drawer; stack → show list. */
  toggleList: () => void
  /** Phone back: calls the page's `onBack` (if any) then shows the list. */
  back: () => void
  listLabel: string
  /** @internal toggles register so MasterDetail can hide its fallback controls. */
  registerToggle: () => () => void
}

const noop = () => {}
const DEFAULT_CTX: MasterDetailContextValue = {
  inMasterDetail: false,
  mode: 'split',
  collapsed: false,
  setCollapsed: noop,
  collapsible: false,
  isOverlay: false,
  listOpen: false,
  openList: noop,
  closeList: noop,
  toggleList: noop,
  back: noop,
  listLabel: 'list',
  registerToggle: () => noop,
}

export const MasterDetailContext = React.createContext<MasterDetailContextValue>(DEFAULT_CTX)

/** Collapse / drawer state of the nearest MasterDetail (safe outside one). */
export function useMasterDetail(): MasterDetailContextValue {
  return React.useContext(MasterDetailContext)
}

