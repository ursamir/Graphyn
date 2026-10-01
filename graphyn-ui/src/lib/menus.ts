/**
 * One-open-menu coordination for popovers / dropdown menus.
 *
 * `useMenuDismiss(open, close, rootRef)` gives a menu the three behaviours
 * every popover in the console needs:
 *  - Escape closes it (capture phase, so a page-level keydown handler that
 *    swallows Escape cannot keep it open);
 *  - a pointerdown outside `rootRef` closes it;
 *  - opening it broadcasts `graphyn:menu-open`, and every other open menu
 *    closes — so two menus are never open at once.
 *
 * `installGlobalDetailsMenuDismiss()` (called once by App) applies the same
 * Escape / outside-click / one-open rules to ad-hoc `<details class="relative">`
 * popovers whose panel is an absolutely positioned direct child (e.g. the Runs
 * "Manage" menu). Plain collapsible `<details>` sections are not touched.
 */

import React from 'react'

export const MENU_OPEN_EVENT = 'graphyn:menu-open'

/** App listens for this and opens the header's Local vs Distributed explainer. */
export const OPEN_MODE_EXPLAINER_EVENT = 'graphyn:open-mode-explainer'

/** Open the header Mode explainer modal from anywhere (e.g. the Editor inspector). */
export function openModeExplainer() {
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(OPEN_MODE_EXPLAINER_EVENT))
}

/** Tell every other menu to close. `id` is the opener's own id (it stays open). */
export function announceMenuOpen(id: string) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent<string>(MENU_OPEN_EVENT, { detail: id }))
}

export function useMenuDismiss(
  open: boolean,
  close: () => void,
  rootRef: React.RefObject<HTMLElement | null>,
): void {
  const reactId = React.useId()
  const idRef = React.useRef(`menu-${reactId}`)
  const closeRef = React.useRef(close)
  closeRef.current = close

  React.useEffect(() => {
    if (!open) return
    const id = idRef.current
    announceMenuOpen(id)
    closeOpenDetailsMenus(null)
    const onOther = (e: Event) => {
      if ((e as CustomEvent<string>).detail !== id) closeRef.current()
    }
    const onPointer = (e: Event) => {
      const root = rootRef.current
      if (root && e.target instanceof Node && root.contains(e.target)) return
      closeRef.current()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      closeRef.current()
    }
    window.addEventListener(MENU_OPEN_EVENT, onOther)
    document.addEventListener('pointerdown', onPointer, true)
    document.addEventListener('keydown', onKey, true)
    return () => {
      window.removeEventListener(MENU_OPEN_EVENT, onOther)
      document.removeEventListener('pointerdown', onPointer, true)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [open, rootRef])
}

const DETAILS_MENU_SELECTOR = 'details[open].relative'

function isDetailsMenu(el: Element): el is HTMLDetailsElement {
  if (!(el instanceof HTMLDetailsElement) || !el.classList.contains('relative')) return false
  return Array.from(el.children).some(
    (c) => c.tagName !== 'SUMMARY' && c instanceof HTMLElement && c.classList.contains('absolute'),
  )
}

function closeOpenDetailsMenus(except: Element | null) {
  if (typeof document === 'undefined') return
  document.querySelectorAll(DETAILS_MENU_SELECTOR).forEach((el) => {
    if (el === except || !isDetailsMenu(el)) return
    if (except && el.contains(except)) return
    el.open = false
  })
}

let detailsInstalled = false

export function installGlobalDetailsMenuDismiss(): () => void {
  if (typeof document === 'undefined' || detailsInstalled) return () => undefined
  detailsInstalled = true
  const onKey = (e: KeyboardEvent) => {
    if (e.key !== 'Escape') return
    const open = Array.from(document.querySelectorAll(DETAILS_MENU_SELECTOR)).filter(isDetailsMenu)
    if (open.length === 0) return
    open.forEach((el) => {
      el.open = false
    })
    const summary = open[open.length - 1].querySelector('summary')
    if (summary instanceof HTMLElement) summary.focus()
  }
  const onPointer = (e: Event) => {
    const target = e.target instanceof Element ? e.target : null
    const owner = target?.closest('details')
    closeOpenDetailsMenus(owner && isDetailsMenu(owner) ? owner : null)
  }
  // A details menu opening (toggle) closes the React menus too.
  const onToggle = (e: Event) => {
    const el = e.target
    if (el instanceof HTMLDetailsElement && el.open && isDetailsMenu(el)) {
      announceMenuOpen('details-menu')
      closeOpenDetailsMenus(el)
    }
  }
  const onOther = (e: Event) => {
    if ((e as CustomEvent<string>).detail !== 'details-menu') closeOpenDetailsMenus(null)
  }
  document.addEventListener('keydown', onKey, true)
  document.addEventListener('pointerdown', onPointer, true)
  document.addEventListener('toggle', onToggle, true)
  window.addEventListener(MENU_OPEN_EVENT, onOther)
  return () => {
    detailsInstalled = false
    document.removeEventListener('keydown', onKey, true)
    document.removeEventListener('pointerdown', onPointer, true)
    document.removeEventListener('toggle', onToggle, true)
    window.removeEventListener(MENU_OPEN_EVENT, onOther)
  }
}
