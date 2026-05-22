import React from "react";
import {
  Plus,
  Pencil,
  Trash2,
  ChevronRight,
  ChevronDown,
  CheckCircle2,
  X,
  GripVertical,
} from "lucide-react";
import type { TaxonomyNode } from "./types";
import { InlineEdit } from "./InlineEdit";

// ---------------------------------------------------------------------------
// Taxonomy tree editor
// ---------------------------------------------------------------------------

export interface TaxonomyNodeEditorProps {
  node: TaxonomyNode;
  depth: number;
  onUpdate: (updated: TaxonomyNode) => void;
  onDelete: () => void;
  onMoveUp: (() => void) | null;
  onMoveDown: (() => void) | null;
}

export function TaxonomyNodeEditor({
  node,
  depth,
  onUpdate,
  onDelete,
  onMoveUp,
  onMoveDown,
}: TaxonomyNodeEditorProps) {
  const [expanded, setExpanded] = React.useState(true);
  const [editing, setEditing] = React.useState(false);
  const [editingDesc, setEditingDesc] = React.useState(false);
  const [descText, setDescText] = React.useState(node.description ?? "");

  const handleRename = (newName: string) => {
    onUpdate({ ...node, name: newName });
    setEditing(false);
  };

  const handleSaveDesc = () => {
    onUpdate({ ...node, description: descText.trim() || undefined });
    setEditingDesc(false);
  };

  const handleAddChild = () => {
    onUpdate({
      ...node,
      children: [...node.children, { name: "new-label", description: "", children: [] }],
    });
    setExpanded(true);
  };

  const handleUpdateChild = (idx: number, updated: TaxonomyNode) => {
    const children = [...node.children];
    children[idx] = updated;
    onUpdate({ ...node, children });
  };

  const handleDeleteChild = (idx: number) => {
    const children = node.children.filter((_, i) => i !== idx);
    onUpdate({ ...node, children });
  };

  const handleMoveChild = (idx: number, dir: -1 | 1) => {
    const children = [...node.children];
    const target = idx + dir;
    if (target < 0 || target >= children.length) return;
    [children[idx], children[target]] = [children[target], children[idx]];
    onUpdate({ ...node, children });
  };

  return (
    <div className={`${depth > 0 ? "ml-5 border-l border-secondary-200 pl-3 dark:border-secondary-700" : ""}`}>
      <div className="group flex items-center gap-1 rounded-md py-1 hover:bg-secondary-50 dark:hover:bg-secondary-800/50">
        {/* Expand/collapse */}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="shrink-0 rounded p-0.5 text-secondary-400 hover:text-secondary-600 dark:hover:text-secondary-300"
          aria-label={expanded ? "Collapse" : "Expand"}
        >
          {node.children.length > 0 ? (
            expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />
          ) : (
            <span className="inline-block h-3.5 w-3.5" />
          )}
        </button>

        {/* Name */}
        <div className="flex-1 min-w-0">
          {editing ? (
            <InlineEdit value={node.name} onSave={handleRename} onCancel={() => setEditing(false)} />
          ) : (
            <span
              className="cursor-pointer text-sm font-medium text-secondary-800 dark:text-secondary-200"
              onDoubleClick={() => setEditing(true)}
              title="Double-click to rename"
            >
              {node.name}
            </span>
          )}
          {node.description && !editingDesc && (
            <span
              className="ml-2 cursor-pointer text-xs text-secondary-400 dark:text-secondary-500"
              onDoubleClick={() => setEditingDesc(true)}
              title="Double-click to edit description"
            >
              — {node.description}
            </span>
          )}
          {editingDesc && (
            <span className="ml-2 inline-flex items-center gap-1">
              <input
                autoFocus
                type="text"
                value={descText}
                onChange={(e) => setDescText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSaveDesc();
                  if (e.key === "Escape") setEditingDesc(false);
                }}
                className="rounded border border-primary-400 bg-white px-2 py-0.5 text-xs text-secondary-700 focus:outline-none dark:bg-secondary-700 dark:text-secondary-200"
                placeholder="description"
              />
              <button type="button" onClick={handleSaveDesc} className="text-green-600 hover:text-green-700">
                <CheckCircle2 className="h-3.5 w-3.5" />
              </button>
              <button type="button" onClick={() => setEditingDesc(false)} className="text-secondary-400 hover:text-secondary-600">
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          )}
        </div>

        {/* Actions (visible on hover) */}
        <div className="flex shrink-0 items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="rounded p-1 text-secondary-400 hover:bg-secondary-100 hover:text-secondary-700 dark:hover:bg-secondary-700 dark:hover:text-secondary-200"
            title="Rename"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={handleAddChild}
            className="rounded p-1 text-secondary-400 hover:bg-secondary-100 hover:text-secondary-700 dark:hover:bg-secondary-700 dark:hover:text-secondary-200"
            title="Add child label"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          {onMoveUp && (
            <button
              type="button"
              onClick={onMoveUp}
              className="rounded p-1 text-secondary-400 hover:bg-secondary-100 hover:text-secondary-700 dark:hover:bg-secondary-700 dark:hover:text-secondary-200"
              title="Move up"
            >
              <GripVertical className="h-3.5 w-3.5 rotate-90" />
            </button>
          )}
          {onMoveDown && (
            <button
              type="button"
              onClick={onMoveDown}
              className="rounded p-1 text-secondary-400 hover:bg-secondary-100 hover:text-secondary-700 dark:hover:bg-secondary-700 dark:hover:text-secondary-200"
              title="Move down"
            >
              <GripVertical className="h-3.5 w-3.5 -rotate-90" />
            </button>
          )}
          <button
            type="button"
            onClick={onDelete}
            className="rounded p-1 text-secondary-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20 dark:hover:text-red-400"
            title="Delete"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {expanded && node.children.length > 0 && (
        <div>
          {node.children.map((child, idx) => (
            <TaxonomyNodeEditor
              key={`${child.name}-${idx}`}
              node={child}
              depth={depth + 1}
              onUpdate={(updated) => handleUpdateChild(idx, updated)}
              onDelete={() => handleDeleteChild(idx)}
              onMoveUp={idx > 0 ? () => handleMoveChild(idx, -1) : null}
              onMoveDown={idx < node.children.length - 1 ? () => handleMoveChild(idx, 1) : null}
            />
          ))}
        </div>
      )}
    </div>
  );
}
