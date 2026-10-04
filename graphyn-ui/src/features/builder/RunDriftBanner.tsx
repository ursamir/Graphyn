/**
 * Editor ↔ run drift banner: the canvas no longer matches the exact graph a
 * run executed ("This pipeline changed since run X"), or the canvas is that
 * run's read-only snapshot. Diff logic: graphDrift.ts.
 */
import React from 'react'
import { GitCompare, History, X } from 'lucide-react'
import { shortRunId } from '../../lib/format'
import { describeDriftChange, type DriftChange } from './graphDrift'

export function RunDriftBanner({
  runId,
  runTitle,
  changes,
  snapshot,
  savedPipelineChanged,
  labelFor,
  onOpenSnapshot,
  onSaveAsNew,
  onExitSnapshot,
  onOpenRun,
  onDismiss,
}: {
  runId: string
  runTitle: string
  /** Canvas vs run graph; null while loading. */
  changes: DriftChange[] | null
  /** Canvas is the run's exact snapshot. */
  snapshot: boolean
  /** Backend `pipeline_drift.drifted` — the saved pipeline changed since the run. */
  savedPipelineChanged?: { pipeline: string } | null
  labelFor?: (nodeId: string) => string | undefined
  onOpenSnapshot: () => void
  onSaveAsNew: () => void
  onExitSnapshot: () => void
  onOpenRun: () => void
  onDismiss: () => void
}) {
  const [compareOpen, setCompareOpen] = React.useState(false)
  const runLink = (
    <button
      type="button"
      className="font-medium text-accent-800 underline-offset-2 hover:underline"
      title={`Open run ${runId}`}
      onClick={onOpenRun}
    >
      {runTitle || `run ${shortRunId(runId)}`}
    </button>
  )
  if (snapshot) {
    const edited = (changes?.length ?? 0) > 0
    return (
      <div role="status" className="border-b border-sky-200 bg-sky-50 px-3 py-1.5 text-[12px] text-sky-950">
        <div className="flex flex-wrap items-center gap-2">
          <History className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            <span className="font-semibold">Read-only snapshot</span> of {runLink}
            <span className="font-mono text-[11px] text-sky-800"> {shortRunId(runId)}</span> — the exact graph that run
            executed (run-scoped output folders removed). Save keeps it as a <span className="font-semibold">new</span>{' '}
            pipeline; it never overwrites the original.
            {edited ? <span className="ml-1 text-amber-800">· {changes!.length} edit{changes!.length === 1 ? '' : 's'} since opening</span> : null}
          </span>
          <span className="ml-auto flex shrink-0 items-center gap-1">
            <button type="button" className="btn-secondary !px-2 !py-0.5 text-[11px]" onClick={onSaveAsNew}>
              Save as new…
            </button>
            <button type="button" className="btn-quiet !px-2 !py-0.5 text-[11px]" onClick={onExitSnapshot} title="Keep the canvas but stop treating it as a snapshot">
              Close snapshot
            </button>
          </span>
        </div>
      </div>
    )
  }
  if (!changes || changes.length === 0) {
    if (!savedPipelineChanged) return null
  }
  const n = changes?.length ?? 0
  return (
    <div role="status" className="border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-[12px] text-amber-950">
      <div className="flex flex-wrap items-center gap-2">
        <GitCompare className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>
          {n > 0 ? (
            <>
              This pipeline changed since {runLink} — {n} difference{n === 1 ? '' : 's'} from the graph that run executed.
            </>
          ) : (
            <>
              The saved pipeline{savedPipelineChanged?.pipeline ? ` “${savedPipelineChanged.pipeline}”` : ''} changed since{' '}
              {runLink}.
            </>
          )}
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-1">
          <button type="button" className="btn-secondary !px-2 !py-0.5 text-[11px]" onClick={onOpenSnapshot}>
            Open run’s exact graph
          </button>
          {n > 0 ? (
            <button
              type="button"
              className="btn-quiet !px-2 !py-0.5 text-[11px]"
              aria-expanded={compareOpen}
              onClick={() => setCompareOpen((v) => !v)}
            >
              {compareOpen ? 'Hide changes' : 'Compare'}
            </button>
          ) : null}
          <button type="button" className="btn-icon" aria-label="Dismiss" title="Dismiss" onClick={onDismiss}>
            <X className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>
      {compareOpen && n > 0 ? (
        <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto rounded-md border border-amber-200 bg-white px-2 py-1 font-mono text-[11px] text-ink-800">
          {changes!.slice(0, 60).map((c, i) => (
            <li key={i} className="truncate" title={describeDriftChange(c, labelFor)}>
              <span className="text-ink-400">{c.kind.startsWith('node-added') || c.kind === 'edge-added' ? '+ ' : c.kind.includes('removed') ? '− ' : '~ '}</span>
              {describeDriftChange(c, labelFor)}
            </li>
          ))}
          {n > 60 ? <li className="text-ink-400">+{n - 60} more</li> : null}
          <li className="pt-0.5 font-sans text-[10px] text-ink-400">Left = run · right = canvas now</li>
        </ul>
      ) : null}
    </div>
  )
}
