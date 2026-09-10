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
      if (cfg.project !== project) {
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
  const meta = {
    ...(graph.metadata ?? {}),
    name: graph.metadata?.name || project,
    project,
    ...(version ? { version_tag: version } : {}),
  }
  return { ...graph, nodes, metadata: meta }
}

/** Phase-2 match: prefer exact meta.project / run.project; soft fallback for legacy runs. */
export function runMatchesProject(
  run: { graph_name?: unknown; project?: unknown; meta?: unknown; [k: string]: unknown },
  project: string,
): boolean {
  const p = project.trim()
  if (!p) return true
  const direct = String(run.project ?? '').trim()
  if (direct && direct === p) return true
  const meta = run.meta && typeof run.meta === 'object' ? (run.meta as Record<string, unknown>) : null
  if (meta) {
    const mp = String(meta.project ?? '').trim()
    if (mp && mp === p) return true
  }
  // Soft legacy fallback (pre-Phase-2 journals without project stamp)
  const pl = p.toLowerCase()
  const graphName = String(run.graph_name ?? '').toLowerCase()
  if (graphName && (graphName === pl || graphName.includes(pl))) return true
  if (direct && direct.toLowerCase().includes(pl)) return true
  if (meta) {
    const mg = String(meta.graph_name ?? '').toLowerCase()
    if (mg && (mg === pl || mg.includes(pl))) return true
  }
  return false
}
