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

const INGEST_PATH_KEYS = new Set([
  'path',
  'dataset_path',
  'input_path',
  'source_path',
  'manifest_path',
  'dataset',
])

function normPath(raw: unknown): string {
  return typeof raw === 'string' ? raw.trim().replace(/\\/g, '/').replace(/\/+$/, '') : ''
}

/**
 * True when an exporter's `output_dir` may be moved into the project's
 * Library folder: unset, the plugin default, or already a Library export
 * (`workspace/datasets/output/...`).
 */
export function isRetargetableExportDir(raw: unknown): boolean {
  const p = normPath(raw)
  if (!p) return true
  if (p === GENERIC_EXPORT_OUTPUT_DIR) return true
  return p.startsWith(DATASETS_OUTPUT_PREFIX)
}

/** Stable dataset hand-off trees (`workspace/artifacts/<slug>/dataset/...`). */
export function isArtifactDatasetPath(raw: unknown): boolean {
  return /(^|\/)workspace\/artifacts\/[^/]+\/dataset(\/|$)/.test(normPath(raw))
}

/**
 * Ingest paths that should follow the active workspace Library Outputs folder:
 * the Library export default always; legacy `artifacts/<slug>/dataset/...`
 * hand-offs only when `legacyIngest` (opening an old template) — a path the
 * user picked explicitly is never silently swapped at run time.
 */
export function shouldRewritePreparedIngestPath(raw: unknown, opts: { legacyIngest?: boolean } = {}): boolean {
  const p = normPath(raw)
  if (!p) return false
  if (isArtifactDatasetPath(p)) return opts.legacyIngest === true
  if (p === GENERIC_EXPORT_OUTPUT_DIR || p.startsWith(`${GENERIC_EXPORT_OUTPUT_DIR}/`)) return true
  return false
}

/** Map a prepared-dataset ingest path onto `datasets/output/<project>/(latest|vN)`. */
export function rewritePreparedIngestPath(
  raw: unknown,
  project: string,
  opts: { legacyIngest?: boolean } = {},
): string | null {
  const p = normPath(raw)
  const proj = project.trim()
  if (!p || !proj || !shouldRewritePreparedIngestPath(p, opts)) return null
  const parts = p.split('/').filter(Boolean)
  const last = parts[parts.length - 1] || ''
  const suffix = last === 'latest' || /^v\d+(\.\d+)*$/.test(last) ? last : 'latest'
  return `${DATASETS_OUTPUT_PREFIX}${proj}/${suffix}`
}

/** Inspector note for an ingest path still pointing at a legacy artifact dataset tree. */
export function legacyIngestPathHint(fieldKey: string, raw: unknown): string | null {
  if (!INGEST_PATH_KEYS.has(fieldKey) || !isArtifactDatasetPath(raw)) return null
  return 'Legacy dataset folder (workspace/artifacts/…) — Run reads it as-is. Prefer a Datasets → Outputs version.'
}

/**
 * Inspector note for exporter `project` / `output_dir`: the editor shows the
 * unstamped graph, so a blank Project would otherwise hide where Run writes.
 */
export function exportDestinationHint(
  nodeType: string,
  fieldKey: string,
  cfg: Record<string, unknown>,
  project: string,
): string | null {
  if (!PROJECT_STAMP_NODES.has(nodeType)) return null
  if (fieldKey !== 'project' && fieldKey !== 'output_dir') return null
  const proj = project.trim()
  if (!isRetargetableExportDir(cfg.output_dir)) {
    if (fieldKey !== 'output_dir') return null
    return isArtifactDatasetPath(cfg.output_dir)
      ? 'Legacy dataset folder — runs show up in Datasets → Outputs only after Publish.'
      : 'Custom folder — Run writes here, outside Datasets → Outputs.'
  }
  if (!proj) return 'Open a workspace — Run then writes into Datasets → Outputs for it.'
  if (fieldKey === 'project') return cfg.project === proj ? null : `Run fills this with “${proj}”.`
  return `Run writes to ${DATASETS_OUTPUT_PREFIX}${proj}/ (next free vN).`
}

/**
 * Stamp project (+ optional version_tag) onto exporter/versioner nodes and metadata.
 *
 * Exporters get `project` / `output_dir = workspace/datasets/output/<ws>` when
 * retargetable. The Library-default ingest path rewrites to
 * `datasets/output/<ws>/latest|vN` so Step 1 → Step 2 hand-off stays in
 * Datasets → Outputs; legacy `artifacts/<slug>/dataset/...` ingest paths only
 * with `opts.legacyIngest` (template load), never at run time.
 */
export function stampProjectOnGraph(
  graph: GraphIR,
  project: string,
  version?: string,
  opts: { legacyIngest?: boolean } = {},
): GraphIR {
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
      // Rewrite artifact sink paths for project isolation without injecting `project`.
      // Use node id (not only node_type) so two trainers / evaluators never share a dir.
      const sink = n.id || n.node_type
      const next = `workspace/artifacts/${project}/${sink}`
      if (cfg.output_dir !== next) {
        cfg.output_dir = next
        changed = true
      }
    }
    if (project) {
      for (const key of INGEST_PATH_KEYS) {
        if (!(key in cfg)) continue
        const next = rewritePreparedIngestPath(cfg[key], project, opts)
        if (next && cfg[key] !== next) {
          cfg[key] = next
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
