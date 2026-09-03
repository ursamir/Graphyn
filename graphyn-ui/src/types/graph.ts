export interface GraphNode {
  id: string
  node_type: string
  config: Record<string, unknown>
  label?: string | null
  capability_metadata?: unknown
  event_trigger?: unknown
}

export interface GraphEdge {
  src_id: string
  src_port: string
  dst_id: string
  dst_port: string
  condition?: string | null
}

export interface GraphIR {
  schema_version: string
  metadata: {
    name: string
    seed: number
    description: string
    created_at: string | null
    tags: string[]
  }
  nodes: GraphNode[]
  edges: GraphEdge[]
  parameters: Record<string, unknown>
  /** Console layout sidecar — never put this under ``parameters``. */
  ui?: {
    positions?: Record<string, { x: number; y: number }>
  } | null
}

export interface PortDef {
  name: string
  data_type?: string
}

export interface NodeCatalogEntry {
  node_type: string
  label?: string
  description?: string
  category?: string
  config_schema?: {
    properties?: Record<string, Record<string, unknown>>
    required?: string[]
  }
  input_ports?: PortDef[]
  output_ports?: PortDef[]
  port_schema?: {
    inputs?: PortDef[]
    outputs?: PortDef[]
  }
  runtime?: string
}

export function emptyGraph(name = 'pipeline', seed = 42): GraphIR {
  return {
    schema_version: '1.1',
    metadata: {
      name,
      seed,
      description: 'Outputs belong in workspace/artifacts/<name>/ (bind-mounted).',
      created_at: null,
      tags: ['workspace-artifacts'],
    },
    nodes: [],
    edges: [],
    parameters: {},
  }
}

export function buildGraphFromCanvas(
  nodes: Array<{
    id: string
    position?: { x: number; y: number }
    data: { nodeType: string; config: Record<string, unknown> }
  }>,
  edges: Array<{
    source: string
    target: string
    sourceHandle?: string | null
    targetHandle?: string | null
  }>,
  seed: number,
  name = 'pipeline',
): GraphIR {
  const positions: Record<string, { x: number; y: number }> = {}
  for (const n of nodes) {
    if (n.position) positions[n.id] = n.position
  }
  return {
    schema_version: '1.1',
    metadata: {
      name,
      seed,
      description: 'Outputs belong in workspace/artifacts/<name>/ (bind-mounted).',
      created_at: null,
      tags: ['workspace-artifacts'],
    },
    nodes: nodes.map((n) => ({
      id: n.id,
      node_type: n.data.nodeType,
      config: n.data.config ?? {},
      label: null,
      capability_metadata: null,
      event_trigger: null,
    })),
    edges: edges.map((e) => ({
      src_id: e.source,
      src_port: canonicalPort(e.sourceHandle, 'output'),
      dst_id: e.target,
      dst_port: canonicalPort(e.targetHandle, 'input'),
      condition: null,
    })),
    parameters: {},
    ui: { positions },
  }
}

export function canonicalPort(handle: string | null | undefined, fallback: string): string {
  const raw = (handle || fallback).trim() || fallback
  return raw.split('::')[0] || fallback
}

export function catalogPorts(entry?: NodeCatalogEntry): { inputs: PortDef[]; outputs: PortDef[] } {
  const inputs =
    entry?.input_ports ??
    entry?.port_schema?.inputs ??
    [{ name: 'input' }]
  const outputs =
    entry?.output_ports ??
    entry?.port_schema?.outputs ??
    [{ name: 'output' }]
  return { inputs, outputs }
}
