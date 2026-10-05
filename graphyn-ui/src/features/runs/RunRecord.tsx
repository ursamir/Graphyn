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
import { AlertTriangle, CheckCircle2, CircleHelp, Copy, FileJson, History, ShieldCheck, XCircle } from 'lucide-react'
import { CopyableMono } from '../../components/ui'
import { ActorName } from '../../components/ActorName'
import { apiJson } from '../../api/client'
import { humanNodeLabel, shortRunId } from '../../lib/format'
import {
  buildRunRecord,
  formatAbsoluteLocal,
  formatDurationMs,
  formatUtc,
  formatVerifyWhen,
  gapFor,
  parseVerifyHistory,
  recordCopyText,
  shortHash,
  triggerLabel,
  verifyStripSummary,
  type InputChange,
  type LastVerify,
  type RecordGap,
  type RunRecordView,
  type VerifyGroup,
  type VerifyCounts,
  type VerifyHistoryRow,
  type VerifyState,
} from './runRecord'
import { useRunRecord } from './useRunRecord'
import {
  externalCallRows,
  externalCallsSummary,
  runInputsView,
  webhookAuthLabel,
  webhookReceipt,
  type ExternalCallRow,
} from './runWorkflow'
import { ResponsiveTable } from '../../components/ResponsiveTable'
import { Globe, Mail, Sparkles } from 'lucide-react'
import { recordSummaryParts } from './runOverview'

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
      <dt className="text-[11px] text-ink-500">{label}</dt>
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

/**
 * Overview card: who/when/what exactly ran, with amber gaps on old runs.
 * Collapsed by default to one line ("Run record · Verified ✓ · chain #12 ·
 * seed 42 · 2 not recorded"); everything else is inside the fold.
 */
export function RunRecordCard({
  runId,
  detail,
  graphSeed,
  onViewRaw,
  onOpenRun,
  nodeTypeLabel,
  verify,
  lastVerify,
  stepLabel,
}: {
  /** Step label for a node id (external calls table). */
  stepLabel?: (nodeId: string) => string | undefined
  /** Verify result for this run in this session (null = not verified yet). */
  verify?: { ok: boolean | null; status?: string } | null
  /** Last server-recorded verify (this session's response, else the run's `last_verify`). */
  lastVerify?: LastVerify | null
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
  const webhook = React.useMemo(() => webhookReceipt(prove, meta ?? (detail?.meta as Rec | undefined)), [prove, meta, detail])
  const runInputs = React.useMemo(() => runInputsView(prove, meta ?? (detail?.meta as Rec | undefined)), [prove, meta, detail])
  const calls = React.useMemo(() => externalCallRows(prove, meta ?? (detail?.meta as Rec | undefined)), [prove, meta, detail])
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
  const summary = recordSummaryParts({
    hasProve: view.hasProve,
    pending,
    loading,
    gapCount: view.gaps.length,
    chainPosition: view.chainPosition,
    seed: view.seed,
    verify: verify ?? null,
    lastVerify: lastVerify ?? null,
  })
  return (
    <details className="group/record rounded-xl border border-ink-200 bg-white" aria-label="Run record">
      <summary className="flex cursor-pointer select-none flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 text-[12px] text-ink-600">
        <ShieldCheck className="h-3.5 w-3.5 text-ink-500" aria-hidden />
        <span className="text-[13px] font-semibold text-ink-900">Run record</span>
        <span className="text-ink-300" aria-hidden>
          ·
        </span>
        <span
          className={clsx(
            summary.tone === 'ok' && 'font-medium text-emerald-700',
            summary.tone === 'warn' && 'rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-semibold text-amber-900',
          )}
          title={
            lastVerify
              ? [
                  lastVerify.checkedAt ? formatUtc(lastVerify.checkedAt) : '',
                  lastVerify.actor
                    ? `by ${lastVerify.actor}${lastVerify.actorVerified === true ? ' (verified)' : lastVerify.actorVerified === false ? ' (self-declared)' : ''}`
                    : '',
                ]
                  .filter(Boolean)
                  .join(' · ') || undefined
              : undefined
          }
        >
          {summary.verdict}
        </span>
        {summary.details.map((d) => (
          <React.Fragment key={d}>
            <span className="text-ink-300" aria-hidden>
              ·
            </span>
            <span
              className={clsx(/not recorded/.test(d) && 'text-amber-800')}
              title={/not recorded/.test(d) ? view.gaps.map((g) => `${g.label}: ${g.hint}`).join('\n') : undefined}
            >
              {d}
            </span>
          </React.Fragment>
        ))}
        <span className="ml-auto text-[11px] text-ink-400 group-open/record:hidden">Show</span>
        <span className="ml-auto hidden text-[11px] text-ink-400 group-open/record:inline">Hide</span>
      </summary>
      <div className="flex flex-wrap items-center gap-1 border-t border-ink-100 px-3 py-1.5">
        <span className="text-[11px] text-ink-500">
          {pending
            ? 'Sealed when the run finishes'
            : loading
              ? 'Loading…'
              : view.gaps.length > 0
                ? `${view.gaps.length} field${view.gaps.length === 1 ? '' : 's'} not recorded`
                : 'Complete record'}
        </span>
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
      </div>
      {!pending && !loading && !view.hasProve ? (
        <p className="px-3 py-2 text-[12px] text-amber-900">
          <NotRecorded gap={gapFor(view, 'record')}>no record</NotRecorded>{' '}
          This run has no reproducibility record (prove.json) — it cannot be verified or replayed exactly.
        </p>
      ) : null}
      <dl className="grid gap-x-4 gap-y-2 border-t border-ink-100 px-3 py-2.5 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Started by">
          {view.actor ? (
            <span>
              <ActorName actor={view.actor} verified={view.actorVerified} claimed={view.claimedActor} bold />
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
        {view.lineageModels.length ? (
          <Field label={view.lineageModels.length > 1 ? 'Models' : 'Model'}>
            <span className="inline-flex flex-wrap items-center gap-1">
              {view.lineageModels.map((m) => (
                <span key={`${m.name}:${m.version}:${m.stage}`} className="inline-flex items-center gap-1">
                  <span className="font-medium text-ink-800">{m.name}</span>
                  {[m.stage, m.version && `v${m.version}`].filter(Boolean).length ? (
                    <span className="text-ink-500">{[m.stage, m.version && `v${m.version}`].filter(Boolean).join(' · ')}</span>
                  ) : null}
                  {m.modelHash ? <HashChip value={m.modelHash} label="model_hash" /> : null}
                  {!m.resolved ? <span className="text-amber-700">not found in registry</span> : null}
                </span>
              ))}
            </span>
          </Field>
        ) : null}
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
        {webhook ? (
          <Field label="Triggered by webhook" wide>
            <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span title="Hook id">
                hook <span className="font-mono">{shortHash(webhook.hookId, 8) || '—'}</span>
              </span>
              <span className="text-ink-600">· {webhookAuthLabel(webhook.auth)}</span>
              {webhook.payloadSha256 ? (
                <span className="inline-flex items-center gap-1">
                  · payload <HashChip value={webhook.payloadSha256} label="payload sha256" />
                  {webhook.payloadBytes != null ? <span className="text-ink-500">{webhook.payloadBytes.toLocaleString()} B</span> : null}
                </span>
              ) : null}
              {webhook.idempotencyKey ? (
                <span className="text-ink-600" title="Idempotency-Key header">
                  · key <span className="font-mono">{webhook.idempotencyKey}</span>
                </span>
              ) : null}
              {webhook.sourceIp ? <span className="text-ink-600">· from <span className="font-mono">{webhook.sourceIp}</span></span> : null}
              {webhook.receivedAt ? (
                <span className="text-ink-600" title={formatUtc(webhook.receivedAt)}>
                  · received {formatAbsoluteLocal(webhook.receivedAt)}
                </span>
              ) : null}
            </span>
          </Field>
        ) : null}
        {runInputs ? (
          <Field label="Run inputs" wide>
            <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-0.5">
              {runInputs.inputKeys.length || runInputs.inputsSha256 ? (
                <span className="inline-flex flex-wrap items-center gap-1">
                  <span className="text-ink-500">inputs</span>
                  {runInputs.inputKeys.length ? <span className="font-mono text-[11px]">{runInputs.inputKeys.join(', ')}</span> : null}
                  {runInputs.inputsSha256 ? <HashChip value={runInputs.inputsSha256} label="inputs sha256" /> : null}
                  {runInputs.inputsBytes != null ? <span className="text-ink-500">{runInputs.inputsBytes.toLocaleString()} B</span> : null}
                </span>
              ) : null}
              {runInputs.parameterNames.length || runInputs.parametersSha256 ? (
                <span className="inline-flex flex-wrap items-center gap-1">
                  <span className="text-ink-500">parameters</span>
                  {runInputs.parameterNames.length ? <span className="font-mono text-[11px]">{runInputs.parameterNames.join(', ')}</span> : null}
                  {runInputs.parametersSha256 ? <HashChip value={runInputs.parametersSha256} label="parameters sha256" /> : null}
                </span>
              ) : null}
            </span>
            <span className="block text-[10.5px] text-ink-400">Fingerprints only — the values themselves are not stored in the record.</span>
          </Field>
        ) : null}
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
                <thead className="text-[11px] text-ink-500">
                  <tr>
                    <th className="px-3 py-1 font-medium">Step type</th>
                    <th className="px-2 py-1 font-medium">Version</th>
                    <th className="px-2 py-1 font-medium">Code hash</th>
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
                <Field label="Image">
                  {!view.environment.image ? (
                    <span className="text-ink-400">not recorded</span>
                  ) : !/^(sha256:)?[0-9a-f]{32,}$/i.test(view.environment.image) ? (
                    // Names like "graphyn-api:local" or "docker container <id> (…)"
                    // are read as text; only digests get the shortened hash chip.
                    <span className="font-mono text-ink-600">{view.environment.image}</span>
                  ) : (
                    <HashChip value={view.environment.image} label="image" />
                  )}
                </Field>
                <Field label="Git">{view.environment.git ? <span className="font-mono">{view.environment.git}</span> : <span className="text-ink-400">—</span>}</Field>
                {view.environment.libs.length ? (
                  <Field label="API host libraries" wide>
                    <span className="font-mono text-[10px] text-ink-600">
                      {view.environment.libs.map(([k, v]) => `${k} ${v}`).join(' · ')}
                    </span>
                  </Field>
                ) : null}
                {view.environment.pluginLibs.map((p) => (
                  <Field key={p.plugin} label={`Plugin env · ${p.plugin}`} wide>
                    <span className="font-mono text-[10px] text-ink-600">
                      {[p.python && `Python ${p.python}`, ...p.libs.map(([k, v]) => `${k} ${v}`)].filter(Boolean).join(' · ')}
                    </span>
                  </Field>
                ))}
              </dl>
            ) : null}
          </details>
        </div>
      ) : null}
      {calls.length ? <ExternalCallsFold rows={calls} stepLabel={stepLabel} /> : null}
    </details>
  )
}

const CALL_ICON: Record<string, React.ReactNode> = {
  http: <Globe className="h-3.5 w-3.5 text-ink-500" aria-label="HTTP" />,
  smtp: <Mail className="h-3.5 w-3.5 text-ink-500" aria-label="Email (SMTP)" />,
  llm: <Sparkles className="h-3.5 w-3.5 text-ink-500" aria-label="LLM" />,
}

/** Record `external_calls`: one compact row per outbound call (URL redacted server-side). */
function ExternalCallsFold({ rows, stepLabel }: { rows: ExternalCallRow[]; stepLabel?: (nodeId: string) => string | undefined }) {
  const failed = rows.some((r) => r.ok === false)
  return (
    <details className="border-t border-ink-100" open={failed || undefined}>
      <summary className="flex cursor-pointer select-none items-center gap-2 px-3 py-1.5 text-[11px] font-medium text-ink-600">
        External calls
        <span className={clsx('font-normal', failed ? 'text-rose-700' : 'text-ink-500')}>{externalCallsSummary(rows)}</span>
      </summary>
      <ResponsiveTable className="px-3 pb-2">
        <table className="w-full text-left text-[11px]">
          <thead className="text-ink-500">
            <tr>
              <th className="py-1 pr-2 font-medium">Step</th>
              <th className="px-2 py-1 font-medium">Call</th>
              <th className="px-2 py-1 font-medium">Status</th>
              <th className="px-2 py-1 text-right font-medium">Time</th>
              <th className="px-2 py-1 font-medium">Request / response</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 200).map((r) => (
              <tr key={r.key} className="border-t border-ink-50 align-top">
                <td className="max-w-[10rem] truncate py-1 pr-2 text-ink-800" title={r.nodeId}>
                  {stepLabel?.(r.nodeId) || r.nodeId || '—'}
                </td>
                <td className="max-w-[18rem] px-2 py-1">
                  <span className="inline-flex min-w-0 max-w-full items-center gap-1" title={`${r.kind} ${r.method} ${r.url}`.trim()}>
                    {CALL_ICON[r.kind] ?? CALL_ICON.http}
                    {r.method ? <span className="font-mono font-semibold text-ink-700">{r.method}</span> : null}
                    <span className="min-w-0 truncate font-mono text-ink-600">{r.url || r.kind}</span>
                  </span>
                  {r.error ? <span className="block truncate text-rose-700" title={r.error}>{r.error}</span> : null}
                </td>
                <td className="px-2 py-1">
                  <span className={clsx('font-mono', r.ok === false ? 'font-semibold text-rose-700' : 'text-ink-700')}>{r.status || '—'}</span>
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right tabular-nums text-ink-600">
                  {r.durationMs != null ? formatDurationMs(r.durationMs) : '—'}
                </td>
                <td className="whitespace-nowrap px-2 py-1">
                  {r.requestSha256 ? <HashChip value={r.requestSha256} label="request sha256" /> : <span className="text-ink-400">—</span>}
                  <span className="text-ink-300"> / </span>
                  {r.responseSha256 ? <HashChip value={r.responseSha256} label="response sha256" /> : <span className="text-ink-400">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > 200 ? <p className="pt-1 text-[10.5px] text-ink-400">+{rows.length - 200} more — View raw record</p> : null}
      </ResponsiveTable>
    </details>
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

/**
 * Verify result as one compact, dismissible strip
 * ("Verified ✓ · 6/6 checks · Oct 4 17:59 · Details"); the per-group checklist
 * expands under it on demand so the run detail does not jump.
 */
export function VerifyChecklist({
  groups,
  ok,
  status,
  verifiedAt,
  labelFor,
  onClose,
  counts,
  actor,
  runId,
  historyCount,
}: {
  groups: VerifyGroup[]
  ok: boolean | null
  status: string
  verifiedAt?: string
  labelFor?: (nodeId: string) => string | undefined
  onClose: () => void
  /** Server `summary` counts (passed/total) — win over the client item count. */
  counts?: VerifyCounts | null
  /** Who ran this verify (server response; absent on older APIs). */
  actor?: { name: string; verified: boolean | null; claimed: string } | null
  /** Enables "History (N)" → GET /runs/{id}/verify/history. */
  runId?: string
  /** Server `history_count` (incl. this verify); history hidden when absent. */
  historyCount?: number | null
}) {
  const [open, setOpen] = React.useState(false)
  const [historyOpen, setHistoryOpen] = React.useState(false)
  const s = verifyStripSummary(groups, ok, status, counts)
  return (
    <div
      role="status"
      aria-label="Verify result"
      className={clsx(
        'w-full min-w-0 rounded-md border px-2.5 py-1 text-[12px]',
        s.tone === 'ok'
          ? 'border-emerald-200 bg-emerald-50/50'
          : s.tone === 'bad'
            ? 'border-rose-200 bg-rose-50/50'
            : 'border-amber-200 bg-amber-50/50',
      )}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        {s.tone === 'ok' ? STATE_ICON.pass : s.tone === 'bad' ? STATE_ICON.failed : STATE_ICON.changed}
        <span className="min-w-0 flex-1 truncate">
          <span className="font-semibold text-ink-900">{s.verdict}</span>
          {s.total > 0 ? (
            <span className="text-ink-600">
              {' '}
              · {s.passed}/{s.total} checks
            </span>
          ) : null}
          {verifiedAt ? (
            <span className="text-ink-500" title={formatUtc(verifiedAt)}>
              {' '}
              · {formatAbsoluteLocal(verifiedAt)}
            </span>
          ) : null}
          {actor && actor.name ? (
            <span className="text-ink-500">
              {' '}
              · by <ActorName actor={actor.name} verified={actor.verified} claimed={actor.claimed} compact />
            </span>
          ) : null}
        </span>
        {runId && historyCount != null && historyCount > 0 ? (
          <button
            type="button"
            className="inline-flex shrink-0 items-center gap-0.5 text-[11px] font-medium text-accent-800 hover:underline"
            aria-expanded={historyOpen}
            title="Every verify of this run: who, when and the result"
            onClick={() => setHistoryOpen((v) => !v)}
          >
            <History className="h-3 w-3" aria-hidden /> History ({historyCount})
          </button>
        ) : null}
        {groups.length > 0 ? (
          <button
            type="button"
            className="shrink-0 text-[11px] font-medium text-accent-800 hover:underline"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? 'Hide details' : 'Details'}
          </button>
        ) : null}
        <button type="button" className="btn-quiet shrink-0 !px-1 !py-0.5" aria-label="Dismiss verify result" title="Dismiss" onClick={onClose}>
          <XCircle className="h-3.5 w-3.5 text-ink-400" />
        </button>
      </div>
      {historyOpen && runId ? <VerifyHistoryList runId={runId} /> : null}
      {open ? (
        <ul className="mt-1 max-h-56 space-y-1 overflow-y-auto border-t border-black/5 pt-1">
          {groups.map((g) => {
            const notPass = g.items.filter((i) => i.state !== 'pass')
            return (
              <li key={g.group}>
                <details open={g.state === 'failed' || g.state === 'changed'}>
                  <summary className="flex cursor-pointer select-none items-center gap-1.5">
                    {STATE_ICON[g.state]}
                    <span className="font-medium text-ink-900">{g.label}</span>
                    <span className="min-w-0 truncate text-ink-500">
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
      ) : null}
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

/** Verify history (newest first): when · who (verified tick) · result · passed/total. */
function VerifyHistoryList({ runId }: { runId: string }) {
  const [state, setState] = React.useState<{ rows: VerifyHistoryRow[]; total: number } | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  React.useEffect(() => {
    let alive = true
    setState(null)
    setError(null)
    apiJson<unknown>(`/runs/${encodeURIComponent(runId)}/verify/history`, { query: { limit: 50 } })
      .then((raw) => {
        if (alive) setState(parseVerifyHistory(raw))
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      alive = false
    }
  }, [runId])
  return (
    <div className="mt-1 border-t border-black/5 pt-1" aria-label="Verify history">
      {error ? (
        <p className="text-[11px] text-rose-700">Couldn’t load verify history — {error}</p>
      ) : !state ? (
        <p className="text-[11px] text-ink-500">Loading history…</p>
      ) : state.rows.length === 0 ? (
        <p className="text-[11px] text-ink-500">No earlier verifies recorded.</p>
      ) : (
        <ul className="max-h-56 space-y-0.5 overflow-y-auto text-[11px]">
          {state.rows.map((h, i) => (
            <li key={`${h.checkedAt}-${i}`} className="flex min-w-0 flex-wrap items-center gap-x-1.5">
              {h.ok ? STATE_ICON.pass : h.status === 'unsealed' ? STATE_ICON.unknown : STATE_ICON.failed}
              <span className="tabular-nums text-ink-700" title={formatUtc(h.checkedAt)}>
                {formatVerifyWhen(h.checkedAt) || '—'}
              </span>
              <span className="text-ink-400">·</span>
              <ActorName actor={h.actor} verified={h.actorVerified} claimed={h.claimedActor} compact className="text-ink-800" />
              <span className="text-ink-400">·</span>
              <span className={clsx(h.ok ? 'text-emerald-700' : 'text-rose-700')}>
                {h.ok ? 'Verified' : h.status === 'unsealed' ? 'Not sealed' : 'Failed'}
              </span>
              {h.total != null && h.total > 0 ? (
                <span className="tabular-nums text-ink-500">
                  {h.passed ?? 0}/{h.total}
                </span>
              ) : null}
              {h.recordHash ? (
                <span className="font-mono text-ink-400" title={`Record hash ${h.recordHash}`}>
                  {shortHash(h.recordHash)}
                </span>
              ) : null}
            </li>
          ))}
          {state.total > state.rows.length ? (
            <li className="text-ink-400">{state.total - state.rows.length} older not shown</li>
          ) : null}
        </ul>
      )}
    </div>
  )
}
