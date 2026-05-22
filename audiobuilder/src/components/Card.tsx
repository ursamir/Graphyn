import React from "react";
import { cn } from "../utils/cn";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string;
  subtitle?: string;
  footer?: React.ReactNode;
}

export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ title, subtitle, footer, children, className = "", ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          "overflow-hidden rounded-xl border border-secondary-200 bg-white shadow-sm dark:border-secondary-700 dark:bg-secondary-800",
          className,
        )}
        {...props}
      >
        {(title || subtitle) && (
          <div className="border-b border-secondary-200 px-6 py-4 dark:border-secondary-700">
            {title && (
              <h3 className="text-lg font-semibold text-secondary-900 dark:text-secondary-100">
                {title}
              </h3>
            )}
            {subtitle && (
              <p className="mt-1 text-sm text-secondary-600 dark:text-secondary-400">
                {subtitle}
              </p>
            )}
          </div>
        )}
        <div className="px-6 py-4">{children}</div>
        {footer && (
          <div className="border-t border-secondary-200 bg-secondary-50 px-6 py-4 dark:border-secondary-700 dark:bg-secondary-700/50">
            {footer}
          </div>
        )}
      </div>
    );
  },
);

Card.displayName = "Card";
