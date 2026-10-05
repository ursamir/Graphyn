/**
 * Compare runs — "what changed" view over `GET /runs/compare/diff`.
 * Summary sentence → Settings that differ (by path / step) → Results per path
 * → Data → Code → Environment (differences only). Run columns scroll
 * horizontally with a sticky first column (ResponsiveTable).
 */
import React from 'react'
import clsx from 'clsx'
import { Trophy } from 'lucide-react'
import { ResponsiveTable } from '../../components/ResponsiveTable'
import { StatusBadge } from '../../components/ui'
import { formatLocaleDateTime, formatRelativeTime, humanNodeLabel } from '../../lib/format'
import { isRatioMetric, metricLabel } from '../../lib/metrics'
import {
  bestValueIndex,
  diffSummarySentence,
  envKeyLabel,
  formatDiffValue,
  groupSettings,
  metricCell,
  resultGroups,
  runColumnTitle,
  type CompareDiff,
  type DiffRun,
} from './compareDiff'

const CELL = 'min-w-[8.5rem] max-w-[14rem] px-2 py-1.5 align-top text-[12px]'
const KEY_CELL = 'min-w-[9rem] max-w-[15rem] px-3 py-1.5 align-top text-[12px]'

function RunHeaderCells({ runs, onOpenRun }: { runs: DiffRun[]; onOpenRun?: (runId: string) => void }) {
  return (
    <>
      {runs.map((r) => {
        const t = runColumnTitle(r)
        return (
          <th key={r.runId} className={clsx(CELL, 'bg-ink-50 text-left font-normal')} title={`${r.runId}${r.name ? ` · ${r.name}` : ''}`}>
            <div className="flex min-w-0 items-center gap-1.5">
              {onOpenRun ? (
                <button
                  type="button"
                  className="font-mono text-[11px] text-accent-800 hover:underline"
                  onClick={() => onOpenRun(r.runId)}
                >
                  {t.short}
                </button>
              ) : (
                <span className="font-mono text-[11px] text-ink-700">{t.short}</span>
              )}
              <StatusBadge kind="run" status={r.status} />
            </div>
            <div className="truncate text-[12px] font-medium text-ink-900">{t.name}</div>
            {r.startedAt ? (
              <div className="text-[11px] text-ink-500" title={formatLocaleDateTime(r.startedAt)}>
                {formatRelativeTime(r.startedAt)}
              </div>
            ) : null}
          </th>
        )
      })}
    </>
  )
}

function Section({
  title,
  note,
  actions,
  children,
}: {
  title: string
  note?: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="ui-card ui-card-flush min-w-0 overflow-hidden" aria-label={title}>
      <div className="flex flex-wrap items-center justify-between gap-2 px-3.5 pt-3 pb-2">
        <h3 className="ide-section-title">
          {title}
          {note ? <span className="ml-2 font-normal text-ink-500">{note}</span> : null}
        </h3>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </section>
  )
}

function GroupRow({ title, span, extra }: { title: string; span: number; extra?: React.ReactNode }) {
  return (
    <tr className="border-t border-ink-100 bg-ink-50/60">
      <td colSpan={span} className="px-3 py-1 text-[11px] font-semibold text-ink-700">
        {title}
        {extra}
      </td>
    </tr>
  )
}

export function CompareDiffView({
  diff,
  showAll,
  onToggleAll,
  onOpenRun,
  busy,
}: {
  diff: CompareDiff
  showAll: boolean
  onToggleAll: () => void
  onOpenRun?: (runId: string) => void
  busy?: boolean
}) {
  const [allMetrics, setAllMetrics] = React.useState(false)
  const runs = diff.runs
  const span = runs.length + 1
  const settingGroups = groupSettings(diff.settings)
  const results = resultGroups(diff)
  const envDiff = diff.environment.filter((e) => e.differs)
  const s = diff.summary

  return (
    <div className="min-w-0 space-y-3">
      <p className="rounded-lg border border-ink-200 bg-white px-3 py-2 text-[13px] text-ink-800" role="status">
        <span className="font-medium">{diffSummarySentence(s)}</span>
        {s.graphSame === false ? <span className="text-ink-500"> · different pipeline graph</span> : null}
      </p>

      <Section
        title="Settings that differ"
        note={showAll ? `${diff.settings.length} settings` : undefined}
        actions={
          <label className="inline-flex items-center gap-1.5 text-[12px] text-ink-600">
            <input type="checkbox" checked={showAll} disabled={busy} onChange={onToggleAll} />
            Show all settings
          </label>
        }
      >
        {settingGroups.length === 0 ? (
          <p className="px-3.5 pb-3 text-[12px] text-ink-500">Every step setting is the same in these runs.</p>
        ) : (
          <ResponsiveTable>
            <table className="w-max min-w-full border-separate border-spacing-0">
              <thead>
                <tr>
                  <th className={clsx(KEY_CELL, 'bg-ink-50 text-left text-[11px] font-medium text-ink-500')}>Setting</th>
                  <RunHeaderCells runs={runs} onOpenRun={onOpenRun} />
                </tr>
              </thead>
              <tbody>
                {settingGroups.map((g) => (
                  <React.Fragment key={g.key}>
                    <GroupRow title={g.title} span={span} />
                    {g.rows.map((row) => (
                      <tr key={`${g.key}.${row.key}`} className="border-t border-ink-50">
                        <td className={clsx(KEY_CELL, row.differs ? 'font-medium text-ink-900' : 'text-ink-600')} title={`${row.nodeId}.${row.key}`}>
                          <span className="block truncate">{row.key}</span>
                          {row.hasDefault ? (
                            <span className="block truncate text-[11px] font-normal text-ink-400">
                              default {formatDiffValue(row.default)}
                            </span>
                          ) : null}
                        </td>
                        {runs.map((r, i) => {
                          const present = row.present[i] !== false
                          const v = row.values[i]
                          const text = present ? formatDiffValue(v) : 'step not in run'
                          const isDefault = row.hasDefault && present && JSON.stringify(v) === JSON.stringify(row.default)
                          return (
                            <td
                              key={r.runId}
                              className={clsx(
                                CELL,
                                'truncate font-mono text-[11px]',
                                !present ? 'italic text-ink-400' : row.differs ? 'bg-amber-50 text-amber-950' : 'text-ink-700',
                                isDefault && row.differs && 'text-ink-500',
                              )}
                              title={text}
                            >
                              {text}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </ResponsiveTable>
        )}
      </Section>

      <Section
        title="Results"
        note={diff.primaryMetric ? `by ${metricLabel(diff.primaryMetric)}` : undefined}
        actions={
          results.some((g) => g.rows.length > 1) ? (
            <button type="button" className="text-[12px] text-accent-800 hover:underline" onClick={() => setAllMetrics((v) => !v)}>
              {allMetrics ? 'Primary metric only' : 'All metrics'}
            </button>
          ) : null
        }
      >
        {results.length === 0 ? (
          <p className="px-3.5 pb-3 text-[12px] text-ink-500">No metrics recorded for these runs.</p>
        ) : (
          <ResponsiveTable>
            <table className="w-max min-w-full border-separate border-spacing-0">
              <thead>
                <tr>
                  <th className={clsx(KEY_CELL, 'bg-ink-50 text-left text-[11px] font-medium text-ink-500')}>Path · metric</th>
                  <RunHeaderCells runs={runs} onOpenRun={onOpenRun} />
                </tr>
              </thead>
              <tbody>
                {results.map((g) => {
                  const rows = allMetrics ? g.rows : g.rows.slice(0, 1)
                  return (
                    <React.Fragment key={g.pathId}>
                      {results.length > 1 || g.pathId !== 'run' ? <GroupRow title={g.pathLabel} span={span} /> : null}
                      {rows.map((row, ri) => {
                        const bestIdx = bestValueIndex(row.metric, row.values)
                        const primary = ri === 0
                        return (
                          <tr key={`${g.pathId}.${row.metric}`} className="border-t border-ink-50">
                            <td className={clsx(KEY_CELL, primary ? 'font-medium text-ink-900' : 'text-ink-600')} title={row.metric}>
                              {metricLabel(row.metric)}
                            </td>
                            {runs.map((r, i) => {
                              const v = row.values[i] ?? null
                              const isBest = bestIdx === i
                              const pathBest = primary && row.best[i] && results.length > 1
                              const ratio = v != null && isRatioMetric(row.metric, v)
                              return (
                                <td
                                  key={r.runId}
                                  className={clsx(
                                    CELL,
                                    'tabular-nums',
                                    isBest ? 'font-semibold text-emerald-800' : row.differs ? 'text-ink-900' : 'text-ink-600',
                                  )}
                                  title={row.pathLabels[i] ? `${row.pathLabels[i]}${pathBest ? ' · best path of this run' : ''}` : undefined}
                                >
                                  <span className="inline-flex items-center gap-1">
                                    {metricCell(row.metric, v)}
                                    {pathBest ? <Trophy className="h-3 w-3 text-amber-500" aria-label="best path of this run" /> : null}
                                  </span>
                                  {primary && ratio ? (
                                    <span className="mt-0.5 block h-1 w-full max-w-[7rem] overflow-hidden rounded-full bg-ink-100" aria-hidden>
                                      <span
                                        className={clsx('block h-full rounded-full', isBest ? 'bg-emerald-500' : 'bg-ink-300')}
                                        style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%` }}
                                      />
                                    </span>
                                  ) : null}
                                </td>
                              )
                            })}
                          </tr>
                        )
                      })}
                    </React.Fragment>
                  )
                })}
              </tbody>
            </table>
          </ResponsiveTable>
        )}
      </Section>

      <Section title="Data" note={s.dataSame === true ? 'same in every run' : s.dataSame === false ? 'different' : undefined}>
        {diff.data.length === 0 ? (
          <p className="px-3.5 pb-3 text-[12px] text-ink-500">
            {s.dataSame === false ? 'Data differs, but no input details were recorded.' : 'Every run read the same input files (same content hashes).'}
          </p>
        ) : (
          <ResponsiveTable>
            <table className="w-max min-w-full border-separate border-spacing-0">
              <thead>
                <tr>
                  <th className={clsx(KEY_CELL, 'bg-ink-50 text-left text-[11px] font-medium text-ink-500')}>Input</th>
                  <RunHeaderCells runs={runs} onOpenRun={onOpenRun} />
                </tr>
              </thead>
              <tbody>
                {diff.data.map((d) => (
                  <tr key={`${d.nodeId}.${d.key}`} className="border-t border-ink-50">
                    <td className={clsx(KEY_CELL, 'text-ink-800')} title={`${d.nodeId} · ${d.key}`}>
                      {d.label}
                    </td>
                    {runs.map((r, i) => {
                      const h = d.hashes[i]
                      const fc = d.fileCounts[i]
                      const ver = d.datasetVersions[i]
                      return (
                        <td
                          key={r.runId}
                          className={clsx(CELL, d.differs ? 'bg-amber-50 text-amber-950' : 'text-ink-700')}
                          title={[d.paths[i], h].filter(Boolean).join('\n') || undefined}
                        >
                          {h ? <span className="font-mono text-[11px]">{h.replace(/^sha256:/i, '').slice(0, 8)}</span> : <span className="text-ink-400">not recorded</span>}
                          {fc != null ? <span className="text-ink-500"> · {fc.toLocaleString('en-US')} files</span> : null}
                          {ver ? <span className="text-ink-500"> · {ver}</span> : null}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </ResponsiveTable>
        )}
      </Section>

      <Section title="Code" note={s.codeSame === true ? 'same plugin versions and code' : s.codeSame === false ? 'different' : undefined}>
        {diff.code.length === 0 ? (
          <p className="px-3.5 pb-3 text-[12px] text-ink-500">Every step ran the same plugin version and code.</p>
        ) : (
          <ResponsiveTable>
            <table className="w-max min-w-full border-separate border-spacing-0">
              <thead>
                <tr>
                  <th className={clsx(KEY_CELL, 'bg-ink-50 text-left text-[11px] font-medium text-ink-500')}>Step type</th>
                  <RunHeaderCells runs={runs} onOpenRun={onOpenRun} />
                </tr>
              </thead>
              <tbody>
                {diff.code.map((c) => (
                  <tr key={c.nodeType} className="border-t border-ink-50">
                    <td className={clsx(KEY_CELL, 'text-ink-800')} title={c.nodeType}>
                      {humanNodeLabel(c.nodeType)}
                    </td>
                    {runs.map((r, i) => (
                      <td key={r.runId} className={clsx(CELL, 'text-ink-700')} title={[c.plugins[i], c.versions[i], c.codeHashes[i]].filter(Boolean).join(' · ') || undefined}>
                        <span className={clsx(c.versionDiffers && 'rounded bg-amber-50 px-1 text-amber-950')}>
                          {[c.plugins[i], c.versions[i]].filter(Boolean).join(' ') || '—'}
                        </span>
                        {c.codeHashes[i] ? (
                          <span className={clsx('ml-1 font-mono text-[11px]', c.codeDiffers ? 'rounded bg-amber-50 px-1 text-amber-950' : 'text-ink-500')}>
                            {c.codeHashes[i].slice(0, 8)}
                          </span>
                        ) : null}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </ResponsiveTable>
        )}
      </Section>

      <Section title="Environment" note={envDiff.length === 0 ? 'same' : 'differences only'}>
        {envDiff.length === 0 ? (
          <p className="px-3.5 pb-3 text-[12px] text-ink-500">Same Python, libraries and image in every run.</p>
        ) : (
          <ResponsiveTable>
            <table className="w-max min-w-full border-separate border-spacing-0">
              <thead>
                <tr>
                  <th className={clsx(KEY_CELL, 'bg-ink-50 text-left text-[11px] font-medium text-ink-500')}>Item</th>
                  <RunHeaderCells runs={runs} onOpenRun={onOpenRun} />
                </tr>
              </thead>
              <tbody>
                {envDiff.map((e) => (
                  <tr key={e.key} className="border-t border-ink-50">
                    <td className={clsx(KEY_CELL, 'text-ink-800')} title={e.key}>
                      {envKeyLabel(e.key)}
                    </td>
                    {runs.map((r, i) => {
                      const text = formatDiffValue(e.values[i])
                      return (
                        <td key={r.runId} className={clsx(CELL, 'truncate bg-amber-50 font-mono text-[11px] text-amber-950')} title={text}>
                          {text}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </ResponsiveTable>
        )}
      </Section>
    </div>
  )
}
