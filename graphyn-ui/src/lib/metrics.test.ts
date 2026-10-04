import { describe, expect, it } from 'vitest'
import {
  formatDelta,
  formatMetric,
  formatMetricDelta,
  formatMetricValue,
  metricPhraseOf,
  formatPrimaryMetric,
  isRatioMetric,
  metricLabel,
  pickPrimaryMetric,
  primaryMetric,
  regressionOf,
} from './metrics'

describe('formatMetric', () => {
  it('formats decimals to 3 places', () => {
    expect(formatMetric(0.5611)).toBe('0.561')
    expect(formatMetric(12)).toBe('12')
    expect(formatMetric('0.25')).toBe('0.250')
  })
  it('supports percent', () => {
    expect(formatMetric(0.5611, { percent: true })).toBe('56.1%')
    expect(formatMetric(1, { percent: true })).toBe('100%')
  })
  it('handles junk and tiny values', () => {
    expect(formatMetric(null)).toBe('—')
    expect(formatMetric(NaN)).toBe('—')
    expect(formatMetric(0.00001)).toBe('1.0e-5')
  })
})

describe('metricLabel / isRatioMetric', () => {
  it('humanizes names', () => {
    expect(metricLabel('test_accuracy')).toBe('Test accuracy')
    expect(metricLabel('roc_auc')).toBe('ROC AUC')
  })
  it('detects ratios', () => {
    expect(isRatioMetric('test_accuracy', 0.5)).toBe(true)
    expect(isRatioMetric('loss', 0.5)).toBe(false)
    expect(isRatioMetric('accuracy', 56)).toBe(false)
  })
})

describe('primaryMetric', () => {
  it('prefers summary.primary_metric', () => {
    expect(
      primaryMetric({ summary: { primary_metric: { name: 'test_accuracy', value: 0.561 } }, metrics: { accuracy: 0.9 } }),
    ).toEqual({ name: 'test_accuracy', value: 0.561 })
  })
  it('falls back to preference order', () => {
    expect(pickPrimaryMetric({ val_accuracy: 0.7, accuracy: 0.8 })).toEqual({ name: 'accuracy', value: 0.8 })
    expect(primaryMetric({ meta: { metrics: { f1: 0.4 } } })).toEqual({ name: 'f1', value: 0.4 })
    expect(primaryMetric({ metrics: { loss: 1 } })).toBeNull()
  })
  it('formats', () => {
    expect(formatPrimaryMetric({ metrics: { test_accuracy: 0.5611 } })).toBe('Test accuracy 0.561')
  })
})

describe('regression', () => {
  it('reads regression block', () => {
    expect(regressionOf({ regression: { delta: -0.02, best_previous_value: 0.58, best_previous_run_id: 'r1' } })).toEqual({
      delta: -0.02,
      previousValue: 0.58,
      previousRunId: 'r1',
    })
    expect(regressionOf({ regression: null })).toBeNull()
  })
  it('formats deltas', () => {
    expect(formatDelta(0.041)).toBe('+0.041')
    expect(formatDelta(-0.02)).toBe('−0.020')
  })
})


describe('one metric format', () => {
  it('ratio metrics as percent, others as decimals', () => {
    expect(formatMetricValue('test_accuracy', 0.756)).toBe('75.6%')
    expect(formatMetricValue('f1', 0.5)).toBe('50%')
    expect(formatMetricValue('val_loss', 0.4123)).toBe('0.412')
    expect(formatMetricValue('accuracy', 87)).toBe('87')
    expect(metricPhraseOf({ name: 'test_accuracy', value: 0.756 })).toBe('Test accuracy 75.6%')
  })
  it('deltas in points for ratio metrics', () => {
    expect(formatMetricDelta('test_accuracy', -0.306)).toBe('−30.6 pts')
    expect(formatMetricDelta('loss', 0.02)).toBe('+0.020')
  })
})
