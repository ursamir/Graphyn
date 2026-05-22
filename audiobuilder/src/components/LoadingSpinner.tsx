interface LoadingSpinnerProps {
  size?: "sm" | "md" | "lg";
  message?: string;
}

export function LoadingSpinner({ size = "md", message }: LoadingSpinnerProps) {
  const sizeClasses = {
    sm: "w-6 h-6",
    md: "w-10 h-10",
    lg: "w-16 h-16",
  };

  return (
    <div className="flex flex-col items-center justify-center gap-3 py-8">
      <div
        className={`${sizeClasses[size]} border-3 border-secondary-200 dark:border-secondary-700 border-t-primary-600 dark:border-t-primary-400 rounded-full animate-spin`}
      />
      {message && (
        <p className="text-sm text-secondary-600 dark:text-secondary-400">
          {message}
        </p>
      )}
    </div>
  );
}
