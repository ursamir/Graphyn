/**
 * Raise the global toast stack above a page's bottom panel.
 *
 * ToastHost sits at `bottom: var(--toast-bottom-inset, 1rem)`. A page with a
 * critical bottom panel (e.g. the Editor execution log) calls
 * `useToastBottomInset(panelHeightPx + 16)` while mounted; the inset resets on
 * unmount. Pass `null` / 0 to leave the default.
 */
import React from 'react'

const VAR = '--toast-bottom-inset'

export function setToastBottomInset(px: number | null) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  if (px && px > 0) root.style.setProperty(VAR, `${Math.round(px)}px`)
  else root.style.removeProperty(VAR)
}

export function useToastBottomInset(px: number | null | undefined) {
  React.useEffect(() => {
    setToastBottomInset(px ?? null)
    return () => setToastBottomInset(null)
  }, [px])
}
