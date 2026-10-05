/**
 * Unit tests for DatasetPathPicker key detection (pure).
 */
import { describe, expect, it } from 'vitest'
import { describeDatasetPath, isDatasetInputPathKey } from './DatasetPathPicker'

describe('describeDatasetPath', () => {
  it('names the folder kind', () => {
    expect(describeDatasetPath('workspace/datasets/input/yes')).toBe('Input · yes')
    expect(describeDatasetPath('workspace/datasets/output/my-test1/v1')).toBe('Prepared · my-test1/v1')
    expect(describeDatasetPath('workspace/datasets/output/my-test1/latest')).toBe('Prepared · my-test1 (newest)')
    expect(describeDatasetPath('workspace/datasets/output/_inputs/yes/v2')).toBe('Frozen input · yes/v2')
    expect(describeDatasetPath('workspace/artifacts/sc/dataset/speech_commands/v3')).toBe(
      'Legacy · speech_commands/v3',
    )
  })
})

describe('isDatasetInputPathKey', () => {
  it('matches ingest-like keys', () => {
    expect(isDatasetInputPathKey('path')).toBe(true)
    expect(isDatasetInputPathKey('dataset_path')).toBe(true)
    expect(isDatasetInputPathKey('input_path')).toBe(true)
    expect(isDatasetInputPathKey('source_path')).toBe(true)
    expect(isDatasetInputPathKey('manifest_path')).toBe(true)
    expect(isDatasetInputPathKey('dataset')).toBe(true)
  })
  it('rejects write sinks and unrelated keys', () => {
    expect(isDatasetInputPathKey('output_path')).toBe(false)
    expect(isDatasetInputPathKey('output_dir')).toBe(false)
    expect(isDatasetInputPathKey('model_path')).toBe(false)
    expect(isDatasetInputPathKey('epochs')).toBe(false)
  })
})
