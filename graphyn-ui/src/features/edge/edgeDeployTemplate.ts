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

/** Guess package file path from packager config (matches plugin defaults). */
export function guessPackagePath(target: EdgeTarget, packageName: string): string {
  const base = packageName.trim() || 'edge_model'
  const dir = 'workspace/artifacts/edge-deploy/packages'
  if (target === 'mobile') return `${dir}/${base}.zip`
  if (target === 'mcu') return `${dir}/${base}.h`
  if (target === 'docker') return `${dir}/${base}_docker.tar.gz`
  return `${dir}/${base}_edge.tar.gz`
}
