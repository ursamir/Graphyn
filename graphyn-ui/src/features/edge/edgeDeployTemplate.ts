import type { GraphIR } from '../../types/graph'

/** Bundled Edge deploy starter (mirrors examples/templates/edge-deploy.graph.json). */
export const EDGE_DEPLOY_TEMPLATE: GraphIR = {
  schema_version: '1.1',
  metadata: {
    name: 'edge-deploy',
    seed: 42,
    description:
      'Edge deploy path: model path → edge_optimizer → deployment_packager. Point model_ref at a Keras SavedModel/.keras from trainer (workspace/artifacts/...). Outputs under workspace/artifacts/edge-deploy/.',
    created_at: null,
    tags: ['example', 'starter', 'edge', 'deploy', 'ml'],
  },
  nodes: [
    {
      id: 'model_ref',
      node_type: 'python_code',
      config: {
        source:
          'output = {\n  "model_path": "workspace/artifacts/models/saved_model",\n  "labels": ["yes", "no", "up", "down", "go", "stop"],\n  "history": {},\n  "metrics": {}\n}\n',
        allowed_paths: [],
        allow_network: false,
      },
      label: 'Model path',
      capability_metadata: null,
      event_trigger: null,
    },
    {
      id: 'edge_optimizer_0',
      node_type: 'edge_optimizer',
      config: {
        backend: 'tflite',
        quantization: 'float32',
        output_path: 'workspace/artifacts/edge-deploy/optimized',
        representative_samples: 100,
        prune: false,
        operator_fusion: true,
      },
      label: 'Edge Optimizer',
      capability_metadata: null,
      event_trigger: null,
    },
    {
      id: 'deployment_packager_0',
      node_type: 'deployment_packager',
      config: {
        target: 'edge',
        output_path: 'workspace/artifacts/edge-deploy/packages',
        include_inference_script: true,
        include_metadata: true,
        package_name: 'edge_model',
      },
      label: 'Deployment Packager',
      capability_metadata: null,
      event_trigger: null,
    },
  ],
  edges: [
    {
      src_id: 'model_ref',
      src_port: 'output',
      dst_id: 'edge_optimizer_0',
      dst_port: 'input',
      condition: null,
    },
    {
      src_id: 'edge_optimizer_0',
      src_port: 'output',
      dst_id: 'deployment_packager_0',
      dst_port: 'input',
      condition: null,
    },
  ],
  parameters: {},
  ui: {
    positions: {
      model_ref: { x: 80, y: 160 },
      edge_optimizer_0: { x: 360, y: 160 },
      deployment_packager_0: { x: 640, y: 160 },
    },
  },
}

export const EDGE_TARGETS = ['mobile', 'mcu', 'docker', 'edge'] as const
export const EDGE_BACKENDS = ['tflite', 'onnx', 'auto'] as const
export const EDGE_QUANTIZATIONS = ['float32', 'float16', 'int8'] as const

export type EdgeTarget = (typeof EDGE_TARGETS)[number]
export type EdgeBackend = (typeof EDGE_BACKENDS)[number]
export type EdgeQuantization = (typeof EDGE_QUANTIZATIONS)[number]

export function buildModelRefSource(modelPath: string, labelsCsv: string): string {
  const labels = labelsCsv
    .split(/[,;\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
  const labelsLit = JSON.stringify(labels.length ? labels : ['class0'])
  const pathLit = JSON.stringify(modelPath.trim() || 'workspace/artifacts/models/saved_model')
  return `output = {\n  "model_path": ${pathLit},\n  "labels": ${labelsLit},\n  "history": {},\n  "metrics": {}\n}\n`
}

export function applyEdgeConfig(
  base: GraphIR,
  opts: {
    modelPath: string
    labelsCsv: string
    backend: EdgeBackend
    quantization: EdgeQuantization
    target: EdgeTarget
    packageName: string
  },
): GraphIR {
  const graph: GraphIR = structuredClone(base)
  for (const node of graph.nodes) {
    if (node.id === 'model_ref' && node.node_type === 'python_code') {
      node.config = {
        ...node.config,
        source: buildModelRefSource(opts.modelPath, opts.labelsCsv),
      }
    }
    if (node.id === 'edge_optimizer_0' && node.node_type === 'edge_optimizer') {
      node.config = {
        ...node.config,
        backend: opts.backend,
        quantization: opts.quantization,
        output_path: 'workspace/artifacts/edge-deploy/optimized',
      }
    }
    if (node.id === 'deployment_packager_0' && node.node_type === 'deployment_packager') {
      node.config = {
        ...node.config,
        target: opts.target,
        package_name: opts.packageName.trim() || 'edge_model',
        output_path: 'workspace/artifacts/edge-deploy/packages',
      }
    }
  }
  return graph
}

/**
 * Registry stages / promote aliases often point at a run root or
 * `…/staging|latest|prod`. Prefer canonical run paths over blind append.
 * Kept for label hints; prefer `resolveModelPathCandidates` + probe for real picks.
 */
export function preferSavedModelPath(path: string): string {
  const p = path.trim().replace(/\/$/, '')
  if (!p) return p
  if (isLikelyModelPath(p)) return p
  if (/(?:^|\/)(staging|latest|prod|production)$/i.test(p)) return `${p}/saved_model`
  if (/\/runs\/[a-f0-9]+$/i.test(p)) return `${p}/saved_model`
  return p
}

export function isLikelyModelPath(path: string): boolean {
  const p = path.trim().replace(/\/$/, '')
  if (!p) return false
  if (/\.(keras|h5|tflite|onnx)$/i.test(p)) return true
  if (/(?:^|\/)saved_model$/i.test(p)) return true
  if (/saved_model\.pb$/i.test(p)) return true
  return false
}

/** True when a path is already a model file/dir (not a parent that needs /saved_model). */
export function isConcreteModelPath(path: string): boolean {
  const p = path.trim().replace(/\/$/, '')
  if (!p) return false
  if (/\.(keras|h5|tflite|onnx)$/i.test(p)) return true
  if (/(?:^|\/)saved_model$/i.test(p)) return true
  return false
}

export function isModelLikeArtifact(a: {
  artifact_type?: string
  uri?: string
  path?: string
  metadata?: Record<string, unknown>
}): boolean {
  const typ = String(a.artifact_type || '').toLowerCase()
  const uri = String(
    a.uri ||
      a.path ||
      (typeof a.metadata?.path === 'string' ? a.metadata.path : '') ||
      '',
  ).toLowerCase()
  if (/model|saved_model|keras|tflite|onnx/.test(typ)) return true
  if (/\.(keras|h5|tflite|onnx)$/.test(uri)) return true
  if (/\/saved_model(\/|$)/.test(uri) || /saved_model\.pb$/.test(uri)) return true
  if (/model\.keras$/.test(uri)) return true
  // Exclude common non-models
  if (/\.(png|jpg|jpeg|webp|gif|json|jsonl|csv|txt|md)$/.test(uri)) return false
  if (/metrics|confusion|roc|training_curves|checkpoint/.test(uri)) return false
  return false
}

export type ModelPathResolveInput = {
  slug?: string | null
  runId?: string | null
  stage?: string | null
  /** Registry stage.path or alias root (e.g. workspace/artifacts/speech-commands/staging). */
  stagePath?: string | null
  /** Explicit artifact URI if user picked one. */
  artifactUri?: string | null
}

/** Ordered candidates for Edge Optimizer (canonical run dir first). */
export function resolveModelPathCandidates(input: ModelPathResolveInput): string[] {
  const out: string[] = []
  const push = (p?: string | null) => {
    const v = (p || '').trim().replace(/\/$/, '')
    if (!v || out.includes(v)) return
    out.push(v)
  }

  const slug = (input.slug || '').trim().replace(/^workspace\/artifacts\//, '').split('/')[0]
  const runId = (input.runId || '').trim()
  const stage = (input.stage || '').trim().toLowerCase() || 'staging'
  const stagePath = (input.stagePath || '').trim().replace(/\/$/, '')
  const artifactUri = (input.artifactUri || '').trim().replace(/\/$/, '')

  if (slug && runId) {
    push(`workspace/artifacts/${slug}/runs/${runId}/saved_model`)
    push(`workspace/artifacts/${slug}/runs/${runId}/model.keras`)
  }
  if (slug && stage) {
    push(`workspace/artifacts/${slug}/${stage}/saved_model`)
    push(`workspace/artifacts/${slug}/${stage}/model.keras`)
  }
  if (stagePath) {
    if (isConcreteModelPath(stagePath)) {
      push(stagePath)
    } else {
      push(`${stagePath}/saved_model`)
      push(`${stagePath}/model.keras`)
      // If stagePath is alias root, also try extracting slug/run from runs/…
      const m = stagePath.match(/workspace\/artifacts\/([^/]+)\/runs\/([a-f0-9]+)/i)
      if (m) {
        push(`workspace/artifacts/${m[1]}/runs/${m[2]}/saved_model`)
        push(`workspace/artifacts/${m[1]}/runs/${m[2]}/model.keras`)
      }
    }
  }
  if (artifactUri) {
    if (isConcreteModelPath(artifactUri)) {
      push(artifactUri)
    } else if (/\/saved_model\.pb$/i.test(artifactUri)) {
      push(artifactUri.replace(/\/saved_model\.pb$/i, ''))
    } else if (!/\.(png|jpg|jpeg|json|jsonl|csv|txt|md|webp|gif)$/i.test(artifactUri)) {
      // Directory-ish URI: try sibling saved_model / model.keras
      push(`${artifactUri}/saved_model`)
      push(`${artifactUri}/model.keras`)
      push(artifactUri)
    }
  }
  return out
}

/**
 * Probe via GET /outputs/file: 200 = file present, 400+"directory" = dir present, 404 = miss.
 */
export async function probePathExists(
  path: string,
  fetchFn: (path: string) => Promise<Response>,
): Promise<boolean> {
  const p = path.trim()
  if (!p) return false
  try {
    const res = await fetchFn(p)
    if (res.status === 200) return true
    if (res.status === 404) return false
    if (res.status === 400) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string }
      return /directory/i.test(String(body.detail || ''))
    }
    // 415 etc. — path existed but type blocked; still "present" for model dirs/files we care about
    if (res.status === 415) return true
    return false
  } catch {
    return false
  }
}

/** First candidate that exists on disk, or first candidate if none probe true. */
export async function pickExistingModelPath(
  candidates: string[],
  fetchFn: (path: string) => Promise<Response>,
): Promise<{ path: string; verified: boolean }> {
  const list = candidates.filter(Boolean)
  if (list.length === 0) return { path: '', verified: false }
  for (const c of list) {
    if (await probePathExists(c, fetchFn)) return { path: c, verified: true }
  }
  return { path: list[0], verified: false }
}

/**
 * Guess package file path. Prefer the run's `artifacts_dir` when known; else
 * the edge-deploy `latest` symlink (packages land under run-scoped dirs).
 */
export function guessPackagePath(
  target: EdgeTarget,
  packageName: string,
  artifactsDir?: string | null,
): string {
  const base = packageName.trim() || 'edge_model'
  const dir = artifactsDir
    ? `${artifactsDir.replace(/\/$/, '')}/packages`
    : 'workspace/artifacts/edge-deploy/latest/packages'
  if (target === 'mobile') return `${dir}/${base}.zip`
  if (target === 'mcu') return `${dir}/${base}.h`
  if (target === 'docker') return `${dir}/${base}_docker.tar.gz`
  return `${dir}/${base}_edge.tar.gz`
}
