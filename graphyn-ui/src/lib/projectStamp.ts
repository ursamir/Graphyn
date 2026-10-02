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

/** Exporter default `output_dir` (plugin Config default) — safe to retarget. */
export const GENERIC_EXPORT_OUTPUT_DIR = 'workspace/datasets/output/audio_export'
const DATASETS_OUTPUT_PREFIX = 'workspace/datasets/output/'

function normPath(raw: unknown): string {
  return typeof raw === 'string' ? raw.trim().replace(/\\/g, '/').replace(/\/+$/, '') : ''
}

/**
 * True when an exporter's `output_dir` may be moved into the project's
 * Library folder: unset, the plugin default, or already a Library export
 * (`workspace/datasets/output/...`). Explicit artifact paths
 * (`workspace/artifacts/<slug>/dataset/...`) are hand-off locations another
 * template of the same example ingests from — they are never rewritten.
 */
export function isRetargetableExportDir(raw: unknown): boolean {
  const p = normPath(raw)
  if (!p) return true
  if (p === GENERIC_EXPORT_OUTPUT_DIR) return true
  return p.startsWith(DATASETS_OUTPUT_PREFIX)
}

/** Stable dataset hand-off trees (`workspace/artifacts/<slug>/dataset/...`). */
function isArtifactDatasetPath(raw: unknown): boolean {
  return /(^|\/)workspace\/artifacts\/[^/]+\/dataset(\/|$)/.test(normPath(raw))
}

/**
 * Stamp project (+ optional version_tag) onto exporter/versioner nodes and metadata.
 *
 * Exporters only get `project` / `output_dir` when their output_dir is
 * retargetable (see {@link isRetargetableExportDir}) — the exporter ignores
 * output_dir once `project` is set, so stamping an explicit artifact path
 * would break the Phase-1 → Phase-2 hand-off. Run attribution still comes
 * from `metadata.project`. The backend (`graph_prepare`) never rewrites node
 * paths for a project either.
 */
export function stampProjectOnGraph(graph: GraphIR, project: string, version?: string): GraphIR {
  const nodes = (graph.nodes ?? []).map((n) => {
    const cfg = { ...(n.config ?? {}) } as Record<string, unknown>
    let changed = false
    if (PROJECT_STAMP_NODES.has(n.node_type)) {
      const retarget = !!project && isRetargetableExportDir(cfg.output_dir)
      if (retarget) {
        if (cfg.project !== project) {
          cfg.project = project
          changed = true
        }
        const next = `${DATASETS_OUTPUT_PREFIX}${project}`
        if (cfg.output_dir !== next) {
          cfg.output_dir = next
          changed = true
        }
      }
      if (version) {
        if (cfg.version_tag === undefined || cfg.version_tag === null || cfg.version_tag === '') {
          cfg.version_tag = version
          changed = true
        }
      }
    } else if (
      project &&
      typeof cfg.output_dir === 'string' &&
      cfg.output_dir.includes('workspace/artifacts/') &&
      !isArtifactDatasetPath(cfg.output_dir)
    ) {
      // Rewrite artifact sink paths for project isolation without injecting `project`
      // (caption_export / experiment_tracker declare output_dir but not project).
      // Dataset hand-off trees (<slug>/dataset/...) are left alone.
      // Use node id (not only node_type) so two trainers / evaluators never share a dir.
      const sink = n.id || n.node_type
      const next = `workspace/artifacts/${project}/${sink}`
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
  // Soft legacy fallback (pre-Phase-2 journals without project stamp):
  // exact graph_name == project only — never substring (avoids project "ml" ↔ "html_pipeline").
  const pl = p.toLowerCase()
  const graphName = String(run.graph_name ?? '').toLowerCase()
  if (graphName && graphName === pl) return true
  if (meta) {
    const mg = String(meta.graph_name ?? '').toLowerCase()
    if (mg && mg === pl) return true
  }
  return false
}
