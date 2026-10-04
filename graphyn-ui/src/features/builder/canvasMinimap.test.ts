import { describe, expect, it } from 'vitest'
import { minimapLayout } from './canvasMinimap'

describe('minimapLayout', () => {
  it('hides the minimap on small canvases', () => {
    expect(minimapLayout(600, 800).show).toBe(false)
    expect(minimapLayout(1200, 300).show).toBe(false)
    expect(minimapLayout(Number.NaN, 800).show).toBe(false)
  })
  it('sizes it 140–200 px wide at 3:2', () => {
    expect(minimapLayout(800, 800)).toEqual({ show: true, width: 140, height: 93 })
    expect(minimapLayout(2400, 1200)).toEqual({ show: true, width: 200, height: 133 })
  })
  it('caps the height at a quarter of the canvas', () => {
    const l = minimapLayout(2400, 440)
    expect(l.height).toBe(110)
    expect(l.width).toBe(165)
  })
})
