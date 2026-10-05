/**
 * Ship package summary — contents (+ sha256), "How to run" commands,
 * provenance and the packager self-test, read from the deployment_packager
 * sidecar `<package>.manifest.json`. Used by Ship step 4 (Download) and the
 * package run's Overview in Runs. Renders nothing for packages built before
 * deployment_packager 1.1 (no sidecar).
 */
import React from 'react'
import clsx from 'clsx'
import { CheckCircle2, Copy, FileArchive } from 'lucide-react'
import { ResponsiveTable } from '../../components/ResponsiveTable'
import { CopyableMono, ShortId } from '../../components/ui'
import { formatBytes } from '../../lib/format'
import {
  checkLabel,
  howToRunText,
  inputSummary,
  selftestSummary,
  type ShipManifest,
} from './shipManifest'
import { useShipManifest } from './useShipManifest'

const TONE: Record<string, string> = {
  ok: 'bg-emerald-100 text-emerald-800',
  warn: 'bg-amber-100 text-amber-900',
  bad: 'bg-rose-100 text-rose-800',
  muted: 'bg-ink-100 text-ink-700',
}

const CHECK_DOT: Record<string, string> = {
  passed: 'bg-emerald-500',
  failed: 'bg-rose-500',
  skipped: 'bg-ink-300',
}

function CopyBlock({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = React.useState(false)
  return (
    <div className="relative">
      <pre
        className="max-w-full overflow-x-auto rounded-lg bg-ink-900 px-3 py-2 pr-10 font-mono text-[11px] leading-relaxed text-ink-50"
        data-testid="ship-how-to-run"
      >
        {text}
      </pre>
      <button
        type="button"
        className={clsx(
          'absolute right-1.5 top-1.5 inline-flex h-6 w-6 items-center justify-center rounded text-ink-300 hover:bg-ink-700 hover:text-white',
          copied && 'text-emerald-400',
        )}
        title={copied ? 'Copied' : `Copy ${label}`}
        aria-label={`Copy ${label}`}
        onClick={() => {
          void navigator.clipboard?.writeText(text).then(() => {
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1200)
          })
        }}
      >
        {copied ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  )
}

export function ShipPackageSummary({
  manifest,
  onOpenRun,
  showHowToRun = true,
}: {
  manifest: ShipManifest
  onOpenRun?: (runId: string) => void
  showHowToRun?: boolean
}) {
  const st = selftestSummary(manifest.selftest)
  const input = inputSummary(manifest.input)
  const samples = manifest.selftest.samples.filter((s) => s.file)
  return (
    <section
      className="space-y-3 rounded-xl border border-ink-100 bg-white px-3 py-3 text-xs text-ink-700"
      data-testid="ship-package-summary"
    >
      <div className="flex flex-wrap items-center gap-2">
        <FileArchive className="h-4 w-4 text-ink-400" aria-hidden />
        <span className="min-w-0 truncate font-semibold text-ink-900" title={manifest.packagePath ?? undefined}>
          {manifest.packageName}
        </span>
        {manifest.sizeBytes != null ? <span className="text-ink-500">{formatBytes(manifest.sizeBytes)}</span> : null}
        <span
          className={clsx('ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold', TONE[st.tone])}
          data-testid="ship-selftest-status"
          title={manifest.selftest.mode ? `mode: ${manifest.selftest.mode}` : undefined}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden />
          {st.label}
        </span>
      </div>

      {manifest.warning ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[11px] text-amber-950">
          {manifest.warning}
        </div>
      ) : null}

      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
        <dt className="text-ink-500">Trained in</dt>
        <dd className="min-w-0">
          {manifest.sourceRunId ? (
            <span className="inline-flex flex-wrap items-center gap-1">
              <ShortId id={manifest.sourceRunId} label="source run id" />
              {onOpenRun ? (
                <button type="button" className="btn-quiet !px-1 !py-0 text-[11px]" onClick={() => onOpenRun(manifest.sourceRunId!)}>
                  Open run
                </button>
              ) : null}
              {manifest.testAccuracy != null ? (
                <span className="text-ink-500">· test accuracy {(manifest.testAccuracy * 100).toFixed(1)} %</span>
              ) : null}
            </span>
          ) : (
            <span className="text-ink-500">unknown</span>
          )}
        </dd>
        {manifest.registeredModel ? (
          <>
            <dt className="text-ink-500">Model</dt>
            <dd className="min-w-0 break-words">
              {manifest.registeredModel.name}
              {manifest.registeredModel.stage ? ` · ${manifest.registeredModel.stage}` : ''}
              {manifest.registeredModel.version ? ` · v${manifest.registeredModel.version}` : ''}
            </dd>
          </>
        ) : null}
        {input ? (
          <>
            <dt className="text-ink-500">Input</dt>
            <dd className="min-w-0 break-words">{input}</dd>
          </>
        ) : null}
        {manifest.labels.length ? (
          <>
            <dt className="text-ink-500">Labels</dt>
            <dd className="min-w-0 break-words font-mono text-[11px]">{manifest.labels.join(', ')}</dd>
          </>
        ) : null}
        {manifest.sha256 ? (
          <>
            <dt className="text-ink-500">Package sha256</dt>
            <dd className="min-w-0">
              <CopyableMono value={manifest.sha256} />
            </dd>
          </>
        ) : null}
      </dl>

      {manifest.contents.length ? (
        <ResponsiveTable>
          <table className="w-full text-left text-[11px]" data-testid="ship-package-contents">
            <thead className="text-ink-500">
              <tr>
                <th className="py-1 pr-3 font-medium">File</th>
                <th className="py-1 pr-3 font-medium">What</th>
                <th className="py-1 pr-3 text-right font-medium">Size</th>
                <th className="py-1 font-medium">sha256</th>
              </tr>
            </thead>
            <tbody>
              {manifest.contents.map((c) => (
                <tr key={c.path} className="border-t border-ink-50">
                  <td className="whitespace-nowrap py-1 pr-3 font-mono text-ink-900">{c.path}</td>
                  <td className="whitespace-nowrap py-1 pr-3 text-ink-600">{c.role}</td>
                  <td className="whitespace-nowrap py-1 pr-3 text-right text-ink-600">{formatBytes(c.size)}</td>
                  <td className="whitespace-nowrap py-1 font-mono text-ink-600">
                    {c.sha256 ? (
                      <span className="inline-flex items-center gap-1" title={c.sha256}>
                        {c.sha256.slice(0, 12)}…
                        <CopyableMono value={c.sha256} copyOnly />
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ResponsiveTable>
      ) : null}

      {showHowToRun ? (
        <div className="space-y-1">
          <div className="text-[11px] font-medium text-ink-500">How to run (Linux / macOS)</div>
          <CopyBlock text={howToRunText(manifest)} label="commands" />
          <p className="text-[11px] text-ink-500">
            Audio is resampled to the training rate and turned into the exact training features
            (see <code className="font-mono">preprocessing.json</code>); add <code className="font-mono">--json</code> for
            machine-readable output.
          </p>
        </div>
      ) : null}

      {manifest.selftest.checks.length || manifest.selftest.notes.length ? (
        <details className="group rounded-lg border border-ink-100 px-2.5 py-1.5" open={st.tone === 'bad'}>
          <summary className="cursor-pointer select-none text-[11px] font-medium text-ink-700">
            Self-test details
            {samples.length ? ` · ${samples.length} real clip${samples.length === 1 ? '' : 's'}` : ''}
          </summary>
          <ul className="mt-1.5 space-y-1" data-testid="ship-selftest-checks">
            {manifest.selftest.checks.map((c) => (
              <li key={c.name} className="flex gap-1.5">
                <span
                  className={clsx('mt-1 h-1.5 w-1.5 shrink-0 rounded-full', CHECK_DOT[c.status] ?? 'bg-ink-300')}
                  aria-hidden
                />
                <span className="min-w-0 break-words">
                  <span className="font-medium text-ink-800">{checkLabel(c.name)}</span>{' '}
                  <span className="text-ink-500">({c.status})</span> — {c.detail}
                </span>
              </li>
            ))}
            {manifest.selftest.notes.map((n) => (
              <li key={n} className="text-ink-500">
                {n}
              </li>
            ))}
          </ul>
          {samples.length ? (
            <ResponsiveTable className="mt-1.5">
              <table className="w-full text-left text-[11px]">
                <thead className="text-ink-500">
                  <tr>
                    <th className="py-1 pr-3 font-medium">Clip</th>
                    <th className="py-1 pr-3 font-medium">Folder label</th>
                    <th className="py-1 pr-3 font-medium">Predicted</th>
                    <th className="py-1 font-medium">Feature diff</th>
                  </tr>
                </thead>
                <tbody>
                  {samples.map((s) => (
                    <tr key={s.file} className="border-t border-ink-50">
                      <td className="max-w-[14rem] truncate py-1 pr-3 font-mono" title={s.file}>
                        {s.file.split('/').pop()}
                      </td>
                      <td className="whitespace-nowrap py-1 pr-3">{s.label ?? '—'}</td>
                      <td className="whitespace-nowrap py-1 pr-3">
                        {s.predicted ?? '—'}
                        {s.probability != null ? ` (${(s.probability * 100).toFixed(0)} %)` : ''}
                      </td>
                      <td className="whitespace-nowrap py-1 font-mono">
                        {s.max_abs_diff != null ? s.max_abs_diff.toExponential(1) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ResponsiveTable>
          ) : null}
        </details>
      ) : null}
    </section>
  )
}

/** Fetch + render the sidecar for a package path (nothing when absent). */
export function ShipPackageSummaryForPath({
  packagePath,
  refreshKey,
  onOpenRun,
  showHowToRun,
}: {
  packagePath: string | null | undefined
  refreshKey?: unknown
  onOpenRun?: (runId: string) => void
  showHowToRun?: boolean
}) {
  const { manifest } = useShipManifest(packagePath, refreshKey)
  if (!manifest) return null
  return <ShipPackageSummary manifest={manifest} onOpenRun={onOpenRun} showHowToRun={showHowToRun} />
}
