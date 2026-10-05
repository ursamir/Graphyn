import { describe, expect, it } from 'vitest'
import {
  CATALOG_WIDTH_PX,
  MIN_READABLE_ZOOM,
  catalogLoadState,
  catalogPrefKey,
  catalogRetryDelay,
  catalogShouldOpen,
  fitZoomFor,
  helpNeedsMore,
  inspectorModeFor,
  isSignificantResize,
  leftAnchoredViewport,
  planFit,
  stepSettingsState,
  toolbarCompact,
} from './editorLayout'

describe('inspectorModeFor', () => {
  it('docks at ≥1280, overlays below, bottom sheet on phones', () => {
    expect(inspectorModeFor(1536)).toBe('docked')
    expect(inspectorModeFor(1280)).toBe('docked')
    expect(inspectorModeFor(1279)).toBe('drawer')
    expect(inspectorModeFor(1024)).toBe('drawer')
    expect(inspectorModeFor(768)).toBe('drawer')
    expect(inspectorModeFor(767)).toBe('sheet')
    expect(inspectorModeFor(0)).toBe('docked')
  })
})

describe('catalog preference per size class', () => {
  it('keys the stored choice by viewport size class', () => {
    expect(catalogPrefKey(1600)).toBe('graphyn.builder.catalogOpen.desktop')
    expect(catalogPrefKey(1024)).toBe('graphyn.builder.catalogOpen.laptop')
    expect(catalogPrefKey(900)).toBe('graphyn.builder.catalogOpen.tablet')
    expect(catalogPrefKey(400)).toBe('graphyn.builder.catalogOpen.phone')
    expect(catalogPrefKey(1600)).not.toBe(catalogPrefKey(1024))
  })

  it('opens by default only when the canvas keeps ≥700px', () => {
    // 1024 viewport minus sidebar ≈ 800px editor → canvas would be ~520px.
    expect(catalogShouldOpen({ areaWidth: 800, stored: null })).toBe(false)
    expect(catalogShouldOpen({ areaWidth: 700 + CATALOG_WIDTH_PX, stored: null })).toBe(true)
    expect(catalogShouldOpen({ areaWidth: 1340, stored: null, dockedInspectorPx: 340 })).toBe(true)
    expect(catalogShouldOpen({ areaWidth: 1200, stored: null, dockedInspectorPx: 340 })).toBe(false)
  })

  it('honours a stored choice for this size class unless the canvas would be cramped', () => {
    expect(catalogShouldOpen({ areaWidth: 1600, stored: false })).toBe(false)
    expect(catalogShouldOpen({ areaWidth: 800, stored: true })).toBe(true) // 520px canvas — the user asked
    expect(catalogShouldOpen({ areaWidth: 700, stored: true })).toBe(false) // 420px — too cramped
    expect(catalogShouldOpen({ areaWidth: 0, stored: true })).toBe(true)
  })
})

describe('planFit (minimum readable zoom)', () => {
  const big = { x: 0, y: 0, width: 4000, height: 600 } // ~15-node fork, 12 columns wide

  it('fits normally when the graph is readable', () => {
    const p = planFit({ bounds: { x: 0, y: 0, width: 800, height: 300 }, canvasW: 1200, canvasH: 700, catalogOpen: true })
    expect(p).toEqual({ collapseCatalog: false, mode: 'fit', zoom: 1 })
  })

  it('collapses the catalog first when that is enough', () => {
    const bounds = { x: 0, y: 0, width: 1800, height: 400 }
    // 1100px canvas → 0.54 zoom; +240px from collapsing → 0.6+.
    expect(fitZoomFor(bounds, 1100, 700, 0.12)).toBeLessThan(MIN_READABLE_ZOOM)
    const p = planFit({ bounds, canvasW: 1100, canvasH: 700, catalogOpen: true })
    expect(p.collapseCatalog).toBe(true)
    expect(p.mode).toBe('fit')
    expect(p.zoom).toBeGreaterThanOrEqual(MIN_READABLE_ZOOM)
  })

  it('falls back to the readable zoom anchored left (never 0.3)', () => {
    expect(planFit({ bounds: big, canvasW: 1100, canvasH: 700, catalogOpen: true })).toEqual({
      collapseCatalog: true,
      mode: 'left',
      zoom: MIN_READABLE_ZOOM,
    })
    expect(planFit({ bounds: big, canvasW: 1300, canvasH: 700, catalogOpen: false })).toEqual({
      collapseCatalog: false,
      mode: 'left',
      zoom: MIN_READABLE_ZOOM,
    })
  })

  it('anchors the left edge and centres vertically when the height fits', () => {
    const v = leftAnchoredViewport({ x: 48, y: 48, width: 4000, height: 400 }, 700, 0.6, 32)
    expect(v.zoom).toBe(0.6)
    expect(v.x).toBeCloseTo(32 - 48 * 0.6)
    expect(v.y).toBeCloseTo((700 - 240) / 2 - 48 * 0.6)
    const tall = leftAnchoredViewport({ x: 0, y: 0, width: 4000, height: 2000 }, 700, 0.6, 32)
    expect(tall.y).toBe(32)
  })
})

describe('isSignificantResize', () => {
  it('ignores small jitter, reacts to panels opening/closing', () => {
    expect(isSignificantResize({ w: 1000, h: 600 }, { w: 1010, h: 600 })).toBe(false)
    expect(isSignificantResize({ w: 1000, h: 600 }, { w: 760, h: 600 })).toBe(true)
    expect(isSignificantResize({ w: 1000, h: 600 }, { w: 1000, h: 400 })).toBe(true)
    expect(isSignificantResize({ w: 0, h: 0 }, { w: 900, h: 500 })).toBe(true)
  })
})

describe('toolbarCompact', () => {
  it('compacts narrow toolbars only', () => {
    expect(toolbarCompact(560)).toBe(true)
    expect(toolbarCompact(1100)).toBe(false)
    expect(toolbarCompact(0)).toBe(false)
  })
})

describe('catalog load state → step settings', () => {
  it('backs off 2s, 5s, 10s, then 30s', () => {
    expect([0, 1, 2, 3, 9].map(catalogRetryDelay)).toEqual([2000, 5000, 10000, 30000, 30000])
  })

  it('derives the catalog state', () => {
    expect(catalogLoadState({ count: 5, error: 'x', refreshing: true, checked: true })).toBe('ready')
    expect(catalogLoadState({ count: 0, error: null, refreshing: false, checked: false })).toBe('loading')
    expect(catalogLoadState({ count: 0, error: 'down', refreshing: false, checked: true })).toBe('failed')
    expect(catalogLoadState({ count: 0, error: 'down', refreshing: true, checked: true })).toBe('loading')
    expect(catalogLoadState({ count: 0, error: null, refreshing: false, checked: true })).toBe('empty')
  })

  it('says "no fields" only for a real catalog entry with zero fields', () => {
    expect(stepSettingsState({ catalog: 'ready', hasEntry: true, fieldCount: 0 })).toBe('empty')
    expect(stepSettingsState({ catalog: 'ready', hasEntry: true, fieldCount: 3 })).toBe('fields')
    expect(stepSettingsState({ catalog: 'loading', hasEntry: false, fieldCount: 0 })).toBe('loading')
    expect(stepSettingsState({ catalog: 'failed', hasEntry: false, fieldCount: 0 })).toBe('failed')
    expect(stepSettingsState({ catalog: 'ready', hasEntry: false, fieldCount: 0 })).toBe('missing')
    expect(stepSettingsState({ catalog: 'failed', hasEntry: false, fieldCount: 2 })).toBe('fields')
  })
})

describe('helpNeedsMore', () => {
  it('puts help longer than ~3 lines behind "more"', () => {
    expect(helpNeedsMore('Mini-batch size for training and validation.')).toBe(false)
    expect(helpNeedsMore('x'.repeat(200))).toBe(true)
    expect(helpNeedsMore(undefined)).toBe(false)
  })
})
