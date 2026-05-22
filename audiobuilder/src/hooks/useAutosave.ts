import { useEffect } from "react";

const AUTOSAVE_KEY = "audiobuilder_canvas_autosave";

export interface AutosaveData {
  nodes: unknown[];
  edges: unknown[];
  configs: unknown;
  seed: number;
}

/**
 * Debounced autosave hook. Saves `data` to localStorage after `delay` ms of
 * inactivity. Only saves when `data.nodes` is non-empty.
 */
export function useAutosave(data: AutosaveData, delay = 5000): void {
  useEffect(() => {
    if (data.nodes.length === 0) return;

    const timer = setTimeout(() => {
      try {
        localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(data));
      } catch {
        // Silently ignore quota errors
      }
    }, delay);

    return () => clearTimeout(timer);
  }, [data, delay]);
}
