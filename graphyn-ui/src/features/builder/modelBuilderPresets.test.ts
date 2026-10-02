import { describe, expect, it } from 'vitest'
import {
  PRESET_FIXTURE_DEFAULTS,
  PRESET_FIXTURES,
  exportLayerSpecs,
  loadPresetIntoConfig,
} from './modelBuilderPresets'

describe('modelBuilderPresets', () => {
  it.each(['ds_cnn', 'mobilenet', 'simple_cnn'] as const)(
    'exportLayerSpecs(%s) matches on-disk fixture at default knobs',
    (arch) => {
      const layers = exportLayerSpecs(arch, PRESET_FIXTURE_DEFAULTS)
      expect(layers).toEqual(PRESET_FIXTURES[arch].layers)
    },
  )

  it('loadPresetIntoConfig switches to custom and fills layers', () => {
    const next = loadPresetIntoConfig('ds_cnn', { filters: 32, num_layers: 2, architecture: 'ds_cnn' })
    expect(next.architecture).toBe('custom')
    expect(Array.isArray(next.layers)).toBe(true)
    expect((next.layers as unknown[]).length).toBeGreaterThan(0)
    expect(exportLayerSpecs('ds_cnn', { filters: 32, numLayers: 2 })).toEqual(next.layers)
  })
})
