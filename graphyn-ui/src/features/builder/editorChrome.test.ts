import { describe, expect, it } from 'vitest'
import {
  logBarSummary,
  nodeSummary,
  prettyCategory,
  sentenceCase,
} from './editorChrome'

describe('sentenceCase', () => {
  it('lowercases all but the first word and keeps acronyms', () => {
    expect(sentenceCase('audio_processing')).toBe('Audio processing')
    expect(sentenceCase('Data Loading')).toBe('Data loading')
    expect(sentenceCase('RAG retrieval')).toBe('RAG retrieval')
    expect(sentenceCase('modelBuilder')).toBe('Model builder')
    expect(sentenceCase('')).toBe('')
    expect(sentenceCase(undefined)).toBe('')
  })
})

describe('prettyCategory', () => {
  it('formats known acronyms and sentence-cases the rest', () => {
    expect(prettyCategory('ml')).toBe('ML')
    expect(prettyCategory('tinyml')).toBe('TinyML')
    expect(prettyCategory('mlops')).toBe('MLOps')
    expect(prettyCategory('audio_input')).toBe('Audio input')
    expect(prettyCategory(undefined)).toBe('')
  })
})

describe('nodeSummary', () => {
  it('prefers architecture + learning rate for model nodes', () => {
    expect(
      nodeSummary({ nodeType: 'model_builder', category: 'ml', config: { architecture: 'mobilenet', learning_rate: 0.002 } }),
    ).toBe('MobileNet · lr 0.002')
  })
  it('shows epochs and lr for a trainer, capped at two bits', () => {
    expect(
      nodeSummary({ nodeType: 'trainer', category: 'ml', config: { epochs: 50, learning_rate: 0.001, batch_size: 32 } }),
    ).toBe('50 epochs · lr 0.001')
  })
  it('formats tiny learning rates compactly', () => {
    expect(nodeSummary({ nodeType: 'trainer', config: { lr: 0.0001 } })).toBe('lr 1e-4')
  })
  it('uses the last path segment for dataset inputs', () => {
    expect(
      nodeSummary({ nodeType: 'dataset_ingest', category: 'audio', config: { dataset_path: 'workspace/datasets/speech_commands/' } }),
    ).toBe('speech_commands')
  })
  it('shows sample rate in kHz', () => {
    expect(nodeSummary({ nodeType: 'resample', category: 'audio', config: { sample_rate: 16000 } })).toBe('16 kHz')
  })
  it('falls back to the category, never a field count', () => {
    expect(nodeSummary({ nodeType: 'evaluator', category: 'ml', config: { verbose: true } })).toBe('ML')
    expect(nodeSummary({ nodeType: 'x', config: {} })).toBe('')
  })
  it('ignores empty values', () => {
    expect(nodeSummary({ nodeType: 'x', category: 'audio', config: { architecture: '', path: '  ' } })).toBe('Audio')
  })
})

describe('logBarSummary', () => {
  it('says idle with no logs and no run', () => {
    expect(logBarSummary({ isRunning: false, logs: [] })).toBe('idle')
  })
  it('shows the last non-empty line', () => {
    expect(
      logBarSummary({ isRunning: false, logs: [{ message: 'Trainer · done' }, { message: '  ' }] }),
    ).toBe('Trainer · done')
  })
  it('prefixes running', () => {
    expect(logBarSummary({ isRunning: true, logs: [] })).toBe('running…')
    expect(logBarSummary({ isRunning: true, logs: [{ message: 'epoch 2/10' }] })).toBe('running — epoch 2/10')
  })
  it('falls back to the linked run status', () => {
    expect(logBarSummary({ isRunning: false, logs: [], runStatus: 'failed' })).toBe('last run failed')
    expect(logBarSummary({ isRunning: false, logs: [], runStatus: 'loading' })).toBe('idle')
  })
})
