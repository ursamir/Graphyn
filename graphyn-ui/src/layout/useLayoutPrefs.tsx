/**
 * Layout preferences: master-detail vs container-content, persisted.
 */
import React from 'react'
import { LAYOUT_MODE_KEY, type ContentLayoutMode } from './keys'

function readMode(): ContentLayoutMode {
  try {
    const v = localStorage.getItem(LAYOUT_MODE_KEY)
    if (v === 'container-content' || v === 'master-detail') return v
  } catch {
    /* ignore */
  }
  return 'master-detail'
}

type LayoutPrefsContextValue = {
  mode: ContentLayoutMode
  setMode: (mode: ContentLayoutMode) => void
}

const LayoutPrefsContext = React.createContext<LayoutPrefsContextValue | null>(null)

export function LayoutPrefsProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = React.useState<ContentLayoutMode>(() => readMode())

  const setMode = React.useCallback((next: ContentLayoutMode) => {
    setModeState(next)
    try {
      localStorage.setItem(LAYOUT_MODE_KEY, next)
    } catch {
      /* ignore */
    }
  }, [])

  const value = React.useMemo(() => ({ mode, setMode }), [mode, setMode])
  return <LayoutPrefsContext.Provider value={value}>{children}</LayoutPrefsContext.Provider>
}

export function useLayoutPrefs(): LayoutPrefsContextValue {
  const ctx = React.useContext(LayoutPrefsContext)
  if (!ctx) {
    // Safe fallback when used outside provider (tests / isolated mounts)
    return {
      mode: readMode(),
      setMode: (next) => {
        try {
          localStorage.setItem(LAYOUT_MODE_KEY, next)
        } catch {
          /* ignore */
        }
      },
    }
  }
  return ctx
}
