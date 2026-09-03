import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow, type EdgeProps } from 'reactflow'

export default function DeletableEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  selected,
}: EdgeProps) {
  const { deleteElements } = useReactFlow()
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
      {selected && (
        <EdgeLabelRenderer>
          <button
            type="button"
            className="nodrag nopan absolute flex h-6 w-6 items-center justify-center rounded-full border border-ink-200 bg-white text-[13px] font-semibold text-rose-600 shadow-soft hover:bg-rose-50"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: 'all',
            }}
            title="Remove connection"
            aria-label="Remove connection"
            onClick={(e) => {
              e.stopPropagation()
              void deleteElements({ edges: [{ id }] })
            }}
          >
            ×
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
