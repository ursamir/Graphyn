import React from "react";
import {
  X,
  Search,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  BookOpen,
  Package,
  Loader2,
} from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────

type FieldDef = {
  type?: string;
  default?: unknown;
  description?: string;
};

type NodeSchemaDef = {
  label?: string;
  description?: string;
  category?: string;
  kind?: string;
  input_type?: string | null;
  output_type?: string | null;
  schema?: Record<string, FieldDef>;
};

interface HelpSidebarProps {
  isOpen: boolean;
  onClose: () => void;
  /** The node type currently selected on the canvas (e.g. "clean", "split"). */
  selectedNodeType?: string | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const DOCS_URL =
  (import.meta as unknown as { env: Record<string, string> }).env
    .VITE_DOCS_URL ?? "https://github.com/your-org/audio-pipeline-builder#readme";

/** Render a default value as a readable string. */
function formatDefault(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return `[${value.join(", ")}]`;
  return String(value);
}

/** Generate a minimal YAML usage snippet for a node. */
function buildUsageExample(type: string, def: NodeSchemaDef): string {
  const fields = def.schema ?? {};
  const lines: string[] = [`- type: ${type}`];
  const configEntries = Object.entries(fields).filter(
    ([, f]) => f.default !== undefined,
  );
  if (configEntries.length > 0) {
    lines.push("  config:");
    for (const [key, f] of configEntries) {
      const val = f.default;
      const yamlVal =
        typeof val === "string"
          ? `"${val}"`
          : Array.isArray(val)
            ? `[${val.join(", ")}]`
            : String(val);
      lines.push(`    ${key}: ${yamlVal}`);
    }
  }
  return lines.join("\n");
}

// ─── Sub-components ───────────────────────────────────────────────────────────

interface NodeEntryProps {
  type: string;
  def: NodeSchemaDef;
  isExpanded: boolean;
  isHighlighted: boolean;
  onToggle: () => void;
}

function NodeEntry({
  type,
  def,
  isExpanded,
  isHighlighted,
  onToggle,
}: NodeEntryProps) {
  const fields = def.schema ?? {};
  const fieldEntries = Object.entries(fields);

  return (
    <div
      className={`rounded-lg border transition-colors ${
        isHighlighted
          ? "border-primary-400 bg-primary-50 dark:border-primary-500 dark:bg-primary-900/20"
          : "border-secondary-200 bg-white dark:border-secondary-700 dark:bg-secondary-800"
      }`}
    >
      {/* Header row */}
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
        aria-expanded={isExpanded}
      >
        <span className="flex-shrink-0 text-secondary-400 dark:text-secondary-500">
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </span>
        <span className="flex-1 min-w-0">
          <span className="block text-sm font-semibold text-secondary-900 dark:text-secondary-100 truncate">
            {def.label ?? type}
          </span>
          {def.description && !isExpanded && (
            <span className="block text-xs text-secondary-500 dark:text-secondary-400 truncate">
              {def.description}
            </span>
          )}
        </span>
        {def.kind === "plugin" && (
          <span className="flex-shrink-0 rounded-full bg-primary-100 px-2 py-0.5 text-[10px] font-medium text-primary-700 dark:bg-primary-900/30 dark:text-primary-300">
            plugin
          </span>
        )}
        {isHighlighted && (
          <span className="flex-shrink-0 rounded-full bg-primary-500 px-2 py-0.5 text-[10px] font-medium text-white">
            selected
          </span>
        )}
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="border-t border-secondary-100 px-3 pb-3 pt-2 dark:border-secondary-700">
          {/* Full description */}
          {def.description && (
            <p className="mb-3 text-xs leading-relaxed text-secondary-600 dark:text-secondary-300">
              {def.description}
            </p>
          )}

          {/* I/O types */}
          {(def.input_type || def.output_type) && (
            <div className="mb-3 flex gap-3 text-xs">
              {def.input_type && (
                <span className="rounded bg-blue-50 px-2 py-0.5 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300">
                  in: {def.input_type}
                </span>
              )}
              {def.output_type && (
                <span className="rounded bg-green-50 px-2 py-0.5 text-green-700 dark:bg-green-900/20 dark:text-green-300">
                  out: {def.output_type}
                </span>
              )}
            </div>
          )}

          {/* Fields table */}
          {fieldEntries.length > 0 && (
            <div className="mb-3">
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-secondary-400 dark:text-secondary-500">
                Fields
              </p>
              <div className="overflow-hidden rounded border border-secondary-200 dark:border-secondary-700">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-secondary-50 dark:bg-secondary-700/50">
                      <th className="px-2 py-1.5 text-left font-semibold text-secondary-600 dark:text-secondary-400">
                        Name
                      </th>
                      <th className="px-2 py-1.5 text-left font-semibold text-secondary-600 dark:text-secondary-400">
                        Type
                      </th>
                      <th className="px-2 py-1.5 text-left font-semibold text-secondary-600 dark:text-secondary-400">
                        Default
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-secondary-100 dark:divide-secondary-700">
                    {fieldEntries.map(([fieldName, fieldDef]) => (
                      <tr key={fieldName}>
                        <td className="px-2 py-1.5 font-mono text-secondary-800 dark:text-secondary-200">
                          {fieldName}
                        </td>
                        <td className="px-2 py-1.5 text-secondary-500 dark:text-secondary-400">
                          {fieldDef.type ?? "—"}
                        </td>
                        <td className="px-2 py-1.5 font-mono text-secondary-600 dark:text-secondary-300">
                          {formatDefault(fieldDef.default)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Field descriptions */}
              {fieldEntries.some(([, f]) => f.description) && (
                <ul className="mt-1.5 space-y-0.5">
                  {fieldEntries
                    .filter(([, f]) => f.description)
                    .map(([fieldName, fieldDef]) => (
                      <li
                        key={fieldName}
                        className="text-[11px] text-secondary-500 dark:text-secondary-400"
                      >
                        <span className="font-mono font-semibold text-secondary-700 dark:text-secondary-300">
                          {fieldName}
                        </span>
                        {" — "}
                        {fieldDef.description}
                      </li>
                    ))}
                </ul>
              )}
            </div>
          )}

          {/* Usage example */}
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-secondary-400 dark:text-secondary-500">
              Usage Example
            </p>
            <pre className="overflow-x-auto rounded bg-secondary-900 p-2.5 text-[11px] leading-relaxed text-green-300 dark:bg-black/40">
              {buildUsageExample(type, def)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function HelpSidebar({
  isOpen,
  onClose,
  selectedNodeType,
}: HelpSidebarProps) {
  const [schemas, setSchemas] = React.useState<Record<
    string,
    NodeSchemaDef
  > | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [searchTerm, setSearchTerm] = React.useState("");
  // manualExpanded tracks user-toggled nodes; selectedNodeType auto-expands on top.
  const [manualExpanded, setManualExpanded] = React.useState<
    Record<string, boolean>
  >({});

  // Merge manual toggles with the auto-highlighted node so the selected node
  // is always expanded without calling setState inside an effect.
  const expandedNodes = React.useMemo(() => {
    if (selectedNodeType) {
      return { ...manualExpanded, [selectedNodeType]: manualExpanded[selectedNodeType] !== false };
    }
    return manualExpanded;
  }, [manualExpanded, selectedNodeType]);

  // Fetch schemas on mount
  React.useEffect(() => {
    const apiBase =
      (import.meta as unknown as { env: Record<string, string> }).env
        .VITE_API_URL ?? "http://localhost:8001";
    fetch(`${apiBase}/schemas`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<Record<string, NodeSchemaDef>>;
      })
      .then(setSchemas)
      .catch((err: unknown) => {
        setLoadError(
          err instanceof Error ? err.message : "Failed to load schemas",
        );
        setSchemas({});
      });
  }, []);

  const toggleNode = React.useCallback((type: string) => {
    // We need to know the current merged expanded state to toggle correctly.
    // Use a functional update that reads manualExpanded; the merged value
    // is computed in the memo above.
    setManualExpanded((prev) => ({ ...prev, [type]: !prev[type] }));
  }, []);

  // Group schemas by category
  const grouped = React.useMemo(() => {
    if (!schemas) return {};
    const map: Record<string, Array<[string, NodeSchemaDef]>> = {};
    for (const [type, def] of Object.entries(schemas)) {
      const cat =
        def.category ?? (def.kind === "plugin" ? "Plugins" : "Other");
      if (!map[cat]) map[cat] = [];
      map[cat].push([type, def]);
    }
    return map;
  }, [schemas]);

  // Filter by search term
  const filteredGrouped = React.useMemo(() => {
    if (!searchTerm.trim()) return grouped;
    const term = searchTerm.toLowerCase();
    const result: Record<string, Array<[string, NodeSchemaDef]>> = {};
    for (const [cat, nodes] of Object.entries(grouped)) {
      const matching = nodes.filter(
        ([type, def]) =>
          type.toLowerCase().includes(term) ||
          (def.label?.toLowerCase().includes(term) ?? false) ||
          (def.description?.toLowerCase().includes(term) ?? false),
      );
      if (matching.length > 0) result[cat] = matching;
    }
    return result;
  }, [grouped, searchTerm]);

  const totalVisible = React.useMemo(
    () =>
      Object.values(filteredGrouped).reduce((sum, arr) => sum + arr.length, 0),
    [filteredGrouped],
  );

  return (
    <>
      {/* Backdrop (click to close) */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/20 backdrop-blur-[1px]"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Slide-in panel */}
      <div
        role="complementary"
        aria-label="Node help sidebar"
        className={`fixed right-0 top-0 z-50 flex h-full w-[420px] max-w-[95vw] flex-col bg-white shadow-2xl transition-transform duration-300 ease-in-out dark:bg-secondary-900 ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* Panel header */}
        <div className="flex flex-shrink-0 items-center justify-between border-b border-secondary-200 bg-gradient-to-r from-primary-700 to-purple-600 px-4 py-3 dark:border-secondary-700">
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-white" />
            <h2 className="text-base font-bold text-white">Node Reference</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-white/80 transition-colors hover:bg-white/20 hover:text-white"
            aria-label="Close help sidebar"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Search */}
        <div className="flex-shrink-0 border-b border-secondary-200 px-4 py-3 dark:border-secondary-700">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-secondary-400 dark:text-secondary-500" />
            <input
              type="text"
              placeholder="Search nodes…"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full rounded-lg border border-secondary-300 bg-white py-2 pl-9 pr-3 text-sm text-secondary-900 placeholder-secondary-400 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/30 dark:border-secondary-600 dark:bg-secondary-800 dark:text-secondary-100 dark:placeholder-secondary-500"
            />
          </div>
          {searchTerm && (
            <p className="mt-1.5 text-xs text-secondary-500 dark:text-secondary-400">
              {totalVisible} node{totalVisible !== 1 ? "s" : ""} found
            </p>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {schemas === null ? (
            /* Loading state */
            <div className="flex flex-col items-center justify-center py-16 text-secondary-400 dark:text-secondary-500">
              <Loader2 className="mb-3 h-8 w-8 animate-spin" />
              <p className="text-sm">Loading node schemas…</p>
            </div>
          ) : loadError ? (
            /* Error state */
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-900/20">
              <p className="text-sm font-semibold text-red-700 dark:text-red-400">
                Failed to load schemas
              </p>
              <p className="mt-1 text-xs text-red-600 dark:text-red-300">
                {loadError}
              </p>
            </div>
          ) : Object.keys(filteredGrouped).length === 0 ? (
            /* Empty search results */
            <div className="flex flex-col items-center justify-center py-16 text-secondary-400 dark:text-secondary-500">
              <Package className="mb-3 h-8 w-8" />
              <p className="text-sm">No nodes match your search</p>
            </div>
          ) : (
            /* Grouped node list */
            <div className="space-y-4">
              {Object.entries(filteredGrouped).map(([category, nodes]) => (
                <section key={category}>
                  <h3 className="mb-2 px-1 text-[11px] font-bold uppercase tracking-wider text-secondary-400 dark:text-secondary-500">
                    {category}
                    <span className="ml-1.5 font-normal normal-case">
                      ({nodes.length})
                    </span>
                  </h3>
                  <div className="space-y-1.5">
                    {nodes.map(([type, def]) => (
                      <NodeEntry
                        key={type}
                        type={type}
                        def={def}
                        isExpanded={!!expandedNodes[type]}
                        isHighlighted={type === selectedNodeType}
                        onToggle={() => toggleNode(type)}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
        </div>

        {/* Footer — docs link */}
        <div className="flex-shrink-0 border-t border-secondary-200 px-4 py-3 dark:border-secondary-700">
          <a
            href={DOCS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-lg border border-secondary-300 bg-secondary-50 px-3 py-2 text-xs font-medium text-secondary-700 transition-colors hover:border-primary-400 hover:bg-primary-50 hover:text-primary-700 dark:border-secondary-600 dark:bg-secondary-800 dark:text-secondary-300 dark:hover:border-primary-500 dark:hover:bg-primary-900/20 dark:hover:text-primary-300"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Full Documentation
          </a>
        </div>
      </div>
    </>
  );
}
