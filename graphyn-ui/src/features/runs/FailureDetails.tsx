/**
 * Failed step text: "ErrorType: message" headline + collapsible traceback
 * (framework noise frames hidden, see runRecord.failureView).
 */
import clsx from 'clsx'
import type { FailureView } from './runRecord'

export function FailureDetails({
  failure,
  className,
  dense,
}: {
  failure: FailureView
  className?: string
  /** One-line headline (header banner); traceback still collapsible. */
  dense?: boolean
}) {
  return (
    <div className={clsx('min-w-0 text-rose-900', className)}>
      <p className={clsx('min-w-0 font-mono', dense ? 'truncate text-[11px]' : 'whitespace-pre-wrap break-words text-[12px]')} title={failure.headline}>
        {failure.errorType ? <span className="font-semibold">{failure.errorType}: </span> : null}
        {failure.errorType ? failure.headline.slice(failure.errorType.length + 2) : failure.headline}
      </p>
      {failure.traceback ? (
        <details className="mt-1">
          <summary className="cursor-pointer select-none text-[11px] text-rose-800/80">
            Traceback
            {failure.hiddenNoise > 0 ? (
              <span className="text-rose-700/60"> · {failure.hiddenNoise} framework lines hidden</span>
            ) : null}
          </summary>
          <pre className="mt-1 max-h-64 overflow-auto rounded-md bg-ink-950 p-2 font-mono text-[10.5px] leading-4 text-ink-100">
            {failure.traceback}
          </pre>
        </details>
      ) : null}
    </div>
  )
}
