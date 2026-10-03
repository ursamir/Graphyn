/**
 * Template catalog helpers (pure): "runnable here" and guided multi-step groups.
 *
 * `GET /pipelines/templates` rows (UX API draft §11) gain
 * `runnable: bool`, `missing_node_types: []`, `group`, `phase`, `step_title`.
 * Older APIs omit them — `runnable` then falls back to the client-side
 * missing-node computation, and templates without `group` stay single cards.
 */

export type GroupableTemplate = {
  name: string
  title?: string
  runnable?: boolean | null
  missing_node_types?: string[] | null
  group?: string | null
  phase?: string | number | null
  step_title?: string | null
}

/** Backend `missing_node_types` when present, else the client computation. */
export function templateMissing<T extends GroupableTemplate>(tpl: T, fallback: (t: T) => string[]): string[] {
  if (Array.isArray(tpl.missing_node_types)) return tpl.missing_node_types.map(String)
  return fallback(tpl)
}

/** Backend `runnable` when it is a boolean, else "no missing node types". */
export function isTemplateRunnable(tpl: GroupableTemplate, missing: readonly string[]): boolean {
  if (typeof tpl.runnable === 'boolean') return tpl.runnable
  return missing.length === 0
}

const PHASE_ORDER = ['prepare', 'data', 'dataset', 'ingest', 'collect', 'train', 'evaluate', 'eval', 'export', 'deploy', 'ship']

/** Sort key for a step: numeric phase / "step-2" / known words, else name. */
export function phaseRank(phase: GroupableTemplate['phase']): number {
  if (typeof phase === 'number' && Number.isFinite(phase)) return phase
  const p = String(phase ?? '').trim().toLowerCase()
  if (!p) return 1000
  const num = /(\d+)/.exec(p)
  if (num) return Number(num[1])
  const idx = PHASE_ORDER.findIndex((w) => p.includes(w))
  return idx >= 0 ? 100 + idx : 500
}

export type TemplateStep<T> = { tpl: T; step: number; title: string }
export type TemplateEntry<T> =
  | { kind: 'single'; tpl: T }
  | { kind: 'group'; group: string; title: string; steps: TemplateStep<T>[] }

/** "speech-commands-e2e" → "Speech commands E2E". */
export function groupTitle(group: string): string {
  const words = group
    .replace(/^ex-\d+-/, '')
    .split(/[-_\s]+/)
    .filter(Boolean)
  return words
    .map((w, i) => {
      const lower = w.toLowerCase()
      if (['e2e', 'asr', 'tts', 'llm', 'ml', 'kws'].includes(lower)) return lower.toUpperCase()
      return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower
    })
    .join(' ')
}

/**
 * Collapse templates sharing `group` into one guided entry (steps ordered by
 * `phase`), keeping the list's order (a group sits where its first member was).
 * A "group" with a single member stays a single entry.
 */
export function groupTemplates<T extends GroupableTemplate>(list: readonly T[]): TemplateEntry<T>[] {
  const byGroup = new Map<string, T[]>()
  for (const t of list) {
    const g = typeof t.group === 'string' ? t.group.trim() : ''
    if (!g) continue
    const arr = byGroup.get(g) ?? []
    arr.push(t)
    byGroup.set(g, arr)
  }
  const out: TemplateEntry<T>[] = []
  const emitted = new Set<string>()
  for (const t of list) {
    const g = typeof t.group === 'string' ? t.group.trim() : ''
    const members = g ? byGroup.get(g) ?? [] : []
    if (!g || members.length < 2) {
      out.push({ kind: 'single', tpl: t })
      continue
    }
    if (emitted.has(g)) continue
    emitted.add(g)
    const sorted = [...members].sort(
      (a, b) => phaseRank(a.phase) - phaseRank(b.phase) || a.name.localeCompare(b.name),
    )
    out.push({
      kind: 'group',
      group: g,
      title: groupTitle(g),
      steps: sorted.map((tpl, i) => ({
        tpl,
        step: i + 1,
        title: (tpl.step_title && tpl.step_title.trim()) || tpl.title || tpl.name,
      })),
    })
  }
  return out
}

/** Locate a template inside grouped entries → its group + step (null when single). */
export function findStep<T extends GroupableTemplate>(
  entries: readonly TemplateEntry<T>[],
  name: string,
): { entry: Extract<TemplateEntry<T>, { kind: 'group' }>; step: TemplateStep<T> } | null {
  for (const e of entries) {
    if (e.kind !== 'group') continue
    const step = e.steps.find((s) => s.tpl.name === name)
    if (step) return { entry: e, step }
  }
  return null
}
