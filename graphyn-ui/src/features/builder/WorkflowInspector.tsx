/**
 * Editor inspector sections for IR workflow features:
 *  - `ErrorHandlingEditor` — per-node on_error (fail / continue / route) + retry;
 *  - `EdgeConditionEditor` — edge `condition` with syntax help and a light
 *    client check on blur (server validation stays authoritative).
 * Pure logic lives in `workflowIr.ts`.
 */
import React from 'react'
import clsx from 'clsx'
import {
  CONDITION_HELP,
  CONDITION_MAX_LENGTH,
  ERROR_PORT_DEFAULT,
  checkCondition,
  errorHandlingSummary,
  type NodeOnError,
  type NodeRetry,
  type OnErrorMode,
} from './workflowIr'

const MODE_LABEL: Record<OnErrorMode, string> = {
  fail: 'Fail the run',
  continue: 'Continue (skip what depends on it)',
  route: 'Route to error branch',
}

function numOrNull(raw: string): number | null {
  if (raw.trim() === '') return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

export function ErrorHandlingEditor({
  onError,
  retry,
  onChange,
}: {
  onError: NodeOnError | null | undefined
  retry: NodeRetry | null | undefined
  onChange: (next: { onError: NodeOnError | null; retry: NodeRetry | null }) => void
}) {
  const mode: OnErrorMode = onError?.mode ?? 'fail'
  const custom = mode !== 'fail' || Boolean(retry)
  const setMode = (m: OnErrorMode) =>
    onChange({
      onError: m === 'fail' ? null : m === 'route' ? { mode: 'route', port: onError?.port || ERROR_PORT_DEFAULT } : { mode: 'continue' },
      retry: retry ?? null,
    })
  const setRetry = (patch: Partial<NodeRetry> | null) => {
    if (patch === null) {
      onChange({ onError: onError ?? null, retry: null })
      return
    }
    const next: NodeRetry = { max_attempts: retry?.max_attempts ?? 1, ...retry, ...patch }
    onChange({ onError: onError ?? null, retry: next })
  }
  const on = retry?.on ?? ['exception']
  const toggleOn = (kind: 'exception' | 'timeout', checked: boolean) => {
    const set = new Set(on)
    if (checked) set.add(kind)
    else set.delete(kind)
    setRetry({ on: set.size ? ([...set] as Array<'exception' | 'timeout'>) : ['exception'] })
  }
  return (
    <details className="group/err rounded-lg border border-ink-200" open={custom || undefined}>
      <summary className="flex cursor-pointer select-none items-center gap-2 px-2.5 py-1.5 text-[12px]">
        <span className="font-semibold text-ink-700">Error handling</span>
        <span className={clsx('min-w-0 flex-1 truncate text-right text-[11px]', custom ? 'text-ink-700' : 'text-ink-400')}>
          {errorHandlingSummary(onError, retry)}
        </span>
      </summary>
      <div className="space-y-2 border-t border-ink-100 px-2.5 py-2">
        <label className="block text-[12px] text-ink-700">
          <span className="font-medium">If this step fails</span>
          <select className="field-control mt-1" value={mode} onChange={(e) => setMode(e.target.value as OnErrorMode)}>
            {(Object.keys(MODE_LABEL) as OnErrorMode[]).map((m) => (
              <option key={m} value={m}>
                {MODE_LABEL[m]}
              </option>
            ))}
          </select>
        </label>
        {mode === 'route' ? (
          <div className="space-y-1">
            <label className="block text-[12px] text-ink-700">
              <span className="font-medium">Error port</span>
              <input
                className="field-control mt-1 font-mono"
                value={onError?.port ?? ERROR_PORT_DEFAULT}
                maxLength={64}
                onChange={(e) =>
                  onChange({
                    onError: { mode: 'route', port: e.target.value.replace(/[^A-Za-z0-9_-]/g, '') },
                    retry: retry ?? null,
                  })
                }
                onBlur={(e) => {
                  if (!e.target.value.trim()) onChange({ onError: { mode: 'route', port: ERROR_PORT_DEFAULT }, retry: retry ?? null })
                }}
              />
            </label>
            <p className="text-[10.5px] leading-snug text-ink-500">
              The step gets a red <span className="font-mono text-rose-700">{onError?.port || ERROR_PORT_DEFAULT}</span> output.
              Wire it to a step like error_catch, send_email or http_webhook — it receives{' '}
              <span className="font-mono">{'{ok:false, error_type, message}'}</span> and the normal outputs are skipped.
            </p>
          </div>
        ) : mode === 'continue' ? (
          <p className="text-[10.5px] leading-snug text-ink-500">
            The run keeps going; steps that need this step’s outputs are skipped.
          </p>
        ) : null}

        <div className="border-t border-ink-100 pt-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12px] font-medium text-ink-700">Retry</span>
            {retry ? (
              <button type="button" className="text-[11px] text-accent-700 hover:underline" onClick={() => setRetry(null)}>
                Use step default
              </button>
            ) : null}
          </div>
          <div className="mt-1 grid grid-cols-3 gap-1.5">
            <label className="block text-[11px] text-ink-600">
              Attempts
              <input
                type="number"
                min={1}
                max={20}
                className="field-control mt-0.5 font-mono"
                placeholder="default"
                value={retry?.max_attempts ?? ''}
                onChange={(e) => {
                  const n = numOrNull(e.target.value)
                  if (n == null) setRetry(null)
                  else setRetry({ max_attempts: Math.min(20, Math.max(1, Math.round(n))) })
                }}
              />
            </label>
            <label className="block text-[11px] text-ink-600" title="Wait before retry i = min(back-off × 2^i, max back-off)">
              Back-off s
              <input
                type="number"
                min={0}
                max={3600}
                step="any"
                className="field-control mt-0.5 font-mono"
                placeholder="0"
                disabled={!retry}
                value={retry?.backoff_s ?? ''}
                onChange={(e) => setRetry({ backoff_s: Math.min(3600, Math.max(0, numOrNull(e.target.value) ?? 0)) })}
              />
            </label>
            <label className="block text-[11px] text-ink-600">
              Max s
              <input
                type="number"
                min={0}
                max={3600}
                step="any"
                className="field-control mt-0.5 font-mono"
                placeholder="60"
                disabled={!retry}
                value={retry?.max_backoff_s ?? ''}
                onChange={(e) => {
                  const n = numOrNull(e.target.value)
                  setRetry({ max_backoff_s: n == null ? undefined : Math.min(3600, Math.max(0, n)) })
                }}
              />
            </label>
          </div>
          {retry ? (
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px] text-ink-600">
              <span className="text-ink-400">Retry on</span>
              {(['exception', 'timeout'] as const).map((k) => (
                <label key={k} className="inline-flex items-center gap-1">
                  <input type="checkbox" checked={on.includes(k)} onChange={(e) => toggleOn(k, e.target.checked)} />
                  {k === 'exception' ? 'any error' : 'timeouts'}
                </label>
              ))}
            </div>
          ) : (
            <p className="mt-1 text-[10.5px] text-ink-400">Blank uses the step’s built-in retry policy.</p>
          )}
        </div>
      </div>
    </details>
  )
}

export function EdgeConditionEditor({
  condition,
  sourcePort,
  onChange,
}: {
  condition: string | null | undefined
  sourcePort: string
  onChange: (next: string | null) => void
}) {
  const [draft, setDraft] = React.useState(String(condition ?? ''))
  const [error, setError] = React.useState<string | null>(() => checkCondition(condition))
  const [helpOpen, setHelpOpen] = React.useState(false)
  React.useEffect(() => {
    setDraft(String(condition ?? ''))
    setError(checkCondition(condition))
  }, [condition])
  const commit = () => {
    const t = draft.trim()
    setError(checkCondition(t))
    if (t !== String(condition ?? '').trim()) onChange(t || null)
  }
  const example = `output["${sourcePort || 'output'}"]`
  return (
    <div className="space-y-1 border-t border-ink-100 pt-2">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor="edge-condition" className="text-[12px] font-semibold text-ink-700">
          Condition
        </label>
        <button type="button" className="text-[11px] text-accent-700 hover:underline" onClick={() => setHelpOpen((v) => !v)} aria-expanded={helpOpen}>
          {helpOpen ? 'Hide syntax' : 'Syntax'}
        </button>
      </div>
      <textarea
        id="edge-condition"
        rows={2}
        maxLength={CONDITION_MAX_LENGTH}
        spellCheck={false}
        className={clsx('field-control font-mono text-[11.5px]', error && 'border-rose-400')}
        placeholder={`e.g. len(${example}) > 0`}
        value={draft}
        aria-invalid={Boolean(error)}
        aria-describedby="edge-condition-msg"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            commit()
          }
        }}
      />
      <p id="edge-condition-msg" className={clsx('text-[10.5px] leading-snug', error ? 'font-medium text-rose-700' : 'text-ink-400')} role={error ? 'alert' : undefined}>
        {error
          ? error
          : draft.trim()
            ? 'The target step runs only when this is true; otherwise it is skipped.'
            : 'Empty = always pass data along this connection.'}
      </p>
      {helpOpen ? (
        <p className="rounded bg-ink-50 px-2 py-1.5 text-[10.5px] leading-snug text-ink-600">{CONDITION_HELP}</p>
      ) : null}
      {draft.trim() ? (
        <button
          type="button"
          className="text-[11px] text-ink-500 hover:text-ink-800 hover:underline"
          onClick={() => {
            setDraft('')
            setError(null)
            onChange(null)
          }}
        >
          Remove condition
        </button>
      ) : null}
    </div>
  )
}
