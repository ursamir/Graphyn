/** Paper-preset layer exporters for model_builder (parity with PluginPackage trainer). */

import dsCnnFixture from './modelBuilderPresets/ds_cnn.layers.json'
import mobilenetFixture from './modelBuilderPresets/mobilenet.layers.json'
import simpleCnnFixture from './modelBuilderPresets/simple_cnn.layers.json'

export type ModelBuilderPreset = 'ds_cnn' | 'mobilenet' | 'simple_cnn'

export type LayerSpec = Record<string, unknown> & { type: string }

export type ExportLayerOpts = {
  filters?: number
  numLayers?: number
  expansionFactor?: number
  stemStride?: number
  dropoutRate?: number
}

/** Default knobs used by on-disk fixtures (tests assert parity). */
export const PRESET_FIXTURE_DEFAULTS: Required<ExportLayerOpts> = {
  filters: 64,
  numLayers: 4,
  expansionFactor: 6,
  stemStride: 2,
  dropoutRate: 0.25,
}

export const PRESET_FIXTURES: Record<ModelBuilderPreset, { layers: LayerSpec[]; architecture: string }> = {
  ds_cnn: dsCnnFixture as { layers: LayerSpec[]; architecture: string },
  mobilenet: mobilenetFixture as { layers: LayerSpec[]; architecture: string },
  simple_cnn: simpleCnnFixture as { layers: LayerSpec[]; architecture: string },
}

/**
 * Mirror of PluginPackage/Common/trainer/model_architecture.export_layer_specs
 * so Apply respects the node's current filters / depth / MobileNet knobs.
 */
export function exportLayerSpecs(
  architecture: ModelBuilderPreset,
  opts: ExportLayerOpts = {},
): LayerSpec[] {
  const filters = Math.max(1, Math.floor(opts.filters ?? 64))
  const numLayers = Math.max(0, Math.floor(opts.numLayers ?? 4))
  const expansionFactor = Math.max(1, Math.floor(opts.expansionFactor ?? 6))
  const stemStride = Math.max(1, Math.floor(opts.stemStride ?? 2))

  if (architecture === 'ds_cnn') {
    const layers: LayerSpec[] = [
      { type: 'conv2d', filters, kernel_size: 3, strides: 1, padding: 'same', use_bias: true },
      { type: 'batch_norm' },
      { type: 'relu' },
    ]
    for (let i = 0; i < numLayers; i++) {
      layers.push({ type: 'ds_separable_block', filters, kernel_size: 3, padding: 'same' })
    }
    return layers
  }

  if (architecture === 'mobilenet') {
    const base = filters
    let width = filters
    const layers: LayerSpec[] = [
      {
        type: 'conv2d',
        filters: width,
        kernel_size: 3,
        strides: stemStride,
        padding: 'same',
        use_bias: false,
      },
      { type: 'batch_norm' },
      { type: 'relu6' },
    ]
    for (let i = 0; i < numLayers; i++) {
      const stride = i % 2 === 1 ? 2 : 1
      const outCh = stride === 2 ? Math.min(width * 2, base * 4) : width
      layers.push({
        type: 'inverted_residual',
        filters: outCh,
        expansion_factor: expansionFactor,
        stride,
        kernel_size: 3,
        use_bias: false,
      })
      width = outCh
    }
    return layers
  }

  // simple_cnn
  return [
    { type: 'conv2d', filters, kernel_size: 3, padding: 'same', activation: 'relu' },
    { type: 'max_pool2d', pool_size: 2 },
    { type: 'conv2d', filters: filters * 2, kernel_size: 3, padding: 'same', activation: 'relu' },
    { type: 'max_pool2d', pool_size: 2 },
  ]
}

export function loadPresetIntoConfig(
  preset: ModelBuilderPreset,
  config: Record<string, unknown>,
): Record<string, unknown> {
  const layers = exportLayerSpecs(preset, {
    filters: Number(config.filters ?? 64),
    numLayers: Number(config.num_layers ?? 4),
    expansionFactor: Number(config.expansion_factor ?? 6),
    stemStride: Number(config.stem_stride ?? 2),
    dropoutRate: Number(config.dropout_rate ?? 0.25),
  })
  return { ...config, architecture: 'custom', layers }
}
