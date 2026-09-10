import type { GraphIR } from '../types/graph'

const DATASET_NODES = new Set([
  'dataset_versioner',
  'dataset_builder',
  'audio_exporter',
  'export',
])

/** Stamp project (+ optional version_tag) onto dataset/export nodes and metadata.name. */
export function stampProjectOnGraph(graph: GraphIR, project: string, version?: string): GraphIR {
  const nodes = (graph.nodes ?? []).map((n) => {
    const cfg = { ...(n.config ?? {}) } as Record<string, unknown>
    let changed = false
    if (DATASET_NODES.has(n.node_type) || 'project' in cfg) {
      if (cfg.project === undefined || cfg.project === null || cfg.project === '') {
        cfg.project = project
        changed = true
      }
    }
    if (DATASET_NODES.has(n.node_type)) {
      const next = `workspace/datasets/output/${project}`
      if (cfg.output_dir !== next) {
        cfg.output_dir = next
        changed = true
      }
    } else if (typeof cfg.output_dir === 'string' && cfg.output_dir.includes('workspace/artifacts/')) {
      const next = `workspace/artifacts/${project}/${n.node_type}`
      if (cfg.output_dir !== next) {
        cfg.output_dir = next
        changed = true
      }
    }
    if (version) {
      if (DATASET_NODES.has(n.node_type) || 'version_tag' in cfg) {
        if (cfg.version_tag === undefined || cfg.version_tag === null || cfg.version_tag === '') {
          cfg.version_tag = version
          changed = true
        }
      }
    }
    return changed ? { ...n, config: cfg } : n
  })
  const meta = { ...(graph.metadata ?? {}), name: graph.metadata?.name || project }
  return { ...graph, nodes, metadata: meta }
}

/** Best-effort Phase-1 match: graph_name / project fields mention the active project. */
export function runMatchesProject(
  run: { graph_name?: unknown; project?: unknown; meta?: unknown; [k: string]: unknown },
  project: string,
): boolean {
  const p = project.trim().toLowerCase()
  if (!p) return true
  const graphName = String(run.graph_name ?? '').toLowerCase()
  if (graphName && (graphName === p || graphName.includes(p))) return true
  const direct = String(run.project ?? '').toLowerCase()
  if (direct && (direct === p || direct.includes(p))) return true
  const meta = run.meta && typeof run.meta === 'object' ? (run.meta as Record<string, unknown>) : null
  if (meta) {
    const mp = String(meta.project ?? '').toLowerCase()
    if (mp && (mp === p || mp.includes(p))) return true
    const mg = String(meta.graph_name ?? '').toLowerCase()
    if (mg && (mg === p || mg.includes(p))) return true
  }
  return false
}
