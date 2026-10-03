/**
 * Editor canvas: recognise parallel branches (a fork into Path A / Path B …)
 * so copies of the same step read "Trainer · Path B" with a coloured path
 * badge instead of an opaque "#c3f15543" id suffix. Pure — unit-tested.
 */
import { computePipelineShape, disambiguateByPath, isMultiTrackShape, topoOrderGraph } from '../runs/runNodes'
import { describeBranch } from '../runs/runResults'

export type CanvasNodeLike = {
  id: string
  data: { nodeType: string; label?: string; config?: Record<string, unknown> }
}
export type CanvasEdgeLike = { source: string; target: string }

export type CanvasPathInfo = {
  /** "A", "B", … */
  letter: string
  /** "DS-CNN · 50 epochs" ('' when unknown). */
  description: string
}

export type CanvasPathView = {
  /** node id → its branch (absent for shared / linear nodes). */
  pathOf: Map<string, CanvasPathInfo>
  /** node id → display label ("Trainer · Path B" for duplicated labels). */
  labelOf: Map<string, string>
}

export function canvasPathView(nodes: CanvasNodeLike[], edges: CanvasEdgeLike[]): CanvasPathView {
  const graph = {
    nodes: nodes.map((n) => ({ id: n.id, node_type: n.data.nodeType, config: n.data.config })),
    edges: edges.map((e) => ({ src_id: e.source, dst_id: e.target })),
  }
  const order = topoOrderGraph(graph)
  const shape = computePipelineShape(order, graph.edges)
  const pathOf = new Map<string, CanvasPathInfo>()
  if (isMultiTrackShape(shape)) {
    shape.branches.forEach((branch, i) => {
      const letter = String.fromCharCode(65 + Math.min(i, 25))
      const description = describeBranch(
        shape.kind === 'fork' ? [...branch, ...shape.sharedIds] : branch,
        graph.nodes,
      )
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
  return { pathOf, labelOf }
}
