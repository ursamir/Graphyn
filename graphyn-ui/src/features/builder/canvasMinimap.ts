/**
 * Editor canvas minimap sizing (pure). The minimap is anchored bottom-right
 * and sized from the canvas box; below the breakpoint it is hidden entirely
 * (it would cover nodes and the zoom controls), not just shrunk.
 */
export const MINIMAP_MIN_CANVAS_WIDTH = 720
export const MINIMAP_MIN_CANVAS_HEIGHT = 420
/** Gap from the canvas edge (px) — matches the other canvas overlays (`right-3`). */
export const MINIMAP_MARGIN = 12

export type MinimapLayout = { show: boolean; width: number; height: number }

export function minimapLayout(canvasWidth: number, canvasHeight: number): MinimapLayout {
  if (
    !Number.isFinite(canvasWidth) ||
    !Number.isFinite(canvasHeight) ||
    canvasWidth < MINIMAP_MIN_CANVAS_WIDTH ||
    canvasHeight < MINIMAP_MIN_CANVAS_HEIGHT
  ) {
    return { show: false, width: 0, height: 0 }
  }
  // ~16% of the canvas width, 140–200 px wide, 3:2, and never taller than a quarter of the canvas.
  let width = Math.round(Math.min(200, Math.max(140, canvasWidth * 0.16)))
  let height = Math.round(width * (2 / 3))
  const maxH = Math.floor(canvasHeight * 0.25)
  if (height > maxH) {
    height = maxH
    width = Math.round(height * 1.5)
  }
  return { show: true, width, height }
}
