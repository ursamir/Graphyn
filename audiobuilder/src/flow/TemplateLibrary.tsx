import React from "react";
import { X, BookOpen, Loader2, Trash2 } from "lucide-react";
import { apiUrl } from "../utils/api";

interface Template {
  name: string;
  title: string;
  description: string;
  is_user?: boolean;
}

interface TemplateLibraryProps {
  schemas: Record<string, unknown>;
  hasNodes: boolean;
  onClose: () => void;
  onLoad: (yamlStr: string) => void;
  refreshKey?: number;
  onDelete?: (name: string) => void;
}

export default function TemplateLibrary({
  schemas: _schemas, // eslint-disable-line @typescript-eslint/no-unused-vars
  hasNodes,
  onClose,
  onLoad,
  refreshKey,
  onDelete: _onDelete, // eslint-disable-line @typescript-eslint/no-unused-vars
}: TemplateLibraryProps) {
  const [templates, setTemplates] = React.useState<Template[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [loadingName, setLoadingName] = React.useState<string | null>(null);

  React.useEffect(() => {
    fetch(apiUrl("/templates"))
      .then((r) => r.json())
      .then((data) => {
        setTemplates(data as Template[]);
        setLoading(false);
      })
      .catch((err) => {
        setError("Failed to load templates: " + (err as Error).message);
        setLoading(false);
      });
  }, [refreshKey]);

  const handleDelete = async (name: string) => {
    setError(null);
    try {
      const res = await fetch(apiUrl(`/templates/${name}`), { method: "DELETE" });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      setTemplates((prev) => prev.filter((t) => t.name !== name));
    } catch (err) {
      setError(
        `Failed to delete template: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  };

  const handleSelect = async (template: Template) => {
    if (hasNodes) {
      const confirmed = window.confirm(
        `Load template "${template.title}"? This will replace the current pipeline.`,
      );
      if (!confirmed) return;
    }

    setLoadingName(template.name);
    setError(null);
    try {
      const res = await fetch(apiUrl(`/template/${template.name}`));
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = (await res.json()) as { yaml: string };
      onLoad(data.yaml);
      onClose();
    } catch (err) {
      setError(
        `Failed to load template: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setLoadingName(null);
    }
  };

  return (
    /* Modal backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-lg mx-4 bg-white dark:bg-secondary-800 rounded-2xl shadow-2xl border border-secondary-200 dark:border-secondary-700 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-secondary-200 dark:border-secondary-700 bg-gradient-to-r from-primary-50 to-purple-50 dark:from-primary-900/20 dark:to-purple-900/20">
          <div className="flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-primary-600 dark:text-primary-400" />
            <h2 className="text-base font-bold text-secondary-900 dark:text-secondary-100">
              Pipeline Templates
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-secondary-400 hover:text-secondary-700 hover:bg-secondary-100 dark:hover:bg-secondary-700 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 max-h-[60vh] overflow-y-auto">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin text-primary-500" />
              <span className="ml-2 text-sm text-secondary-500">Loading templates...</span>
            </div>
          )}

          {error && (
            <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-4 py-3 mb-4">
              {error}
            </div>
          )}

          {!loading && templates.length === 0 && !error && (
            <div className="text-center py-12 text-secondary-500 dark:text-secondary-400">
              <BookOpen className="w-8 h-8 mx-auto mb-2 opacity-40" />
              <p className="text-sm">No templates found.</p>
              <p className="text-xs mt-1">
                Add YAML files to <code className="bg-secondary-100 dark:bg-secondary-700 px-1 rounded">workspace/configs/templates/</code>
              </p>
            </div>
          )}

          {!loading && templates.length > 0 && (
            <div className="space-y-3">
              {templates.map((template) => (
                <div key={template.name} className="flex items-center gap-2">
                  <button
                    onClick={() => void handleSelect(template)}
                    disabled={loadingName !== null}
                    className="flex-1 min-w-0 text-left p-4 rounded-xl border-2 border-secondary-200 dark:border-secondary-600 hover:border-primary-400 dark:hover:border-primary-500 hover:bg-primary-50/50 dark:hover:bg-primary-900/10 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed group"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-sm text-secondary-900 dark:text-secondary-100 group-hover:text-primary-700 dark:group-hover:text-primary-300 transition-colors">
                          {template.title}
                        </div>
                        {template.description && (
                          <div className="text-xs text-secondary-500 dark:text-secondary-400 mt-1 line-clamp-2">
                            {template.description}
                          </div>
                        )}
                      </div>
                      {loadingName === template.name && (
                        <Loader2 className="w-4 h-4 animate-spin text-primary-500 flex-shrink-0 mt-0.5" />
                      )}
                    </div>
                  </button>
                  {template.is_user === true && (
                    <button
                      onClick={() => void handleDelete(template.name)}
                      disabled={loadingName !== null}
                      aria-label="Delete template"
                      className="flex-shrink-0 p-2 rounded-lg text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-secondary-200 dark:border-secondary-700 bg-secondary-50 dark:bg-secondary-900/40">
          <p className="text-xs text-secondary-400 dark:text-secondary-500">
            Templates are loaded from <code className="bg-secondary-100 dark:bg-secondary-700 px-1 rounded">workspace/configs/templates/</code>
          </p>
        </div>
      </div>
    </div>
  );
}
