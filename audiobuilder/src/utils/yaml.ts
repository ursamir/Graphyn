// audiobuilder/src/utils/yaml.ts
import yaml from "js-yaml";

interface YamlNode {
  id: string;
  type: string;
  data: Record<string, unknown>;
  position: { x: number; y: number };
}

interface YamlEdge {
  id: string;
  source: string;
  target: string;
}

type NormalizedValue =
  | string
  | number
  | boolean
  | null
  | NormalizedValue[]
  | { [key: string]: NormalizedValue };

function normalize(value: unknown): NormalizedValue {
  if (value === undefined) {
    return null;
  }

  if (Array.isArray(value)) {
    return value.map(normalize);
  }

  if (value && typeof value === "object") {
    const out: { [key: string]: NormalizedValue } = {};
    const record = value as Record<string, unknown>;
    for (const k in record) {
      out[k] = normalize(record[k]);
    }
    return out;
  }

  // convert numeric strings → numbers
  if (typeof value === "string") {
    const trimmed = value.trim();

    // integer or float
    if (/^-?\d+(\.\d+)?$/.test(trimmed)) {
      return Number(trimmed);
    }

    // boolean strings
    if (trimmed === "true") return true;
    if (trimmed === "false") return false;
  }

  return value as NormalizedValue;
}

function nodeType(node: YamlNode): string {
  const type = node.data.label;
  if (typeof type !== "string" || type.trim() === "") {
    throw new Error(`Node ${node.id} is missing a node type`);
  }
  return type;
}

function ensureNodeConfig(
  nodeId: string,
  nodeConfigs: Record<string, Record<string, unknown>>,
) {
  if (!Object.prototype.hasOwnProperty.call(nodeConfigs, nodeId)) {
    throw new Error(`Node ${nodeId} is missing its configuration`);
  }
  return nodeConfigs[nodeId];
}

export function generateYAML(
  nodes: YamlNode[],
  edges: YamlEdge[],
  nodeConfigs: Record<string, Record<string, unknown>> = {},
  seed: number = 42,
) {
  if (nodes.length === 0) throw new Error("No nodes in pipeline");

  const nextMap: Record<string, string[]> = {};
  const incomingCount: Record<string, number> = {};
  const nodesById = new Map(nodes.map((node) => [node.id, node]));

  nodes.forEach((n) => {
    nodeType(n);
    ensureNodeConfig(n.id, nodeConfigs);
    nextMap[n.id] = [];
    incomingCount[n.id] = 0;
  });

  edges.forEach((e) => {
    if (!nodesById.has(e.source)) {
      throw new Error(`Edge ${e.id} references missing source node`);
    }
    if (!nodesById.has(e.target)) {
      throw new Error(`Edge ${e.id} references missing target node`);
    }
    nextMap[e.source].push(e.target);
    incomingCount[e.target] = (incomingCount[e.target] || 0) + 1;
  });

  nodes.forEach((node) => {
    if (nextMap[node.id].length > 1) {
      throw new Error(`Node ${nodeType(node)} has multiple outgoing edges`);
    }
    if (incomingCount[node.id] > 1) {
      throw new Error(`Node ${nodeType(node)} has multiple incoming edges`);
    }
  });

  const starts = nodes.filter((node) => incomingCount[node.id] === 0);
  if (starts.length === 0) throw new Error("Pipeline has a cycle");
  if (starts.length > 1) throw new Error("Pipeline has multiple start nodes");

  const ordered: YamlNode[] = [];
  const visited = new Set<string>();
  let current: YamlNode | undefined = starts[0];

  while (current) {
    if (visited.has(current.id)) {
      throw new Error("Pipeline has a cycle");
    }
    visited.add(current.id);
    ordered.push(current);

    const nextId: string | undefined = nextMap[current.id][0];
    current = nextId ? nodesById.get(nextId) : undefined;
  }

  if (visited.size !== nodes.length) {
    throw new Error("Pipeline contains disconnected nodes");
  }

  const firstType = nodeType(ordered[0]);
  if (firstType !== "input" && firstType !== "mic_input") {
    throw new Error("Pipeline must start with an input or mic_input node");
  }

  const lastType = nodeType(ordered[ordered.length - 1]);
  if (lastType !== "export") {
    throw new Error("Pipeline must end with an export node");
  }

  return yaml.dump(
    {
      pipeline: {
        seed: seed,
        nodes: ordered.map((n) => ({
          type: nodeType(n),
          config: normalize(ensureNodeConfig(n.id, nodeConfigs)),
        })),
      },
    },
    {
      noRefs: true,
      lineWidth: -1,
    },
  );
}
