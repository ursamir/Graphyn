import React from "react";
import type { LogEntry } from "../store/pipeline";

interface LogViewerProps {
  logs: LogEntry[];
  isLoading?: boolean;
  showTimestamp?: boolean;
}

type LevelFilter = "ALL" | "INFO" | "WARNING" | "ERROR";

export function LogViewer({
  logs,
  isLoading = false,
  showTimestamp = true,
}: LogViewerProps) {
  const logEndRef = React.useRef<HTMLDivElement>(null);

  // Filter state
  const [nodeFilter, setNodeFilter] = React.useState<string>("ALL");
  const [levelFilter, setLevelFilter] = React.useState<LevelFilter>("ALL");
  const [searchText, setSearchText] = React.useState<string>("");

  // Auto-scroll to bottom when new logs arrive
  React.useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // Extract unique node_type values from log messages (e.g. "[0] clean — ...")
  const nodeTypes = React.useMemo(() => {
    const types = new Set<string>();
    for (const log of logs) {
      // Match patterns like "[0] clean —" or "node_type: clean"
      const match = log.message.match(/^\[(\d+)\]\s+(\w+)\s+[—-]/);
      if (match) types.add(match[2]);
    }
    return Array.from(types).sort();
  }, [logs]);

  // Apply filters
  const filteredLogs = React.useMemo(() => {
    return logs.filter((log) => {
      // Level filter
      if (levelFilter !== "ALL") {
        const logLevel = log.type.toUpperCase();
        if (levelFilter === "ERROR" && logLevel !== "ERROR") return false;
        if (levelFilter === "WARNING" && logLevel !== "WARNING" && logLevel !== "ERROR") return false;
        if (levelFilter === "INFO" && logLevel === "SUCCESS") {
          // treat success as info-level
        } else if (levelFilter === "INFO" && logLevel !== "INFO" && logLevel !== "SUCCESS") {
          return false;
        }
      }

      // Node filter
      if (nodeFilter !== "ALL") {
        const match = log.message.match(/^\[(\d+)\]\s+(\w+)\s+[—-]/);
        if (!match || match[2] !== nodeFilter) return false;
      }

      // Text search
      if (searchText.trim()) {
        if (!log.message.toLowerCase().includes(searchText.toLowerCase())) return false;
      }

      return true;
    });
  }, [logs, levelFilter, nodeFilter, searchText]);

  const isFiltered = levelFilter !== "ALL" || nodeFilter !== "ALL" || searchText.trim() !== "";

  const clearFilters = () => {
    setLevelFilter("ALL");
    setNodeFilter("ALL");
    setSearchText("");
  };

  const levelColor = (type: string) => {
    switch (type) {
      case "error": return "text-red-400";
      case "warning": return "text-yellow-400";
      case "success": return "text-green-300";
      default: return "text-green-400";
    }
  };

  return (
    <div className="flex flex-col gap-2">
      {/* Filter controls */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Node filter */}
        {nodeTypes.length > 0 && (
          <select
            value={nodeFilter}
            onChange={(e) => setNodeFilter(e.target.value)}
            className="rounded border border-secondary-600 bg-secondary-800 px-2 py-1 text-xs text-secondary-200 focus:outline-none focus:ring-1 focus:ring-primary-500"
            aria-label="Filter by node"
          >
            <option value="ALL">All nodes</option>
            {nodeTypes.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        )}

        {/* Level filter */}
        <select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value as LevelFilter)}
          className="rounded border border-secondary-600 bg-secondary-800 px-2 py-1 text-xs text-secondary-200 focus:outline-none focus:ring-1 focus:ring-primary-500"
          aria-label="Filter by level"
        >
          <option value="ALL">All levels</option>
          <option value="INFO">INFO+</option>
          <option value="WARNING">WARNING+</option>
          <option value="ERROR">ERROR only</option>
        </select>

        {/* Text search */}
        <input
          type="text"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="Search logs..."
          className="rounded border border-secondary-600 bg-secondary-800 px-2 py-1 text-xs text-secondary-200 placeholder-secondary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 w-40"
          aria-label="Search log messages"
        />

        {/* Count + clear */}
        {isFiltered && (
          <>
            <span className="text-xs text-secondary-400">
              {filteredLogs.length}/{logs.length}
            </span>
            <button
              type="button"
              onClick={clearFilters}
              className="rounded border border-secondary-600 bg-secondary-700 px-2 py-1 text-xs text-secondary-300 hover:bg-secondary-600 transition-colors"
            >
              Clear Filters
            </button>
          </>
        )}
      </div>

      {/* Log output */}
      <div className="bg-secondary-900 dark:bg-black text-green-400 font-mono text-sm rounded-lg p-4 h-[120px] overflow-y-auto border border-secondary-700">
        {filteredLogs.length === 0 && !isLoading && (
          <div className="text-secondary-500">
            {isFiltered ? "No matching log entries." : "No logs yet..."}
          </div>
        )}
        {filteredLogs.map((log, idx) => (
          <div
            key={`${log.timestamp.toISOString()}:${idx}`}
            className={`whitespace-pre-wrap break-words ${levelColor(log.type)}`}
          >
            {showTimestamp && (
              <span className="text-secondary-600 mr-2">
                [{log.timestamp.toLocaleTimeString()}]
              </span>
            )}
            <span className="text-secondary-400 mr-2">
              {log.type.toUpperCase()}
            </span>
            {log.message}
          </div>
        ))}
        {isLoading && <div className="text-yellow-400">⟳ Running...</div>}
        <div ref={logEndRef} />
      </div>
    </div>
  );
}
