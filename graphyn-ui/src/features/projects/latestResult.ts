/**
 * Home "Latest result" card (pure): the newest run that reported a headline
 * metric, its regression vs the best previous run, and the registered model
 * that came from it (if any).
 */
import { primaryMetric, regressionOf, type PrimaryMetric, type RegressionInfo } from '../../lib/metrics'

export type LatestResult<R> = {
  run: R
  metric: PrimaryMetric
  regression: RegressionInfo | null
  /** Registered model whose stages point at this run. */
  modelName: string | null
}

type RunLike = { run_id: string; status?: string; created_at?: string }
type ModelLike = { name: string; stages?: Record<string, { run_id?: string; source_run_id?: string } | null | undefined> }

/** Runs are newest-first (GET /runs order); failed runs never count as a result. */
export function pickLatestResult<R extends RunLike>(runs: readonly R[], models: readonly ModelLike[] = []): LatestResult<R> | null {
  for (const run of runs) {
    if (/fail|error|cancel/i.test(run.status || '')) continue
    const metric = primaryMetric(run)
    if (!metric) continue
    const model = models.find((m) =>
      Object.values(m.stages || {}).some((st) => st && (st.run_id === run.run_id || st.source_run_id === run.run_id)),
    )
    return { run, metric, regression: regressionOf(run), modelName: model?.name ?? null }
  }
  return null
}

/** Tone for the regression badge: worse than the best previous run = regression. */
export function regressionTone(reg: RegressionInfo | null, lowerIsBetter = false): 'better' | 'worse' | 'same' | null {
  if (!reg) return null
  const d = lowerIsBetter ? -reg.delta : reg.delta
  if (Math.abs(d) < 1e-9) return 'same'
  return d > 0 ? 'better' : 'worse'
}
