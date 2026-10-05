/**
 * Run with inputs: shown by the Editor's Run when the graph has a
 * `webhook_trigger` step (JSON body per trigger, prefilled from its
 * `sample_body`) or declares IR `parameters` (one field each, default
 * prefilled). Sends `{inputs, parameters}` with POST /pipelines/run{,-async};
 * 422 (unknown node/port, bad parameter) / 413 (> 1 MiB) surface in the
 * Editor's normal run-error banner. Drafts persist per graph for the session.
 */
import React from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { Play, X } from 'lucide-react'
import { buildRunExtras, paramText, type RunInputsSpec } from './workflowIr'

const DRAFT_KEY = 'graphyn.builder.runInputs.'

function readDraft(key: string): { bodies?: Record<string, string>; params?: Record<string, string> } {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY + key)
    return raw ? (JSON.parse(raw) as { bodies?: Record<string, string>; params?: Record<string, string> }) : {}
  } catch {
    return {}
  }
}

function writeDraft(key: string, value: { bodies: Record<string, string>; params: Record<string, string> }) {
  try {
    sessionStorage.setItem(DRAFT_KEY + key, JSON.stringify(value))
  } catch {
    /* private mode / quota — drafts are a convenience */
  }
}

function pretty(v: unknown): string {
  try {
    return JSON.stringify(v ?? {}, null, 2)
  } catch {
    return '{}'
  }
}

export default function RunInputsDialog({
  spec,
  mode,
  draftKey,
  onCancel,
  onRun,
}: {
  spec: RunInputsSpec
  mode: 'stream' | 'async'
  draftKey: string
  onCancel: () => void
  onRun: (extras: { inputs?: Record<string, Record<string, unknown>>; parameters?: Record<string, unknown> }) => void
}) {
  const [bodies, setBodies] = React.useState<Record<string, string>>(() => {
    const draft = readDraft(draftKey).bodies ?? {}
    return Object.fromEntries(spec.webhooks.map((w) => [w.nodeId, draft[w.nodeId] ?? pretty(w.sampleBody)]))
  })
  const [params, setParams] = React.useState<Record<string, string>>(() => {
    const draft = readDraft(draftKey).params ?? {}
    return Object.fromEntries(spec.parameters.map((p) => [p.name, draft[p.name] ?? paramText(p.default)]))
  })
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const firstRef = React.useRef<HTMLTextAreaElement | HTMLInputElement | null>(null)

  const cancelRef = React.useRef(onCancel)
  cancelRef.current = onCancel
  React.useEffect(() => {
    firstRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') cancelRef.current()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const submit = () => {
    const { extras, errors: errs } = buildRunExtras(spec, bodies, params)
    setErrors(errs)
    if (Object.keys(errs).length) return
    writeDraft(draftKey, { bodies, params })
    onRun(extras)
  }

  const checkBody = (nodeId: string) => {
    const { errors: errs } = buildRunExtras({ webhooks: spec.webhooks.filter((w) => w.nodeId === nodeId), parameters: [] }, bodies, {})
    setErrors((prev) => {
      const next = { ...prev }
      delete next[`body:${nodeId}`]
      return { ...next, ...errs }
    })
  }

  let focusAssigned = false
  const focusRef = (el: HTMLTextAreaElement | HTMLInputElement | null) => {
    if (!focusAssigned && el) {
      firstRef.current = el
      focusAssigned = true
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/30 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="run-inputs-title"
        className="flex max-h-[calc(100dvh-2rem)] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-ink-200 bg-white shadow-xl"
      >
        <div className="flex shrink-0 items-start justify-between gap-2 border-b border-ink-100 px-4 py-2.5">
          <div className="min-w-0">
            <h2 id="run-inputs-title" className="text-[13px] font-semibold text-ink-900">
              {mode === 'async' ? 'Run in background with inputs' : 'Run with inputs'}
            </h2>
            <p className="mt-0.5 text-[11px] text-ink-500">
              The run record keeps only a fingerprint (sha256) of what you send here, never the values.
            </p>
          </div>
          <button type="button" className="btn-quiet shrink-0 !px-1.5 !py-1" aria-label="Close" title="Close (Esc)" onClick={onCancel}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <form
          className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          {spec.webhooks.map((w) => {
            const err = errors[`body:${w.nodeId}`]
            const id = `run-body-${w.nodeId}`
            return (
              <div key={w.nodeId}>
                <label htmlFor={id} className="flex items-baseline justify-between gap-2 text-[12px] text-ink-700">
                  <span>
                    <span className="font-medium">Request body</span>
                    {spec.webhooks.length > 1 ? <span className="text-ink-400"> · {w.label}</span> : null}
                  </span>
                  <button
                    type="button"
                    className="text-[11px] text-accent-700 hover:underline"
                    onClick={() => setBodies((b) => ({ ...b, [w.nodeId]: pretty(w.sampleBody) }))}
                  >
                    Reset to sample
                  </button>
                </label>
                <textarea
                  id={id}
                  ref={focusRef}
                  rows={8}
                  spellCheck={false}
                  className={clsx('field-control mt-1 font-mono text-[11.5px]', err && 'border-rose-400')}
                  value={bodies[w.nodeId] ?? ''}
                  aria-invalid={Boolean(err)}
                  onChange={(e) => setBodies((b) => ({ ...b, [w.nodeId]: e.target.value }))}
                  onBlur={() => checkBody(w.nodeId)}
                />
                <p className={clsx('mt-0.5 text-[10.5px]', err ? 'font-medium text-rose-700' : 'text-ink-400')} role={err ? 'alert' : undefined}>
                  {err || 'JSON sent to the webhook trigger’s body output, as a real delivery would.'}
                </p>
              </div>
            )
          })}
          {spec.parameters.length ? (
            <fieldset className="space-y-2">
              <legend className="text-[12px] font-semibold text-ink-700">Parameters</legend>
              {spec.parameters.map((p) => {
                const err = errors[`param:${p.name}`]
                const id = `run-param-${p.name}`
                const isBool = /^bool/i.test(p.type)
                return (
                  <div key={p.name}>
                    <label htmlFor={id} className="block text-[12px] text-ink-700">
                      <span className="font-mono font-medium">{p.name}</span>
                      <span className="text-ink-400"> · {p.type}</span>
                      {p.description ? <span className="block text-[10.5px] text-ink-400">{p.description}</span> : null}
                    </label>
                    {isBool ? (
                      <select
                        id={id}
                        className="field-control mt-1"
                        value={/^(true|1|yes|on)$/i.test(params[p.name] ?? '') ? 'true' : 'false'}
                        onChange={(e) => setParams((v) => ({ ...v, [p.name]: e.target.value }))}
                      >
                        <option value="false">false</option>
                        <option value="true">true</option>
                      </select>
                    ) : (
                      <input
                        id={id}
                        ref={focusRef}
                        className={clsx('field-control mt-1 font-mono', err && 'border-rose-400')}
                        value={params[p.name] ?? ''}
                        placeholder={paramText(p.default)}
                        aria-invalid={Boolean(err)}
                        onChange={(e) => setParams((v) => ({ ...v, [p.name]: e.target.value }))}
                      />
                    )}
                    {err ? (
                      <p className="mt-0.5 text-[10.5px] font-medium text-rose-700" role="alert">
                        {err}
                      </p>
                    ) : null}
                  </div>
                )
              })}
              <p className="text-[10.5px] text-ink-400">
                Used wherever a step setting says <span className="font-mono">{'${params.NAME}'}</span>. Unchanged values use the default.
              </p>
            </fieldset>
          ) : null}
          <button type="submit" className="hidden" aria-hidden tabIndex={-1} />
        </form>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-ink-100 px-4 py-2.5">
          <button type="button" className="btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={submit}>
            <Play className="h-3.5 w-3.5" /> {mode === 'async' ? 'Run in background' : 'Run'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
