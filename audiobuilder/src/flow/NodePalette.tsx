import React from "react";
import {
  Search,
  Package,
  Download,
  Zap,
  Sparkles,
  Wand2,
  GitBranch,
  Upload,
  Volume2,
  Mic,
  ChevronDown,
} from "lucide-react";

type PaletteSchema = {
  label?: string;
  kind?: string;
  description?: string;
  category?: string;
};

interface NodePaletteProps {
  schemas: Record<string, unknown>;
}

const STORAGE_KEY = "nodePalette_collapsed";

function loadCollapsed(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Record<string, boolean>;
  } catch {
    return {};
  }
}

export default function NodePalette({ schemas }: NodePaletteProps) {
  const [searchTerm, setSearchTerm] = React.useState("");
  const [collapsed, setCollapsed] = React.useState<Record<string, boolean>>(loadCollapsed);
  const searchInputRef = React.useRef<HTMLInputElement>(null);

  // Listen for the custom focus-search event dispatched by useKeyboardShortcuts
  React.useEffect(() => {
    const handleFocusSearch = () => {
      searchInputRef.current?.focus();
      searchInputRef.current?.select();
    };
    window.addEventListener("audiobuilder:focus-search", handleFocusSearch);
    return () => {
      window.removeEventListener("audiobuilder:focus-search", handleFocusSearch);
    };
  }, []);

  const toggleCategory = (cat: string) => {
    setCollapsed((prev) => {
      const next = { ...prev, [cat]: !prev[cat] };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  };

  const onDragStart = (event: React.DragEvent<HTMLDivElement>, type: string) => {
    event.dataTransfer.setData("application/reactflow", type);
    event.dataTransfer.effectAllowed = "move";
  };

  // Icon mapping for node types
  const iconMap: Record<string, React.ReactNode> = {
    input: <Download className="w-5 h-5" />,
    mic_input: <Mic className="w-5 h-5" />,
    segment: <Zap className="w-5 h-5" />,
    clean: <Sparkles className="w-5 h-5" />,
    augment: <Wand2 className="w-5 h-5" />,
    split: <GitBranch className="w-5 h-5" />,
    export: <Upload className="w-5 h-5" />,
    noise: <Volume2 className="w-5 h-5" />,
  };

  const filteredSchemas = Object.entries(schemas).filter(([type, rawDef]) => {
    const def = rawDef as PaletteSchema;
    return (
      type.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (def.label?.toLowerCase().includes(searchTerm.toLowerCase()) ?? false)
    );
  });

  const grouped = React.useMemo(() => {
    const map: Record<string, Array<[string, PaletteSchema]>> = {};
    for (const [type, rawDef] of Object.entries(schemas)) {
      const def = rawDef as PaletteSchema;
      const cat = def.category ?? (def.kind === "plugin" ? "Plugins" : "Other");
      if (!map[cat]) map[cat] = [];
      map[cat].push([type, def]);
    }
    return map;
  }, [schemas]);

  const renderNodeCard = (type: string, def: PaletteSchema) => (
    <div
      key={type}
      draggable
      onDragStart={(e) => onDragStart(e, type)}
      className="p-4 rounded-xl bg-white dark:bg-secondary-700 border-2 border-secondary-200 dark:border-secondary-600 cursor-grab hover:border-primary-500 dark:hover:border-primary-400 hover:shadow-xl hover:scale-105 active:cursor-grabbing active:scale-95 transition-all duration-300 group"
    >
      <div className="flex items-center gap-3">
        <div className="p-2.5 bg-gradient-to-br from-primary-100 to-primary-200 dark:from-primary-900/40 dark:to-primary-800/40 rounded-lg text-primary-600 dark:text-primary-400 group-hover:from-primary-200 group-hover:to-primary-300 dark:group-hover:from-primary-900/60 dark:group-hover:to-primary-800/60 transition-all duration-300">
          {(iconMap[type] as React.ReactNode) || (
            <Package className="w-5 h-5" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <div className="font-bold text-sm text-secondary-900 dark:text-secondary-100 group-hover:text-primary-600 dark:group-hover:text-primary-400 transition-colors">
              {def.label || type}
            </div>
            {def.kind === "plugin" && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300">
                plugin
              </span>
            )}
          </div>
          {def.description && (
            <div className="text-xs text-secondary-500 dark:text-secondary-400 mt-1 line-clamp-2">
              {String(def.description)}
            </div>
          )}
        </div>
        <div className="text-primary-400 dark:text-primary-500 opacity-0 group-hover:opacity-100 group-hover:scale-110 transition-all duration-300">
          <Zap className="w-4 h-4" />
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex flex-col h-full bg-white dark:bg-secondary-900 border-r border-secondary-200 dark:border-secondary-700">
      {/* Header */}
      <div className="px-4 py-4 border-b border-secondary-200 dark:border-secondary-700 bg-gradient-to-b from-secondary-50 to-secondary-100 dark:from-secondary-800 dark:to-secondary-900">
        <h3 className="text-sm font-bold text-secondary-900 dark:text-secondary-100 mb-3 flex items-center gap-2">
          <Package className="w-4 h-4 text-primary-600 dark:text-primary-400" />
          Node Library
        </h3>
        {/* Search Input */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-secondary-400 dark:text-secondary-500" />
          <input
            ref={searchInputRef}
            type="text"
            placeholder="Search nodes..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-10 pr-3 py-2 text-sm border border-secondary-300 dark:border-secondary-600 rounded-lg bg-white dark:bg-secondary-700 text-secondary-900 dark:text-secondary-100 placeholder-secondary-400 dark:placeholder-secondary-500 focus:outline-none focus:ring-2 focus:ring-primary-500 dark:focus:ring-primary-400 transition-ring"
          />
        </div>
      </div>

      {/* Nodes List */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {searchTerm ? (
          /* Flat filtered list when searching */
          <div className="space-y-3">
            {filteredSchemas.length === 0 ? (
              <div className="text-center py-8">
                <p className="text-sm text-secondary-500 dark:text-secondary-400">
                  No nodes found
                </p>
              </div>
            ) : (
              filteredSchemas.map(([type, rawDef]) => {
                const def = rawDef as PaletteSchema;
                return renderNodeCard(type, def);
              })
            )}
          </div>
        ) : (
          /* Grouped view when not searching */
          <div>
            {Object.entries(grouped).map(([category, nodes]) => (
              <div key={category}>
                <button
                  onClick={() => toggleCategory(category)}
                  className="w-full flex items-center justify-between px-2 py-1.5 text-xs font-bold uppercase tracking-wider text-secondary-500 dark:text-secondary-400 hover:text-secondary-700 dark:hover:text-secondary-200 transition-colors"
                >
                  <span>{category}</span>
                  <ChevronDown
                    className={`w-3 h-3 transition-transform duration-200 ${collapsed[category] ? "-rotate-90" : ""}`}
                  />
                </button>
                {!collapsed[category] && (
                  <div className="space-y-2 mb-2">
                    {nodes.map(([type, def]) => renderNodeCard(type, def))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
