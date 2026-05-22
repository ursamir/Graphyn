import React from "react";
import { CheckCircle2, X } from "lucide-react";

// ---------------------------------------------------------------------------
// Inline text editor (for rename)
// ---------------------------------------------------------------------------

export interface InlineEditProps {
  value: string;
  onSave: (v: string) => void;
  onCancel: () => void;
}

export function InlineEdit({ value, onSave, onCancel }: InlineEditProps) {
  const [text, setText] = React.useState(value);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) onSave(text.trim());
      }}
      className="flex items-center gap-1"
    >
      <input
        autoFocus
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="rounded border border-primary-400 bg-white px-2 py-0.5 text-sm text-secondary-900 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:bg-secondary-700 dark:text-secondary-100"
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
        }}
      />
      <button type="submit" className="rounded p-1 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20">
        <CheckCircle2 className="h-4 w-4" />
      </button>
      <button type="button" onClick={onCancel} className="rounded p-1 text-secondary-500 hover:bg-secondary-100 dark:hover:bg-secondary-700">
        <X className="h-4 w-4" />
      </button>
    </form>
  );
}
