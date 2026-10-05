/**
 * Effective learning rate for Model builder → Trainer pairs (pure — unit-tested
 * in learningRate.test.ts).
 *
 * Backend rule (PluginPackage/Common/trainer/nodes.py, read-only here):
 *   TrainerNode._keras_model_on_device clones the builder's model and always
 *   re-compiles it with Adam(lr): `trainer.learning_rate` when set, otherwise
 *   the builder's compiled optimizer LR (`_compiled_learning_rate`, which is
 *   `model_builder.learning_rate`). So a set Trainer value wins; an empty one
 *   keeps the Model builder's value. (ReduceLROnPlateau may lower it later.)
 */

export type LrNodeLike = {
  id: string
  data: { nodeType: string; label?: string; config?: Record<string, unknown> | null }
}
export type LrEdgeLike = { source: string; target: string }

export type LrInfo = {
  role: 'builder' | 'trainer'
  /** LR the trainer actually trains with; null when it can't be known. */
  effective: number | null
  /** Who decides `effective`. */
  source: 'trainer' | 'model_builder' | null
  builderLr: number | null
  trainerLr: number | null
  /** The paired node (upstream builder for a trainer, downstream trainer for a builder). */
  otherId: string | null
  otherLabel: string
}

/** Keras Adam default the builder compiles with when its field is empty. */
export const DEFAULT_BUILDER_LR = 0.001

function bareType(t: string): string {
  return String(t || '').replace(/^Isolated_/, '').toLowerCase()
}

export function isModelBuilderType(t: string): boolean {
  return bareType(t) === 'model_builder'
}

export function isTrainerType(t: string): boolean {
  return bareType(t) === 'trainer'
}

export function lrValue(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v) && v > 0) return v
  if (typeof v === 'string' && v.trim() && Number.isFinite(Number(v)) && Number(v) > 0) return Number(v)
  return null
}

function label(n: LrNodeLike | undefined): string {
  if (!n) return ''
  return (n.data.label || n.data.nodeType || n.id).trim()
}

/** Nearest nodes (BFS) matching `match`, walking `next`. */
function nearest(start: string, next: Map<string, string[]>, match: (id: string) => boolean): string[] {
  const seen = new Set([start])
  let frontier = [start]
  while (frontier.length) {
    const found: string[] = []
    const upcoming: string[] = []
    for (const id of frontier) {
      for (const n of next.get(id) ?? []) {
        if (seen.has(n)) continue
        seen.add(n)
        if (match(n)) found.push(n)
        else upcoming.push(n)
      }
    }
    if (found.length) return found
    frontier = upcoming
  }
  return []
}

/** node id → learning-rate pairing for every Model builder / Trainer that has a partner. */
export function learningRateLinks(nodes: LrNodeLike[], edges: LrEdgeLike[]): Map<string, LrInfo> {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const down = new Map<string, string[]>()
  const up = new Map<string, string[]>()
  for (const e of edges) {
    down.set(e.source, [...(down.get(e.source) ?? []), e.target])
    up.set(e.target, [...(up.get(e.target) ?? []), e.source])
  }
  const isBuilder = (id: string) => isModelBuilderType(byId.get(id)?.data.nodeType ?? '')
  const isTrainer = (id: string) => isTrainerType(byId.get(id)?.data.nodeType ?? '')
  const cfgLr = (id: string | null) => (id ? lrValue(byId.get(id)?.data.config?.learning_rate) : null)

  const out = new Map<string, LrInfo>()
  const trainerInfo = (trainerId: string): LrInfo | null => {
    const builderId = nearest(trainerId, up, isBuilder)[0] ?? null
    if (!builderId) return null
    const trainerLr = cfgLr(trainerId)
    const builderLr = cfgLr(builderId)
    const effective = trainerLr ?? builderLr ?? DEFAULT_BUILDER_LR
    return {
      role: 'trainer',
      effective,
      source: trainerLr != null ? 'trainer' : 'model_builder',
      builderLr,
      trainerLr,
      otherId: builderId,
      otherLabel: label(byId.get(builderId)),
    }
  }
  for (const n of nodes) {
    if (isTrainer(n.id)) {
      const info = trainerInfo(n.id)
      if (info) out.set(n.id, info)
    }
  }
  for (const n of nodes) {
    if (!isBuilder(n.id)) continue
    const trainers = nearest(n.id, down, isTrainer).filter((t) => out.get(t)?.otherId === n.id)
    if (trainers.length === 0) continue
    const infos = trainers.map((t) => out.get(t)!)
    const values = new Set(infos.map((i) => i.effective))
    const single = values.size === 1 ? infos[0] : null
    out.set(n.id, {
      role: 'builder',
      effective: single ? single.effective : null,
      source: single ? single.source : null,
      builderLr: cfgLr(n.id),
      trainerLr: single ? single.trainerLr : null,
      otherId: trainers[0],
      otherLabel: trainers.length === 1 ? label(byId.get(trainers[0])) : `${trainers.length} trainers`,
    })
  }
  return out
}

/** "0.002", "1e-4". */
export function formatLr(n: number): string {
  if (n !== 0 && Math.abs(n) < 0.001) {
    const [m, e] = n.toExponential().split('e')
    return `${Number(Number(m).toPrecision(3))}e${Number(e)}`
  }
  return String(Number(n.toPrecision(4)))
}

/** Inspector note under a `learning_rate` field saying which value training uses. */
export function learningRateNote(info: LrInfo | undefined | null): string | null {
  if (!info) return null
  const other = info.otherLabel || (info.role === 'trainer' ? 'Model builder' : 'Trainer')
  if (info.role === 'trainer') {
    const b = info.builderLr ?? DEFAULT_BUILDER_LR
    if (info.trainerLr != null) {
      return info.trainerLr === b
        ? `Same as ${other} (${formatLr(b)}). Training uses ${formatLr(info.trainerLr)}.`
        : `Wins over ${other}'s ${formatLr(b)} — training uses ${formatLr(info.trainerLr)}.`
    }
    return `Empty — training uses ${other}'s ${formatLr(b)}.`
  }
  if (info.effective == null) return `Downstream ${other} set different learning rates; each trainer's own value wins when set.`
  if (info.source === 'trainer') {
    const own = info.builderLr ?? DEFAULT_BUILDER_LR
    return own === info.effective
      ? `${other} sets the same value (${formatLr(info.effective)}); the trainer's value wins.`
      : `Not used for training — ${other} sets ${formatLr(info.effective)}, which wins.`
  }
  return `Used for training (${other} leaves its learning rate empty).`
}
