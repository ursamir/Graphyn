/**
 * Run audit UI: the Overview "Run record" card (prove.json at a glance), the
 * Verify checklist and the Replay confirm / input-changed diff panels used by
 * the run header. Parsing lives in runRecord.ts (pure, unit-tested).
 *
 * Sources (defensive — old API containers lack the new fields):
 *   GET /runs/{id} `record` / `record_status` (audit contract) →
 *   else runs/<id>/prove.json via GET /outputs/file.
 */
import React from 'react'
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, CircleHelp, Copy, FileJson, ShieldCheck, XCircle } from 'lucide-react'
import { CopyableMono } from '../../components/ui'
import { humanNodeLabel, shortRunId } from '../../lib/format'
import {
  buildRunRecord,
  formatAbsoluteLocal,
  formatDurationMs,
  formatUtc,
  gapFor,
  recordCopyText,
  shortHash,
  triggerLabel,
  type InputChange,
  type RecordGap,
  type RunRecordView,
  type VerifyGroup,
  type VerifyState,
} from './runRecord'
import { useRunRecord } from './useRunRecord'

type Rec = Record<string, unknown>

function NotRecorded({ gap, children = 'not recorded' }: { gap?: RecordGap; children?: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900"
      title={gap?.hint}
    >
      <AlertTriangle className="h-3 w-3" aria-hidden />
      {children}
    </span>
  )
}

function HashChip({ value, label }: { value: string; label?: string }) {
  if (!value) return null
  return (
    <span className="inline-flex items-center gap-1 font-mono text-[11px] text-ink-800" title={`${label ? `${label}: ` : ''}${value}`}>
      {shortHash(value, 12)}
      <CopyableMono value={value} copyOnly />
    </span>
  )
}

function Field({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={clsx('min-w-0', wide && 'sm:col-span-2')}>
      <dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">{label}</dt>
      <dd className="mt-0.5 min-w-0 text-[12px] text-ink-800">{children}</dd>
    </div>
  )
}

function TimeValue({ iso }: { iso: string }) {
  if (!iso) return <span className="text-ink-400">—</span>
  return (
    <span className="tabular-nums" title={`${formatUtc(iso)} · ${iso}`}>
      {formatAbsoluteLocal(iso)}
    </span>
  )
}

/** Overview card: who/when/what exactly ran, with amber gaps on old runs. */
export function RunRecordCard({
  runId,
  detail,
  graphSeed,
  onViewRaw,
  onOpenRun,
  nodeTypeLabel,
}: {
  runId: string
  detail: Rec | null
  /** Seed from the run's graph metadata (fallback). */
  graphSeed?: unknown
  /** Open prove.json in Run outputs' viewer. */
  onViewRaw?: () => void
  onOpenRun?: (runId: string) => void
  nodeTypeLabel?: (nodeType: string) => string
}) {
  const { prove, meta, pending, loading } = useRunRecord(runId, detail)
  const [copied, setCopied] = React.useState(false)
  const view: RunRecordView = React.useMemo(
    () => buildRunRecord({ runId, prove, meta, detail, graphMetadata: { seed: graphSeed } }),
    [runId, prove, meta, detail, graphSeed],
  )
  if (!detail) return null
  const typeLabel = nodeTypeLabel ?? ((t: string) => humanNodeLabel(t))
  const copyAll = () => {
    void navigator.clipboard.writeText(recordCopyText(view)).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1400)
    })
  }
  const nodeGap = gapFor(view, 'node_versions')
  const p = view.pipeline
  return (
    <section className="rounded-xl border border-ink-200 bg-white" aria-label="Run record">
      <header className="flex flex-wrap items-center gap-2 border-b border-ink-100 bg-ink-50/60 px-3 py-1.5">
        <ShieldCheck className="h-3.5 w-3.5 text-ink-500" aria-hidden />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Run record</span>
        {pending ? (
          <span className="text-[11px] text-ink-500">· sealed when the run finishes</span>
        ) : loading ? (
          <span className="text-[11px] text-ink-400">· loading…</span>
        ) : view.gaps.length > 0 ? (
          <span
            className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900"
            title={view.gaps.map((g) => `${g.label}: ${g.hint}`).join('\n')}
          >
            {view.gaps.length} not recorded
          </span>
        ) : (
          <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800">complete</span>
        )}
        <span className="ml-auto flex items-center gap-1">
          <button type="button" className="btn-quiet !px-1.5 !py-0.5 text-[11px]" onClick={copyAll} title="Copy the whole record as text">
            {copied ? <CheckCircle2 className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />} Copy all
          </button>
          {onViewRaw && view.hasProve ? (
            <button type="button" className="btn-quiet !px-1.5 !py-0.5 text-[11px]" onClick={onViewRaw} title="Open prove.json in Run outputs">
              <FileJson className="h-3 w-3" /> View raw record
            </button>
          ) : null}
        </span>
      </header>
      {!pending && !loading && !view.hasProve ? (
        <p className="px-3 py-2 text-[12px] text-amber-900">
          <NotRecorded gap={gapFor(view, 'record')}>no record</NotRecorded>{' '}
          This run has no reproducibility record (prove.json) — it cannot be verified or replayed exactly.
        </p>
      ) : null}
      <dl className="grid gap-x-4 gap-y-2 px-3 py-2.5 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Started by">
          {view.actor ? (
            <span>
              <span className="font-medium">{view.actor}</span>
              {view.trigger ? <span className="text-ink-500"> · via {triggerLabel(view.trigger)}</span> : null}{' '}
              {gapFor(view, 'actor') ? <NotRecorded gap={gapFor(view, 'actor')}>generic</NotRecorded> : null}
            </span>
          ) : (
            <NotRecorded gap={gapFor(view, 'actor')} />
          )}
        </Field>
        <Field label="Started">
          <TimeValue iso={view.startedAt} />
        </Field>
        <Field label="Finished">
          <TimeValue iso={view.endedAt} />
          {view.durationMs != null ? <span className="ml-1 text-ink-500">· {formatDurationMs(view.durationMs)}</span> : null}
        </Field>
        <Field label="Graph snapshot">
          {view.graphHash ? (
            <HashChip value={view.graphHash} label="graph_hash" />
          ) : (
            <NotRecorded gap={gapFor(view, 'graph_hash')} />
          )}
          {view.materializedGraphHash ? (
            <span className="ml-1 text-[10px] text-ink-400" title={`As executed (paths resolved): ${view.materializedGraphHash}`}>
              · executed {shortHash(view.materializedGraphHash)}
            </span>
          ) : null}
        </Field>
        <Field label="Pipeline version">
          {p?.kind === 'saved' ? (
            <span title={[p.label, p.match ? `matched by ${p.match.replace('_', ' ')}` : ''].filter(Boolean).join(' · ') || undefined}>
              <span className="font-medium">{p.name || 'pipeline'}</span>
              {p.env ? <span className="text-ink-500"> · {p.env}</span> : null}
              {p.revision ? <span className="font-mono text-[11px] text-ink-500"> · {p.revision}</span> : null}
              {p.modified ? (
                <span className="ml-1">
                  <NotRecorded gap={{ key: 'modified', label: 'Pipeline', hint: 'The graph was edited after loading the saved pipeline — the saved version is not exactly what ran' }}>
                    edited before run
                  </NotRecorded>
                </span>
              ) : null}
            </span>
          ) : p?.kind === 'ad-hoc' ? (
            <span className="text-ink-600">Ad-hoc graph (not a saved pipeline)</span>
          ) : (
            <span>
              <span className="text-ink-600">Ad-hoc graph? </span>
              <NotRecorded gap={gapFor(view, 'pipeline_version')} />
            </span>
          )}
        </Field>
        <Field label="Seed">
          {view.seed != null ? <span className="font-mono">{view.seed}</span> : <NotRecorded gap={gapFor(view, 'seed')} />}
        </Field>
        <Field label="Record">
          {view.recordHash ? (
            <span className="inline-flex flex-wrap items-center gap-1">
              <HashChip value={view.recordHash} label="record_hash" />
              {view.chainPosition != null ? (
                <span className="text-ink-500" title={view.prevRecordHash ? `Previous record ${view.prevRecordHash}` : 'First record in this chain'}>
                  · chain #{view.chainPosition}
                </span>
              ) : null}
            </span>
          ) : (
            <NotRecorded gap={gapFor(view, 'record_hash')}>not hashed</NotRecorded>
          )}
        </Field>
        <Field label="Platform">
          <span className="text-ink-700" title={view.runtimeVersion}>
            {[view.graphynVersion ? `Graphyn ${view.graphynVersion}` : '', view.runtimeVersion].filter(Boolean).join(' · ') || '—'}
          </span>
        </Field>
        {view.replayOf ? (
          <Field label="Replay of">
            {onOpenRun ? (
              <button
                type="button"
                className="font-mono text-accent-800 underline-offset-2 hover:underline"
                title={view.replayOf}
                onClick={() => onOpenRun(view.replayOf)}
              >
                run {shortRunId(view.replayOf)}
              </button>
            ) : (
              <span className="font-mono" title={view.replayOf}>{shortRunId(view.replayOf)}</span>
            )}
          </Field>
        ) : null}
      </dl>

      {view.hasProve ? (
        <div className="divide-y divide-ink-100 border-t border-ink-100">
          <details className="group">
            <summary className="flex cursor-pointer select-none items-center gap-2 px-3 py-1.5 text-[11px] font-medium text-ink-600">
              Code — {view.nodeVersions.length} node type{view.nodeVersions.length === 1 ? '' : 's'}
              {nodeGap ? <NotRecorded gap={nodeGap}>versions not recorded</NotRecorded> : null}
              {gapFor(view, 'plugin_version') && !nodeGap ? <NotRecorded gap={gapFor(view, 'plugin_version')}>plugin versions</NotRecorded> : null}
            </summary>
            {view.nodeVersions.length ? (
              <table className="w-full text-left text-[11px]">
                <thead className="text-[10px] uppercase tracking-wide text-ink-400">
                  <tr>
                    <th className="px-3 py-1 font-semibold">Step type</th>
                    <th className="px-2 py-1 font-semibold">Version</th>
                    <th className="px-2 py-1 font-semibold">Code hash</th>
                  </tr>
                </thead>
                <tbody>
                  {view.nodeVersions.map((n) => (
                    <tr key={n.nodeType} className="border-t border-ink-50">
                      <td className="px-3 py-1 text-ink-800" title={n.nodeType}>
                        {typeLabel(n.nodeType)}
                        {n.plugin && n.plugin !== n.nodeType ? <span className="text-ink-400"> · {n.plugin}</span> : null}
                      </td>
                      <td className="px-2 py-1">
                        {n.placeholder ? (
                          <NotRecorded gap={nodeGap}>{n.version || 'not recorded'}</NotRecorded>
                        ) : (
                          <span className="font-mono">{n.version || '—'}</span>
                        )}
                        {n.runtime ? <span className="ml-1 text-ink-400">{n.runtime}</span> : null}
                      </td>
                      <td className="px-2 py-1">{n.codeHash ? <HashChip value={n.codeHash} label="code hash" /> : <span className="text-ink-400">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </details>
          <details>
            <summary className="flex cursor-pointer select-none items-center gap-2 px-3 py-1.5 text-[11px] font-medium text-ink-600">
              Inputs — {view.inputs.length} external input{view.inputs.length === 1 ? '' : 's'}
              {view.datasetVersions.length ? ` · ${view.datasetVersions.length} dataset version${view.datasetVersions.length === 1 ? '' : 's'}` : ''}
              {gapFor(view, 'dataset_versions') ? <NotRecorded gap={gapFor(view, 'dataset_versions')}>dataset versions</NotRecorded> : null}
              {gapFor(view, 'inputs') ? <NotRecorded gap={gapFor(view, 'inputs')}>no hashes</NotRecorded> : null}
            </summary>
            <ul className="space-y-1 px-3 pb-2 text-[11px]">
              {view.inputs.slice(0, 40).map((i, idx) => (
                <li key={`${i.hash}-${idx}`} className="flex min-w-0 flex-wrap items-center gap-x-2">
                  <span className="min-w-0 max-w-full truncate font-mono text-ink-700" title={i.label || undefined}>
                    {i.label || `input ${idx + 1}`}
                  </span>
                  {i.kind === 'missing' ? <NotRecorded>missing at run time</NotRecorded> : null}
                  {i.hash ? <HashChip value={i.hash} label="content hash" /> : <NotRecorded gap={gapFor(view, 'inputs')}>no hash</NotRecorded>}
                  {i.hashMode === 'manifest' ? (
                    <span className="text-ink-400" title="Large folder: hashed by file list + sizes, not full content">manifest</span>
                  ) : null}
                  {i.fileCount ? <span className="text-ink-400">{i.fileCount.toLocaleString()} files</span> : null}
                  {i.datasetVersion ? <span className="rounded bg-ink-100 px-1 text-ink-700">dataset {i.datasetVersion}</span> : null}
                </li>
              ))}
              {view.inputs.length > 40 ? <li className="text-ink-400">+{view.inputs.length - 40} more — View raw record</li> : null}
              {view.datasetVersions.map((d, idx) => (
                <li key={`ds-${idx}`} className="flex flex-wrap items-center gap-x-2">
                  <span className="text-ink-500">Dataset</span>
                  <span className="font-medium text-ink-800">{d.name}</span>
                  {d.version ? <span className="font-mono">{d.version}</span> : null}
                  {d.hash ? <HashChip value={d.hash} label="dataset content hash" /> : null}
                </li>
              ))}
              {view.inputs.length === 0 && view.datasetVersions.length === 0 ? (
                <li className="text-ink-400">No external inputs recorded.</li>
              ) : null}
            </ul>
          </details>
          <details>
            <summary className="flex cursor-pointer select-none items-center gap-2 px-3 py-1.5 text-[11px] font-medium text-ink-600">
              Environment
              {view.environment ? (
                <span className="font-normal text-ink-500">
                  {[view.environment.python && `Python ${view.environment.python}`, view.environment.platform].filter(Boolean).join(' · ')}
                </span>
              ) : (
                <NotRecorded gap={gapFor(view, 'environment')} />
              )}
            </summary>
            {view.environment ? (
              <dl className="grid gap-x-4 gap-y-1 px-3 pb-2 text-[11px] sm:grid-cols-2">
                <Field label="Image">{view.environment.image ? <HashChip value={view.environment.image} label="image" /> : <span className="text-ink-400">not in a container / not recorded</span>}</Field>
                <Field label="Git">{view.environment.git ? <span className="font-mono">{view.environment.git}</span> : <span className="text-ink-400">—</span>}</Field>
                {view.environment.libs.length ? (
                  <Field label="Libraries" wide>
                    <span className="font-mono text-[10px] text-ink-600">
                      {view.environment.libs.map(([k, v]) => `${k} ${v}`).join(' · ')}
                    </span>
                  </Field>
                ) : null}
              </dl>
            ) : null}
          </details>
        </div>
      ) : null}
    </section>
  )
}

// ── Verify checklist ───────────────────────────────────────────────────

const STATE_ICON: Record<VerifyState, React.ReactNode> = {
  pass: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" aria-label="pass" />,
  changed: <AlertTriangle className="h-3.5 w-3.5 text-amber-600" aria-label="changed" />,
  failed: <XCircle className="h-3.5 w-3.5 text-rose-600" aria-label="failed" />,
  unknown: <CircleHelp className="h-3.5 w-3.5 text-ink-400" aria-label="not checked" />,
}

const STATE_WORD: Record<VerifyState, string> = {
  pass: 'matches',
  changed: 'changed',
  failed: 'failed',
  unknown: 'not checked',
}

export function VerifyChecklist({
  groups,
  ok,
  status,
  verifiedAt,
  labelFor,
  onClose,
}: {
  groups: VerifyGroup[]
  ok: boolean | null
  status: string
  verifiedAt?: string
  labelFor?: (nodeId: string) => string | undefined
  onClose: () => void
}) {
  const headline =
    status === 'unsealed'
      ? 'No sealed record yet — nothing to verify'
      : ok
        ? 'Everything matches the record'
        : groups.some((g) => g.state === 'failed')
          ? 'Verification failed'
          : groups.some((g) => g.state === 'changed')
            ? 'Some things changed since this run'
            : 'Verification incomplete'
  return (
    <div
      role="dialog"
      aria-label="Verify run"
      className={clsx(
        'w-full space-y-1.5 rounded-lg border px-3 py-2 text-[12px]',
        ok ? 'border-emerald-200 bg-emerald-50/50' : 'border-amber-200 bg-amber-50/50',
      )}
    >
      <div className="flex items-center gap-2">
        <span className="font-semibold text-ink-900">{headline}</span>
        {verifiedAt ? <span className="text-[11px] text-ink-500" title={formatUtc(verifiedAt)}>· checked {formatAbsoluteLocal(verifiedAt)}</span> : null}
        <button type="button" className="btn-quiet ml-auto !px-1.5 !py-0.5 text-[11px]" onClick={onClose}>
          Close
        </button>
      </div>
      {groups.length === 0 ? <p className="text-ink-500">The server returned no checks.</p> : null}
      <ul className="space-y-1">
        {groups.map((g) => {
          const notPass = g.items.filter((i) => i.state !== 'pass')
          return (
            <li key={g.group}>
              <details open={g.state === 'failed' || g.state === 'changed'}>
                <summary className="flex cursor-pointer select-none items-center gap-1.5">
                  {STATE_ICON[g.state]}
                  <span className="font-medium text-ink-900">{g.label}</span>
                  <span className="text-ink-500">
                    — {STATE_WORD[g.state]}
                    {g.items.length > 1
                      ? ` (${g.items.length - notPass.length} of ${g.items.length} match)`
                      : g.items[0]?.detail
                        ? ` · ${g.items[0].detail}`
                        : ''}
                  </span>
                </summary>
                {g.items.length > 1 || notPass.some((i) => i.target) ? (
                  <ul className="ml-5 mt-0.5 space-y-0.5 text-[11px]">
                    {(notPass.length ? notPass : g.items).slice(0, 30).map((i) => (
                      <li key={i.key} className="flex min-w-0 flex-wrap items-center gap-1.5">
                        {STATE_ICON[i.state]}
                        {i.nodeId ? <span className="font-medium text-ink-800" title={i.nodeId}>{labelFor?.(i.nodeId) || humanNodeLabel(i.nodeId)}</span> : null}
                        {i.target ? <span className="min-w-0 max-w-full truncate font-mono text-ink-600" title={i.target}>{i.target}</span> : null}
                        {i.detail ? <span className="text-ink-500">{i.detail}</span> : null}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </details>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// ── Replay ─────────────────────────────────────────────────────────────

export function ReplayPanel({
  graphHash,
  seed,
  busy,
  conflict,
  onReplay,
  onCancel,
}: {
  graphHash: string
  seed: number | null
  busy: boolean
  /** 409 inputs_changed diff (null until the server reports one). */
  conflict: { message: string; changes: InputChange[] } | null
  onReplay: (force: boolean) => void
  onCancel: () => void
}) {
  return (
    <div role="dialog" aria-label="Replay exactly" className="w-full space-y-2 rounded-lg border border-ink-200 bg-white px-3 py-2 text-[12px] text-ink-700">
      {conflict ? (
        <>
          <p className="font-semibold text-amber-950">
            {conflict.message || 'Some inputs changed since this run — a replay would not see the same data.'}
          </p>
          <ul className="max-h-40 space-y-0.5 overflow-y-auto text-[11px]">
            {conflict.changes.map((c, i) => (
              <li key={`${c.label}-${i}`} className="flex min-w-0 flex-wrap items-center gap-1.5">
                <span className="rounded bg-amber-100 px-1 text-[10px] font-semibold text-amber-900">{c.change}</span>
                <span className="min-w-0 max-w-full truncate font-mono" title={c.label}>{c.label || 'input'}</span>
                {c.recorded || c.current ? (
                  <span className="font-mono text-ink-500">
                    {c.recorded ? shortHash(c.recorded, 10) : '—'} → {c.current ? shortHash(c.current, 10) : 'missing'}
                  </span>
                ) : null}
              </li>
            ))}
            {conflict.changes.length === 0 ? <li className="text-ink-500">The server did not list which inputs changed.</li> : null}
          </ul>
          <div className="flex flex-wrap gap-1.5">
            <button type="button" className="btn-danger !px-2 !py-1 text-[11px]" disabled={busy} onClick={() => onReplay(true)}>
              {busy ? 'Starting…' : 'Replay anyway'}
            </button>
            <button type="button" className="btn-quiet !px-2 !py-1 text-[11px]" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <p>
            Starts a <span className="font-semibold">new run</span> from this run’s exact graph snapshot
            {graphHash ? (
              <>
                {' '}
                (<span className="font-mono" title={graphHash}>{shortHash(graphHash)}</span>)
              </>
            ) : null}{' '}
            with the same seed{seed != null ? <span className="font-mono"> {seed}</span> : ''} and configuration — not
            the pipeline as it is in the Editor now. Inputs are checked against their recorded hashes first.
          </p>
          <div className="flex flex-wrap gap-1.5">
            <button type="button" className="btn-primary !px-2 !py-1 text-[11px]" disabled={busy} onClick={() => onReplay(false)}>
              {busy ? 'Starting…' : 'Replay exactly'}
            </button>
            <button type="button" className="btn-quiet !px-2 !py-1 text-[11px]" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </>
      )}
    </div>
  )
}
