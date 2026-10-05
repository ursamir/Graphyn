/**
 * Editor layout decisions (pure — unit-tested in editorLayout.test.ts):
 * canvas-first catalog default per viewport size class, inspector mode for the
 * viewport width, the readable-zoom fit plan, catalog retry backoff and the
 * inspector's "step settings" state.
 */
import { viewportSizeFor } from '../../lib/viewport'

// ── Inspector ────────────────────────────────────────────────────────────────

/** At / above this viewport width the inspector docks beside the canvas. */
export const INSPECTOR_DOCK_MIN_WIDTH = 1280
/** Below this the inspector is a bottom sheet. */
export const INSPECTOR_SHEET_MAX_WIDTH = 768

export type InspectorMode = 'docked' | 'drawer' | 'sheet'

/** docked (≥1280: shrinks the canvas) · drawer (768–1279: overlays it) · sheet (<768). */
export function inspectorModeFor(viewportWidth: number): InspectorMode {
  if (!Number.isFinite(viewportWidth) || viewportWidth <= 0) return 'docked'
  if (viewportWidth < INSPECTOR_SHEET_MAX_WIDTH) return 'sheet'
  if (viewportWidth < INSPECTOR_DOCK_MIN_WIDTH) return 'drawer'
  return 'docked'
}

// ── Catalog ──────────────────────────────────────────────────────────────────

/** Open catalog width (≈ `w-[min(17.5rem,32vw)]`). */
export const CATALOG_WIDTH_PX = 280
/** Collapsed catalog rail. */
export const CATALOG_RAIL_PX = 40
/** Default-open only when the canvas would keep at least this much width. */
export const CATALOG_MIN_CANVAS_PX = 700
/** Even an explicit "open" choice yields below this canvas width. */
export const CATALOG_HARD_MIN_CANVAS_PX = 480

const CATALOG_PREF_PREFIX = 'graphyn.builder.catalogOpen'

/** Catalog preference key per viewport size class (a choice made on a wide screen never applies to a narrow one). */
export function catalogPrefKey(viewportWidth: number): string {
  return `${CATALOG_PREF_PREFIX}.${viewportSizeFor(viewportWidth)}`
}

/**
 * Should the catalog be open? `areaWidth` = the Editor's width (catalog + canvas
 * + docked inspector); `dockedInspectorPx` = width a docked inspector takes now.
 */
export function catalogShouldOpen(args: {
  areaWidth: number
  stored: boolean | null
  dockedInspectorPx?: number
}): boolean {
  const { areaWidth, stored } = args
  if (!Number.isFinite(areaWidth) || areaWidth <= 0) return stored ?? false
  const canvasIfOpen = areaWidth - CATALOG_WIDTH_PX - (args.dockedInspectorPx ?? 0)
  if (stored === false) return false
  if (stored === true) return canvasIfOpen >= CATALOG_HARD_MIN_CANVAS_PX
  return canvasIfOpen >= CATALOG_MIN_CANVAS_PX
}

// ── Fit ──────────────────────────────────────────────────────────────────────

/** Below this zoom node labels are unreadable — don't fit smaller by default. */
export const MIN_READABLE_ZOOM = 0.6

export type Rect = { x: number; y: number; width: number; height: number }

/** React Flow's fitView zoom for `bounds` in a `w`×`h` canvas (getViewportForBounds). */
export function fitZoomFor(bounds: Rect, w: number, h: number, padding: number): number {
  if (bounds.width <= 0 || bounds.height <= 0 || w <= 0 || h <= 0) return 1
  return Math.min(w / (bounds.width * (1 + padding)), h / (bounds.height * (1 + padding)))
}

export type FitPlan = {
  /** Collapse the catalog first (it buys the room to stay readable). */
  collapseCatalog: boolean
  /** fit = whole graph visible; left = readable zoom anchored on the leftmost nodes. */
  mode: 'fit' | 'left'
  zoom: number
}

export function planFit(args: {
  bounds: Rect
  canvasW: number
  canvasH: number
  catalogOpen: boolean
  catalogPx?: number
  padding?: number
  minZoom?: number
  maxZoom?: number
}): FitPlan {
  const padding = args.padding ?? 0.12
  const minZoom = args.minZoom ?? MIN_READABLE_ZOOM
  const maxZoom = args.maxZoom ?? 1
  const z = fitZoomFor(args.bounds, args.canvasW, args.canvasH, padding)
  if (z >= minZoom) return { collapseCatalog: false, mode: 'fit', zoom: Math.min(z, maxZoom) }
  if (args.catalogOpen) {
    const gained = (args.catalogPx ?? CATALOG_WIDTH_PX) - CATALOG_RAIL_PX
    const z2 = fitZoomFor(args.bounds, args.canvasW + gained, args.canvasH, padding)
    if (z2 >= minZoom) return { collapseCatalog: true, mode: 'fit', zoom: Math.min(z2, maxZoom) }
    return { collapseCatalog: true, mode: 'left', zoom: minZoom }
  }
  return { collapseCatalog: false, mode: 'left', zoom: minZoom }
}

/** Viewport at `zoom` showing the graph's left edge; vertically centred when it fits, else top-aligned. */
export function leftAnchoredViewport(
  bounds: Rect,
  canvasH: number,
  zoom: number,
  padPx = 32,
): { x: number; y: number; zoom: number } {
  const h = bounds.height * zoom
  const y = h + 2 * padPx <= canvasH ? (canvasH - h) / 2 - bounds.y * zoom : padPx - bounds.y * zoom
  return { x: padPx - bounds.x * zoom, y, zoom }
}

/** Re-fit after a canvas resize only when it changed meaningfully (not every pixel). */
export function isSignificantResize(
  prev: { w: number; h: number },
  next: { w: number; h: number },
): boolean {
  if (prev.w <= 0 || prev.h <= 0) return next.w > 0 && next.h > 0
  const dw = Math.abs(next.w - prev.w)
  const dh = Math.abs(next.h - prev.h)
  return dw > Math.max(80, prev.w * 0.12) || dh > Math.max(80, prev.h * 0.12)
}

// ── Toolbar ──────────────────────────────────────────────────────────────────

/** Below this toolbar width version switch + undo/redo move into ⋯. */
export const TOOLBAR_COMPACT_MAX_PX = 760

export function toolbarCompact(width: number): boolean {
  return width > 0 && width < TOOLBAR_COMPACT_MAX_PX
}

// ── Catalog load state (inspector step settings) ─────────────────────────────

/** Auto-retry backoff for a failed catalog load: 2 s, 5 s, 10 s, then every 30 s. */
export function catalogRetryDelay(attempt: number): number {
  const steps = [2000, 5000, 10000]
  return steps[attempt] ?? 30000
}

export type CatalogLoadState = 'loading' | 'failed' | 'ready' | 'empty'

export function catalogLoadState(args: {
  count: number
  error: string | null
  refreshing: boolean
  checked: boolean
}): CatalogLoadState {
  if (args.count > 0) return 'ready'
  if (args.refreshing) return 'loading'
  if (args.error) return 'failed'
  return args.checked ? 'empty' : 'loading'
}

export type StepSettingsState = 'loading' | 'failed' | 'missing' | 'empty' | 'fields'

/**
 * What the inspector shows for a node's config: "No config fields" only when
 * the catalog entry exists and truly has zero fields.
 */
export function stepSettingsState(args: {
  catalog: CatalogLoadState
  hasEntry: boolean
  fieldCount: number
}): StepSettingsState {
  if (args.hasEntry) return args.fieldCount > 0 ? 'fields' : 'empty'
  if (args.fieldCount > 0) return 'fields' // saved schema on the node itself
  if (args.catalog === 'loading') return 'loading'
  if (args.catalog === 'failed') return 'failed'
  return 'missing'
}

// ── Field help ───────────────────────────────────────────────────────────────

/** Help text longer than ~3 inspector lines goes behind a "more" toggle. */
export function helpNeedsMore(text: string | null | undefined, charsPerLine = 46, lines = 3): boolean {
  const t = String(text ?? '').trim()
  return t.length > charsPerLine * lines
}
