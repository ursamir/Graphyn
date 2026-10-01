/**
 * Compare runs: fold each run's node config params (from its graph.json) into
 * the `/experiments/compare` payload so the param table / CSV show
 * `node_id.field` rows. Experiment-level params win on key clashes
 * (`mergeRunParams`); `param_keys` is rebuilt from `compareParamRows`.
 * Pure — no React / fetch — so it is unit-tested in the node env.
 */
import { compareParamRows, mergeRunParams } from '../runs/runCompare'

type GraphLike = Parameters<typeof mergeRunParams>[1]

export function enrichCompareParams<
  P extends { param_keys: string[]; runs: Array<{ run_id: string; parameters?: Record<string, unknown> }> },
>(payload: P, graphs: ReadonlyMap<string, GraphLike>): P {
  const runs = payload.runs.map((r) => ({
    ...r,
    parameters: mergeRunParams(r.parameters, graphs.get(r.run_id) ?? null),
  }))
  const param_keys = compareParamRows(runs.map((r) => ({ params: r.parameters }))).map((row) => row.key)
  return { ...payload, runs, param_keys }
}

/** True when there is at least one param or metric row to export. */
export function compareHasRows(payload: { param_keys?: string[]; metric_keys?: string[] } | null): boolean {
  return Boolean(payload && ((payload.param_keys?.length ?? 0) > 0 || (payload.metric_keys?.length ?? 0) > 0))
}
