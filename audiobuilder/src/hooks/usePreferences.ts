import React from "react";

export interface Preferences {
  theme: "dark" | "light" | "system";
  nodePaletteCollapsed: Record<string, boolean>;
  recentProjects: string[]; // last 5 project names
  logViewerFilters: { level: string; nodeFilter: string; searchText: string };
}

const STORAGE_KEY = "audiobuilder_preferences";

const DEFAULT_PREFERENCES: Preferences = {
  theme: "system",
  nodePaletteCollapsed: {},
  recentProjects: [],
  logViewerFilters: { level: "ALL", nodeFilter: "", searchText: "" },
};

function loadPreferences(): Preferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_PREFERENCES };
    const parsed = JSON.parse(raw) as Partial<Preferences>;
    return {
      ...DEFAULT_PREFERENCES,
      ...parsed,
      logViewerFilters: {
        ...DEFAULT_PREFERENCES.logViewerFilters,
        ...(parsed.logViewerFilters ?? {}),
      },
    };
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

function savePreferences(prefs: Preferences): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // Silently ignore localStorage quota errors
  }
}

export function usePreferences() {
  const [prefs, setPrefs] = React.useState<Preferences>(loadPreferences);

  const updatePrefs = React.useCallback((partial: Partial<Preferences>) => {
    setPrefs((prev) => {
      const next: Preferences = {
        ...prev,
        ...partial,
        nodePaletteCollapsed: {
          ...prev.nodePaletteCollapsed,
          ...(partial.nodePaletteCollapsed ?? {}),
        },
        logViewerFilters: {
          ...prev.logViewerFilters,
          ...(partial.logViewerFilters ?? {}),
        },
      };
      savePreferences(next);
      return next;
    });
  }, []);

  const resetPrefs = React.useCallback(() => {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore
    }
    setPrefs({ ...DEFAULT_PREFERENCES });
  }, []);

  return { prefs, updatePrefs, resetPrefs };
}
