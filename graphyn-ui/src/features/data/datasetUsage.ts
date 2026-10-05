/**
 * Datasets page: which shared input labels a workspace actually uses (pure).
 *
 * Sources: labels pinned on Home (`GET /projects/{id}/links` → `inputs`) and
 * the dataset each run read (`GET /runs` row `summary.dataset.source_path` /
 * `resolved_path`, e.g. `workspace/datasets/input/speech-commands`). A label
 * counts as used by a run when it is a whole path segment of either path.
 */

type Rec = Record<string, unknown>

function rec(v: unknown): Rec | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null
}

/** Dataset paths a run row recorded (source + resolved), '' entries dropped. */
export function runDatasetPaths(run: unknown): string[] {
  const r = rec(run)
  const summary = rec(r?.summary) ?? rec(rec(r?.meta)?.summary)
  const ds = rec(summary?.dataset)
  const out: string[] = []
  for (const k of ['source_path', 'resolved_path']) {
    const v = ds?.[k]
    if (typeof v === 'string' && v.trim()) out.push(v.trim())
  }
  return out
}

/**
 * Labels (from `labels`) used by this workspace, in `labels` order: pinned
 * ones plus any matched by a run's dataset path segment.
 */
export function usedInputLabels(
  labels: readonly string[],
  runs: readonly unknown[],
  pinned: readonly string[] = [],
): string[] {
  const segs = new Set<string>()
  for (const run of runs) {
    for (const p of runDatasetPaths(run)) {
      for (const seg of p.split(/[\\/]+/)) if (seg) segs.add(seg)
    }
  }
  const pin = new Set(pinned)
  return labels.filter((l) => pin.has(l) || segs.has(l))
}

/**
 * The used label to open by default: the one the most runs read (a whole-
 * dataset folder such as `speech-commands` beats per-class folders read by a
 * few preprocess runs). Ties keep `labels` order; null when none is used.
 */
export function mostUsedInputLabel(labels: readonly string[], runs: readonly unknown[]): string | null {
  let best: string | null = null
  let bestCount = 0
  for (const label of labels) {
    let count = 0
    for (const run of runs) {
      if (runDatasetPaths(run).some((p) => p.split(/[\\/]+/).includes(label))) count += 1
    }
    if (count > bestCount) {
      best = label
      bestCount = count
    }
  }
  return best
}
