/**
 * Editor canvas: recognise parallel branches (a fork into Path A / Path B …)
 * so copies of the same step read "Trainer · Path B" with a coloured path
 * badge instead of an opaque "#c3f15543" id suffix. Pure — unit-tested.
 */
import { computePipelineShape, disambiguateByPath, isMultiTrackShape, topoOrderGraph } from '../runs/runNodes'
import { describeBranch } from '../runs/runResults'
import { graphHasMlPaths } from '../runs/runFlow'
import { formatLr, learningRateLinks } from './learningRate'

export type CanvasNodeLike = {
  id: string
  data: { nodeType: string; label?: string; config?: Record<string, unknown> }
}
export type CanvasEdgeLike = { source: string; target: string }

export type CanvasPathInfo = {
  /** "A", "B", … */
  letter: string
  /** "DS-CNN · 50 epochs" (+ " · lr 0.001" when paths train at different effective LRs; '' when unknown). */
  description: string
}

export type CanvasPathView = {
  /** node id → its branch (absent for shared / linear nodes). */
  pathOf: Map<string, CanvasPathInfo>
  /** node id → display label ("Trainer · Path B" for duplicated labels). */
  labelOf: Map<string, string>
  /**
   * Workflow graphs: node id → {title: node id, subtitle: type label} when
   * several unlabeled nodes share a type ("approved" / "Set / Map").
   */
  titleOf: Map<string, { title: string; subtitle: string }>
}

export function canvasPathView(nodes: CanvasNodeLike[], edges: CanvasEdgeLike[]): CanvasPathView {
  const graph = {
    nodes: nodes.map((n) => ({ id: n.id, node_type: n.data.nodeType, config: n.data.config })),
    edges: edges.map((e) => ({ src_id: e.source, dst_id: e.target })),
  }
  const order = topoOrderGraph(graph)
  const shape = computePipelineShape(order, graph.edges)
  const pathOf = new Map<string, CanvasPathInfo>()
  const typeOf = new Map(nodes.map((n) => [n.id, n.data.nodeType]))
  // Path badges only for ML-style multi-path graphs (≥2 branches that train /
  // evaluate) — if_switch / approval / error branches are not "paths".
  const mlPaths = isMultiTrackShape(shape) && graphHasMlPaths(shape, (id) => typeOf.get(id))
  if (mlPaths) {
    // Effective LR per branch (a set Trainer value wins over the Model builder's).
    const lrs = learningRateLinks(nodes, edges)
    const branchLr = shape.branches.map((branch) => {
      for (const id of branch) {
        const info = lrs.get(id)
        if (info?.role === 'trainer' && info.effective != null) return info.effective
      }
      return null
    })
    const lrDiffers = new Set(branchLr.filter((v) => v != null)).size > 1
    shape.branches.forEach((branch, i) => {
      const letter = String.fromCharCode(65 + Math.min(i, 25))
      const base = describeBranch(
        shape.kind === 'fork' ? [...branch, ...shape.sharedIds] : branch,
        graph.nodes,
      )
      const lr = branchLr[i]
      const description = lrDiffers && lr != null ? [base, `lr ${formatLr(lr)}`].filter(Boolean).join(' · ') : base
      for (const id of branch) {
        if (!pathOf.has(id)) pathOf.set(id, { letter, description })
      }
    })
  }
  const items = nodes.map((n) => ({
    id: n.id,
    nodeType: n.data.nodeType,
    label: (n.data.label || n.data.nodeType).trim(),
  }))
  const labelled = disambiguateByPath(items, (id) => {
    const p = pathOf.get(id)
    return p ? `Path ${p.letter}` : null
  })
  const labelOf = new Map(labelled.map((it) => [it.id, it.label]))
  const titleOf = new Map<string, { title: string; subtitle: string }>()
  if (!mlPaths) {
    // Same type + same label (no custom label) → the id tells them apart.
    const key = (it: (typeof items)[number]) => `${it.nodeType}\u0000${it.label.toLowerCase()}`
    const counts = new Map<string, number>()
    for (const it of items) counts.set(key(it), (counts.get(key(it)) ?? 0) + 1)
    for (const it of items) {
      if ((counts.get(key(it)) ?? 0) < 2) continue
      titleOf.set(it.id, { title: it.id, subtitle: it.label })
      labelOf.set(it.id, it.id)
    }
  }
  return { pathOf, labelOf, titleOf }
}
