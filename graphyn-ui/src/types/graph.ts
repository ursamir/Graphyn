export type NodePlacement = {
  mode?: 'auto' | 'local' | 'worker' | 'pool'
  worker?: string | null
  pool?: string | null
  tags?: string[]
  require_gpu?: boolean
  min_vram_mib?: number | null
}

export interface GraphNode {
  id: string
  node_type: string
  config: Record<string, unknown>
  label?: string | null
  capability_metadata?: unknown
  event_trigger?: unknown
  /** IR 1.2+ distributed placement hint (Mode B). */
  placement?: NodePlacement | null
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
    project?: string | null
    version_tag?: string | null
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
  input_ports?: PortDef[] | Record<string, Record<string, unknown>>
  output_ports?: PortDef[] | Record<string, Record<string, unknown>>
  port_schema?: {
    inputs?: PortDef[] | Record<string, Record<string, unknown>>
    outputs?: PortDef[] | Record<string, Record<string, unknown>>
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
    data: {
      nodeType: string
      config: Record<string, unknown>
      placement?: NodePlacement | null
    }
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
  const hasPlacement = nodes.some((n) => {
    const p = n.data.placement
    if (!p) return false
    if (p.mode && p.mode !== 'auto') return true
    if (p.require_gpu) return true
    if (p.worker || p.pool) return true
    if (Array.isArray(p.tags) && p.tags.length > 0) return true
    if (p.min_vram_mib != null) return true
    return false
  })
  return {
    schema_version: hasPlacement ? '1.2' : '1.1',
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
      placement: n.data.placement ?? null,
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

function normalizePorts(raw: unknown, fallback: string): PortDef[] {
  if (Array.isArray(raw)) {
    return raw
      .map((p) => {
        if (typeof p === 'string') return { name: p }
        if (p && typeof p === 'object' && 'name' in p) {
          const rec = p as Record<string, unknown>
          return { name: String(rec.name), data_type: rec.data_type ? String(rec.data_type) : undefined }
        }
        return null
      })
      .filter((p): p is PortDef => !!p && !!p.name)
  }
  if (raw && typeof raw === 'object') {
    return Object.entries(raw as Record<string, unknown>).map(([name, spec]) => {
      const rec = spec && typeof spec === 'object' ? (spec as Record<string, unknown>) : {}
      const dt = rec.data_type ?? rec.type
      return { name, data_type: dt != null ? String(dt) : undefined }
    })
  }
  return [{ name: fallback }]
}

export function catalogPorts(entry?: NodeCatalogEntry): { inputs: PortDef[]; outputs: PortDef[] } {
  const inputs = normalizePorts(entry?.input_ports ?? entry?.port_schema?.inputs, 'input')
  const outputs = normalizePorts(entry?.output_ports ?? entry?.port_schema?.outputs, 'output')
  return {
    inputs: inputs.length ? inputs : [{ name: 'input' }],
    outputs: outputs.length ? outputs : [{ name: 'output' }],
  }
}
