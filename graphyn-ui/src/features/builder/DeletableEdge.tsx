import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow, useStore, type EdgeProps } from 'reactflow'
import { canonicalPort } from '../../types/graph'
import { SELECT_EDGE_EVENT, conditionChipText, errorPortOf, type NodeOnError } from './workflowIr'

/**
 * Canvas edge: bezier + (selected) remove button. An IR `condition` renders a
 * small chip at the midpoint (full expression in the tooltip; click selects
 * the edge so the inspector can edit it). Wires out of a node's routed error
 * port draw dashed red.
 */
export default function DeletableEdge({
  id,
  source,
  sourceHandleId,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  selected,
  data,
}: EdgeProps<{ condition?: string | null } | undefined>) {
  const { deleteElements, setEdges } = useReactFlow()
  const sourceOnError = useStore(
    (s) => (s.nodeInternals.get(source)?.data as { onError?: NodeOnError | null } | undefined)?.onError ?? null,
  )
  const errPort = errorPortOf(sourceOnError)
  const isErrorBranch = Boolean(errPort && canonicalPort(sourceHandleId, 'output') === errPort)
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })
  const condition = String(data?.condition ?? '').trim()
  const chip = conditionChipText(condition)
  const edgeStyle = isErrorBranch ? { ...style, stroke: '#e11d48', strokeDasharray: '6 4' } : style
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={edgeStyle} />
      {chip || selected ? (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan absolute flex items-center gap-1"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: 'all',
            }}
          >
            {chip ? (
              <button
                type="button"
                className="max-w-[12rem] truncate rounded-full border border-amber-200 bg-amber-50 px-1.5 py-px font-mono text-[10px] text-amber-900 shadow-sm hover:border-amber-300"
                title={`Runs only when: ${condition}`}
                aria-label={`Condition: ${condition}`}
                onClick={(e) => {
                  e.stopPropagation()
                  setEdges((eds) => eds.map((ed) => ({ ...ed, selected: ed.id === id })))
                  // The label layer sits outside the edge's hit area — tell the Editor.
                  window.dispatchEvent(new CustomEvent(SELECT_EDGE_EVENT, { detail: id }))
                }}
              >
                if {chip}
              </button>
            ) : null}
            {selected ? (
              <button
                type="button"
                className="flex h-6 w-6 items-center justify-center rounded-full border border-ink-200 bg-white text-[13px] font-semibold text-rose-600 shadow-soft hover:bg-rose-50"
                title="Remove connection"
                aria-label="Remove connection"
                onClick={(e) => {
                  e.stopPropagation()
                  void deleteElements({ edges: [{ id }] })
                }}
              >
                ×
              </button>
            ) : null}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  )
}
