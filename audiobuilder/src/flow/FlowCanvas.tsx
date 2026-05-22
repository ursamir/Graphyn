import React from "react";
import ReactFlow, {
  Background,
  Controls,
  addEdge,
  useNodesState,
  useEdgesState,
  applyNodeChanges,
  applyEdgeChanges,
  useReactFlow,
} from "reactflow";
import type {
  Connection,
  EdgeChange,
  NodeChange,
  Node,
  Edge,
} from "reactflow";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import yaml from "js-yaml";
import "reactflow/dist/style.css";

import BaseNode from "./BaseNode";
import NodePalette from "./NodePalette";
import { usePipelineStore } from "../store/pipeline";
import { useAutosave } from "../hooks";

// ✅ stable reference (CRITICAL) - must be outside component
const nodeTypes = {
  default: BaseNode,
};

interface FlowCanvasProps {
  schemas: Record<string, unknown>;
}

export interface FlowCanvasHandle {
  clearCanvas: () => void;
  loadYAML: (yamlStr: string, schemas: Record<string, unknown>) => void;
  resetNodeStatuses: () => void;
  updateNodeStatus: (nodeId: string, status: "idle" | "running" | "success" | "error", errorMsg?: string) => void;
  getNodeIndexMap: (edges: Array<{id: string; source: string; target: string}>) => Map<number, string>;
}

type NodeSchema = Record<string, { type: string; default?: unknown }>;
type SchemaEntry = {
  schema?: NodeSchema;
  kind?: string;
  description?: string;
  label?: string;
  input_type?: string | null;
  output_type?: string | null;
  category?: string;
};

function getDefaultConfig(type: string, schema: NodeSchema) {
  const cfg: Record<string, unknown> = {};
  Object.entries(schema).forEach(([key, def]) => {
    if (def.default !== undefined) cfg[key] = def.default;
  });
  if (type === "mic_input") {
    cfg.path = "workspace/datasets/input/mic";
  }
  return cfg;
}

function toPreview(cfg: Record<string, unknown>) {
  const entries = Object.entries(cfg);
  if (entries.length === 0) return "No config";
  return entries
    .slice(0, 2)
    .map(
      ([k, v]) => `${k}=${Array.isArray(v) ? `[${v.join(",")}]` : String(v)}`,
    )
    .join(" · ");
}

function buildNodeIndexMap(nodes: Node[], edges: Edge[]): Map<number, string> {
  // Find root node (no incoming edges)
  const targetIds = new Set(edges.map((e) => e.target));
  const rootNode = nodes.find((n) => !targetIds.has(n.id));
  if (!rootNode) return new Map();

  const map = new Map<number, string>();
  const edgeMap = new Map<string, string>(); // source → target
  edges.forEach((e) => edgeMap.set(e.source, e.target));

  let current: string | undefined = rootNode.id;
  let index = 0;
  while (current) {
    map.set(index, current);
    current = edgeMap.get(current);
    index++;
  }
  return map;
}

const FlowCanvas = React.forwardRef<FlowCanvasHandle, FlowCanvasProps>(
  function FlowCanvas({ schemas }, ref) {
    const { screenToFlowPosition, project } = useReactFlow();
    const selectNode = usePipelineStore((s) => s.selectNode);
    const setFlowState = usePipelineStore((s) => s.setFlowState);
    const setNodeConfig = usePipelineStore((s) => s.setNodeConfig);
    const removeNodeConfig = usePipelineStore((s) => s.removeNodeConfig);
    const setSeed = usePipelineStore((s) => s.setSeed);
    const lastFlowSnapshotRef = React.useRef<string>("");
    const [leftOpen, setLeftOpen] = React.useState(true);
    const [draggingOutputType, setDraggingOutputType] = React.useState<string | null>(null);

    const [nodes, setNodes] = useNodesState([]);
    const [edges, setEdges] = useEdgesState([]);

    // Read nodeConfigs and seed from store for autosave
    const nodeConfigs = usePipelineStore((s) => s.nodeConfigs);
    const seed = usePipelineStore((s) => s.seed);

    // Autosave canvas state to localStorage (debounced 5s)
    useAutosave({ nodes, edges, configs: nodeConfigs, seed });

    const handleDeleteNode = React.useCallback(
      (nodeId: string) => {
        setNodes((nds) => nds.filter((n) => n.id !== nodeId));
        setEdges((eds) =>
          eds.filter((e) => e.source !== nodeId && e.target !== nodeId),
        );
        removeNodeConfig(nodeId);
        selectNode(null, null);
      },
      [setNodes, setEdges, removeNodeConfig, selectNode],
    );

    type NodeStatus = "idle" | "running" | "success" | "error";

    const updateNodeStatus = React.useCallback(
      (nodeId: string, status: NodeStatus, errorMsg?: string) => {
        setNodes((nds) =>
          nds.map((n) =>
            n.id !== nodeId
              ? n
              : { ...n, data: { ...n.data, status, statusError: errorMsg } },
          ),
        );
      },
      [setNodes],
    );

    const resetNodeStatuses = React.useCallback(() => {
      setNodes((nds) =>
        nds.map((n) => ({ ...n, data: { ...n.data, status: "idle", statusError: undefined } })),
      );
    }, [setNodes]);

    const handleNodeConfigChange = React.useCallback(
      (nodeId: string, key: string, value: unknown) => {
        setNodes((nds) =>
          nds.map((n) => {
            if (n.id !== nodeId) return n;
            const currentConfig =
              (n.data?.config as Record<string, unknown> | undefined) ?? {};
            const nextConfig = { ...currentConfig, [key]: value };
            setNodeConfig(nodeId, nextConfig);
            return {
              ...n,
              data: {
                ...n.data,
                config: nextConfig,
                preview: toPreview(nextConfig),
              },
            };
          }),
        );
      },
      [setNodes, setNodeConfig],
    );

    const createNodeData = React.useCallback(
      (
        nodeId: string,
        type: string,
        schema: NodeSchema,
        config: Record<string, unknown>,
        meta?: SchemaEntry,
      ) => ({
        label: type,
        title: meta?.label || type,
        kind: meta?.kind || "base",
        description: meta?.description,
        input_type: meta?.input_type ?? null,
        output_type: meta?.output_type ?? null,
        schema,
        config,
        preview: toPreview(config),
        onConfigChange: (field: string, value: unknown) =>
          handleNodeConfigChange(nodeId, field, value),
        onMicUpload: (inputPath: string) =>
          handleNodeConfigChange(nodeId, "path", inputPath),
        onDelete: () => handleDeleteNode(nodeId),
      }),
      [handleNodeConfigChange, handleDeleteNode],
    );

    // Expose imperative API to parent (App.tsx)
    React.useImperativeHandle(ref, () => ({
      clearCanvas() {
        setNodes([]);
        setEdges([]);
        selectNode(null, null);
        // Clear all node configs from store
        usePipelineStore.getState().flowNodes.forEach((n) => {
          usePipelineStore.getState().removeNodeConfig(n.id);
        });
      },

      loadYAML(yamlStr: string, loadSchemas: Record<string, unknown>) {
        const parsed = yaml.load(yamlStr) as {
          pipeline?: {
            seed?: number;
            nodes?: Array<{ type: string; config?: Record<string, unknown> }>;
          };
        };

        if (!parsed?.pipeline?.nodes) {
          throw new Error("Invalid pipeline YAML: missing pipeline.nodes");
        }

        const pipelineNodes = parsed.pipeline.nodes;
        const pipelineSeed = parsed.pipeline.seed;
        if (typeof pipelineSeed === "number") {
          setSeed(pipelineSeed);
        }

        // Clear existing state
        setNodes([]);
        setEdges([]);
        selectNode(null, null);

        const newNodes: Node[] = [];
        const newEdges: typeof edges = [];

        pipelineNodes.forEach((nodeCfg, i) => {
          const type = nodeCfg.type;
          const schemaDef = (loadSchemas as Record<string, SchemaEntry>)[type];
          const schema = schemaDef?.schema ?? {};
          const defaultConfig = getDefaultConfig(type, schema);
          const config = { ...defaultConfig, ...(nodeCfg.config ?? {}) };

          const nodeId = crypto.randomUUID();
          const position = { x: 200 + i * 0, y: 80 + i * 140 };

          newNodes.push({
            id: nodeId,
            type: "default",
            position,
            data: createNodeData(nodeId, type, schema, config, schemaDef),
          });

          usePipelineStore.getState().setNodeConfig(nodeId, config);

          // Chain edges
          if (i > 0) {
            newEdges.push({
              id: `e-${i - 1}-${i}`,
              source: newNodes[i - 1].id,
              target: nodeId,
            });
          }
        });

        setNodes(newNodes);
        setEdges(newEdges);
      },

      resetNodeStatuses() {
        resetNodeStatuses();
      },

      updateNodeStatus(nodeId, status, errorMsg) {
        updateNodeStatus(nodeId, status, errorMsg);
      },

      getNodeIndexMap(edgeList) {
        // Build from current nodes + provided edges
        const currentNodes = usePipelineStore.getState().flowNodes as Node[];
        return buildNodeIndexMap(currentNodes, edgeList as Edge[]);
      },
    }));

    // Sync canvas state to store so run-stream can access nodes/edges
    React.useEffect(() => {
      const snapshot = JSON.stringify({
        nodes: nodes.map((n) => ({
          id: n.id,
          x: n.position.x,
          y: n.position.y,
          label: n.data?.label,
        })),
        edges: edges.map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
        })),
      });

      if (lastFlowSnapshotRef.current === snapshot) {
        return;
      }

      lastFlowSnapshotRef.current = snapshot;
      setFlowState(
        nodes.map((node) => ({
          id: node.id,
          type: node.type ?? "default",
          data: node.data as Record<string, unknown>,
          position: node.position,
        })),
        edges.map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
        })),
      );
    }, [nodes, edges, setFlowState]);

    // ✅ proper node change handling
    const handleNodesChange = React.useCallback(
      (changes: NodeChange[]) => {
        setNodes((nds) => applyNodeChanges(changes, nds));
      },
      [setNodes],
    );

    // ✅ proper edge change handling
    const handleEdgesChange = React.useCallback(
      (changes: EdgeChange[]) => {
        setEdges((eds) => applyEdgeChanges(changes, eds));
      },
      [setEdges],
    );

    // ✅ connect edges
    const onConnect = React.useCallback(
      (params: Connection) => {
        const sourceNode = nodes.find((n) => n.id === params.source);
        const targetNode = nodes.find((n) => n.id === params.target);
        const sourceOutput = sourceNode?.data?.output_type as string | null | undefined;
        const targetInput = targetNode?.data?.input_type as string | null | undefined;
        // Block incompatible connections (only when both types are defined and non-null)
        if (
          sourceOutput != null &&
          targetInput != null &&
          sourceOutput !== targetInput
        ) {
          return;
        }
        setEdges((eds) => addEdge(params, eds));
      },
      [nodes, setEdges],
    );

    const onConnectStart = React.useCallback(
      (_event: React.MouseEvent | React.TouchEvent, { nodeId }: { nodeId: string | null }) => {
        if (!nodeId) return;
        const sourceNode = nodes.find((n) => n.id === nodeId);
        const outputType = sourceNode?.data?.output_type as string | null | undefined;
        setDraggingOutputType(outputType ?? null);
      },
      [nodes],
    );

    const onConnectEnd = React.useCallback(() => {
      setDraggingOutputType(null);
    }, []);

    // ✅ explicit node selection tracking
    const onNodeClick = React.useCallback(
      (_event: React.MouseEvent, node: Node) => {
        const nodeType =
          typeof node.data?.label === "string" ? node.data.label : null;
        selectNode(node.id, nodeType);
      },
      [selectNode],
    );

    const onPaneClick = React.useCallback(() => {
      selectNode(null, null);
    }, [selectNode]);

    const nodesWithCompat = React.useMemo(() => {
      if (!draggingOutputType) {
        return nodes.map((n) => ({
          ...n,
          data: { ...n.data, compatState: "idle" as const },
        }));
      }
      return nodes.map((n) => {
        const inputType = n.data?.input_type as string | null | undefined;
        const compat =
          inputType == null
            ? ("idle" as const)
            : inputType === draggingOutputType
              ? ("compatible" as const)
              : ("incompatible" as const);
        return { ...n, data: { ...n.data, compatState: compat } };
      });
    }, [nodes, draggingOutputType]);

    // ✅ drag & drop
    const onDrop = React.useCallback(
      (event: React.DragEvent<HTMLDivElement>) => {
        event.preventDefault();

        const type = event.dataTransfer.getData("application/reactflow");

        if (!type) return;

        const schemaDef = (schemas as Record<string, SchemaEntry>)[type];
        const schema = schemaDef?.schema ?? {};
        const defaultConfig = getDefaultConfig(type, schema);

        const toFlowPosition =
          screenToFlowPosition ??
          ((point: { x: number; y: number }) => project(point));
        const position = toFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });

        const nodeId = crypto.randomUUID();

        const newNode: Node = {
          id: nodeId,
          type: "default",
          position,
          data: createNodeData(nodeId, type, schema, defaultConfig, schemaDef),
        };

        setNodeConfig(nodeId, defaultConfig);

        setNodes((nds) => [...nds, newNode]);
      },
      [setNodes, schemas, createNodeData, setNodeConfig, screenToFlowPosition, project],
    );

    const onDragOver = (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    };

    return (
      <div className="flex h-full w-full min-h-0">
        {/* LEFT PANEL - NODE PALETTE */}
        <div
          className={`${leftOpen ? "w-72" : "w-12"} border-r border-secondary-200 dark:border-secondary-700 bg-gradient-to-b from-secondary-50 to-white dark:from-secondary-800 dark:to-secondary-900 flex flex-col shadow-lg transition-all duration-200 overflow-hidden`}
        >
          <button
            onClick={() => setLeftOpen((v) => !v)}
            className="m-2 p-2 rounded-md hover:bg-secondary-200/60 dark:hover:bg-secondary-700/60 text-secondary-700 dark:text-secondary-200"
            title={leftOpen ? "Collapse node library" : "Expand node library"}
          >
            {leftOpen ? (
              <PanelLeftClose className="w-4 h-4" />
            ) : (
              <PanelLeftOpen className="w-4 h-4" />
            )}
          </button>
          {leftOpen && <NodePalette schemas={schemas} />}
        </div>

        {/* CANVAS */}
        <div
          id="canvas-container"
          className="react-flow-wrapper flex-1 h-full w-full min-h-0 overflow-hidden"
          onDrop={onDrop}
          onDragOver={onDragOver}
        >
          <ReactFlow
            nodes={nodesWithCompat}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={handleNodesChange}
            onEdgesChange={handleEdgesChange}
            onConnect={onConnect}
            onConnectStart={onConnectStart}
            onConnectEnd={onConnectEnd}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            deleteKeyCode={["Delete", "Backspace"]}
            fitView
          >
            <Background color="#94a3b8" gap={18} size={1} />
            <Controls />
          </ReactFlow>
        </div>
      </div>
    );
  },
);

export default FlowCanvas;
