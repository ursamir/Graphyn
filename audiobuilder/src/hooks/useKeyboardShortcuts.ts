import { useEffect } from "react";

interface KeyboardShortcutHandlers {
  onSave?: () => void;
  onFocusSearch?: () => void;
  onRun?: () => void;
  onUndo?: () => void;
  onRedo?: () => void;
}

/**
 * Registers global keyboard shortcuts on the window.
 *
 * Shortcuts:
 *   Ctrl/Cmd + S        → onSave
 *   Ctrl/Cmd + F        → onFocusSearch (prevents browser find)
 *   Ctrl/Cmd + Enter    → onRun
 *   Ctrl/Cmd + Z        → onUndo
 *   Ctrl/Cmd + Shift+Z  → onRedo
 */
export function useKeyboardShortcuts(handlers: KeyboardShortcutHandlers): void {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const ctrl = e.ctrlKey || e.metaKey;
      if (!ctrl) return;

      const key = e.key.toLowerCase();

      if (key === "s") {
        e.preventDefault();
        handlers.onSave?.();
        return;
      }

      if (key === "f") {
        e.preventDefault();
        handlers.onFocusSearch?.();
        return;
      }

      if (key === "enter") {
        e.preventDefault();
        handlers.onRun?.();
        return;
      }

      if (key === "z") {
        e.preventDefault();
        if (e.shiftKey) {
          handlers.onRedo?.();
        } else {
          handlers.onUndo?.();
        }
        return;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [handlers]);
}
