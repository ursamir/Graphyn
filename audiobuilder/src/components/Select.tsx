import React from "react";
import { cn } from "../utils/cn";

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  helperText?: string;
  options: Array<{ value: string; label: string }>;
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, helperText, options, className = "", ...props }, ref) => {
    return (
      <div className="w-full">
        {label && (
          <label className="mb-2 block text-sm font-medium text-secondary-700 dark:text-secondary-300">
            {label}
          </label>
        )}
        <select
          ref={ref}
          className={cn(
            "w-full rounded-lg border bg-white px-3 py-2 text-secondary-900 transition-colors dark:bg-secondary-800 dark:text-secondary-100",
            error
              ? "border-red-500 focus:border-transparent focus:ring-2 focus:ring-red-500"
              : "border-secondary-300 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500 dark:border-secondary-600",
            className,
          )}
          {...props}
        >
          <option value="">Select an option...</option>
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {error && (
          <p className="mt-1 text-sm text-red-600 dark:text-red-400">{error}</p>
        )}
        {helperText && !error && (
          <p className="mt-1 text-sm text-secondary-600 dark:text-secondary-400">
            {helperText}
          </p>
        )}
      </div>
    );
  },
);

Select.displayName = "Select";
