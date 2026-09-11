import type { GraphIR } from '../types/graph'

/**
 * Nodes whose Config declares project / output_dir / version_tag.
 * Do NOT include dataset_builder (in-memory splits only — no project/output_dir).
 * Never stamp because `'project' in cfg` alone — that poisons trainer/model_builder.
 */
const PROJECT_STAMP_NODES = new Set([
  'dataset_versioner',
  'audio_exporter',
  'export',
])

/** Stamp project (+ optional version_tag) onto exporter/versioner nodes and metadata. */
export function stampProjectOnGraph(graph: GraphIR, project: string, version?: string): GraphIR {
  const nodes = (graph.nodes ?? []).map((n) => {
    const cfg = { ...(n.config ?? {}) } as Record<string, unknown>
    let changed = false
    if (PROJECT_STAMP_NODES.has(n.node_type)) {
      if (cfg.project !== project) {
        cfg.project = project
        changed = true
      }
      const next = `workspace/datasets/output/${project}`
      if (cfg.output_dir !== next) {
        cfg.output_dir = next
        changed = true
      }
      if (version) {
        if (cfg.version_tag === undefined || cfg.version_tag === null || cfg.version_tag === '') {
          cfg.version_tag = version
          changed = true
        }
      }
    } else if (
      typeof cfg.output_dir === 'string' &&
      cfg.output_dir.includes('workspace/artifacts/')
    ) {
      // Rewrite artifact sink paths for project isolation without injecting `project`
      // (caption_export / experiment_tracker declare output_dir but not project).
      const next = `workspace/artifacts/${project}/${n.node_type}`
      if (cfg.output_dir !== next) {
        cfg.output_dir = next
        changed = true
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
