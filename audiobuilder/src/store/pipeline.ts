import { create } from "zustand";

export interface LogEntry {
  message: string;
  timestamp: Date;
  type: "info" | "error" | "success" | "warning";
}

export interface FlowNode {
  id: string;
  type: string;
  data: Record<string, unknown>;
  position: { x: number; y: number };
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
}

interface PipelineState {
  selectedNodeId: string | null;
  selectedNodeType: string | null;
  selectNode: (id: string | null, nodeType?: string | null) => void;
  logs: LogEntry[];
  addLog: (
    message: string,
    type?: LogEntry["type"],
    timestamp?: Date,
  ) => void;
  clearLogs: () => void;
  isRunning: boolean;
  setIsRunning: (running: boolean) => void;
  error: string | null;
  setError: (error: string | null) => void;
  // Pipeline seed
  seed: number;
  setSeed: (seed: number) => void;
  // Per-node configuration storage
  nodeConfigs: Record<string, Record<string, unknown>>;
  setNodeConfig: (nodeId: string, config: Record<string, unknown>) => void;
  removeNodeConfig: (nodeId: string) => void;
  // React Flow canvas state (synced from FlowCanvas)
  flowNodes: FlowNode[];
  flowEdges: FlowEdge[];
  setFlowState: (nodes: FlowNode[], edges: FlowEdge[]) => void;
  // Global active project context
  activeProject: string | null;
  setActiveProject: (name: string | null) => void;
  lastRunId: string | null;
  setLastRunId: (id: string | null) => void;
}

export const usePipelineStore = create<PipelineState>((set) => ({
  selectedNodeId: null,
  selectedNodeType: null,
  logs: [],
  isRunning: false,
  error: null,
  seed: 42,
  nodeConfigs: {},
  flowNodes: [],
  flowEdges: [],
  activeProject: null,
  lastRunId: null,

  selectNode: (id: string | null, nodeType: string | null = null) =>
    set({ selectedNodeId: id, selectedNodeType: nodeType }),

  addLog: (
    message: string,
    type: LogEntry["type"] = "info",
    timestamp: Date = new Date(),
  ) =>
    set((state) => ({
      logs: [
        ...state.logs,
        {
          message,
          timestamp,
          type,
        },
      ],
    })),

  clearLogs: () => set({ logs: [] }),

  setIsRunning: (running: boolean) => set({ isRunning: running }),

  setError: (error: string | null) => set({ error }),

  setSeed: (seed: number) => set({ seed }),

  setNodeConfig: (nodeId: string, config: Record<string, unknown>) =>
    set((state) => ({
      nodeConfigs: { ...state.nodeConfigs, [nodeId]: config },
    })),

  removeNodeConfig: (nodeId: string) =>
    set((state) => {
      const next = { ...state.nodeConfigs };
      delete next[nodeId];
      return { nodeConfigs: next };
    }),

  setFlowState: (nodes: FlowNode[], edges: FlowEdge[]) =>
    set({ flowNodes: nodes as FlowNode[], flowEdges: edges as FlowEdge[] }),

  setActiveProject: (name: string | null) => set({ activeProject: name }),

  setLastRunId: (id: string | null) => set({ lastRunId: id }),
}));
