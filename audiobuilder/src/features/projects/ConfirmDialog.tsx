import React from "react";
import { AlertTriangle } from "lucide-react";

// ---------------------------------------------------------------------------
// Confirmation dialog
// ---------------------------------------------------------------------------

export interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  requireTyping?: string; // if set, user must type this string to confirm
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Confirm",
  danger = false,
  requireTyping,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const [typed, setTyped] = React.useState("");
  const canConfirm = !requireTyping || typed === requireTyping;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      onClick={onCancel}
    >
      <div
        className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl dark:bg-secondary-800"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start gap-3">
          {danger && (
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
          )}
          <div>
            <h3 className="text-base font-bold text-secondary-900 dark:text-secondary-100">
              {title}
            </h3>
            <p className="mt-1 text-sm text-secondary-600 dark:text-secondary-400">
              {message}
            </p>
          </div>
        </div>

        {requireTyping && (
          <div className="mb-4">
            <label className="mb-1 block text-xs font-medium text-secondary-600 dark:text-secondary-400">
              Type <strong className="text-secondary-900 dark:text-secondary-100">{requireTyping}</strong> to confirm
            </label>
            <input
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className="w-full rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
              placeholder={requireTyping}
              autoFocus
            />
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-secondary-300 bg-white px-4 py-2 text-sm font-semibold text-secondary-700 hover:bg-secondary-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!canConfirm}
            className={`rounded-lg px-4 py-2 text-sm font-semibold text-white transition-colors disabled:opacity-50 ${
              danger
                ? "bg-red-600 hover:bg-red-700 disabled:bg-red-400"
                : "bg-primary-600 hover:bg-primary-700"
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
