import { describe, expect, it } from 'vitest'
import {
  formatConfigIssues,
  isFieldVisible,
  numberInputAttrs,
  validateFieldValue,
  validateNodeConfigs,
} from './configValidation'

const rules = (def: Record<string, unknown>, v: unknown) => validateFieldValue(def, v).map((i) => i.rule)

describe('validateFieldValue', () => {
  it('numeric bounds, integer, multipleOf', () => {
    const def = { type: 'integer', minimum: 1, maximum: 96000 }
    expect(rules(def, 16000)).toEqual([])
    expect(rules(def, 0)).toEqual(['minimum'])
    expect(rules(def, 100000)).toEqual(['maximum'])
    expect(rules(def, 1.5)).toEqual(['integer'])
    expect(rules({ type: 'number', exclusiveMinimum: 0 }, 0)).toEqual(['exclusiveMinimum'])
    expect(rules({ type: 'number', exclusiveMaximum: 1 }, 1)).toEqual(['exclusiveMaximum'])
    expect(rules({ type: 'number', minimum: 0, exclusiveMinimum: true }, 0)).toEqual(['exclusiveMinimum'])
    expect(rules({ type: 'number', multipleOf: 0.5 }, 1.5)).toEqual([])
    expect(rules({ type: 'number', multipleOf: 0.5 }, 1.2)).toEqual(['multipleOf'])
    expect(rules({ type: 'number' }, 'abc')).toEqual(['type'])
  })
  it('unwraps anyOf nullable schemas and skips empty values', () => {
    const def = { anyOf: [{ type: 'integer', minimum: 1 }, { type: 'null' }], default: null }
    expect(rules(def, null)).toEqual([])
    expect(rules(def, 0)).toEqual(['minimum'])
  })
  it('enum, minLength, maxLength, pattern', () => {
    expect(rules({ type: 'string', enum: ['peak', 'lufs'] }, 'rms')).toEqual(['enum'])
    expect(rules({ type: 'string', enum: ['peak', 'lufs'] }, 'lufs')).toEqual([])
    expect(rules({ type: 'string', minLength: 3 }, 'ab')).toEqual(['minLength'])
    expect(rules({ type: 'string', maxLength: 2 }, 'abc')).toEqual(['maxLength'])
    expect(rules({ type: 'string', pattern: '^[a-z]+$' }, 'Ab')).toEqual(['pattern'])
    expect(rules({ type: 'string', pattern: '(' }, 'x')).toEqual([])
  })
})

describe('numberInputAttrs', () => {
  it('derives min/max/step', () => {
    expect(numberInputAttrs({ type: 'integer', minimum: 1, maximum: 10 })).toEqual({ min: 1, max: 10, step: 1 })
    expect(numberInputAttrs({ type: 'integer', exclusiveMinimum: 0 })).toEqual({ min: 1, step: 1 })
    expect(numberInputAttrs({ type: 'number', multipleOf: 0.1 })).toEqual({ step: 0.1 })
    expect(numberInputAttrs({ type: 'number' })).toEqual({ step: 'any' })
  })
})

describe('isFieldVisible', () => {
  const props = {
    normalize_method: { type: 'string', default: 'peak', enum: ['peak', 'rms', 'lufs'] },
    target_lufs: { type: 'number', ui: { visible_if: { normalize_method: 'lufs' } } },
    target_db: { type: 'number', visible_if: { normalize_method: ['peak', 'rms'] } },
    trim_threshold_db: { type: 'number', depends_on: 'trim_silence' },
    trim_silence: { type: 'boolean', default: true },
  }
  it('supports ui.visible_if / visible_if (value or list) / depends_on, falling back to defaults', () => {
    expect(isFieldVisible(props.target_lufs, {}, props)).toBe(false)
    expect(isFieldVisible(props.target_lufs, { normalize_method: 'lufs' }, props)).toBe(true)
    expect(isFieldVisible(props.target_db, {}, props)).toBe(true)
    expect(isFieldVisible(props.target_db, { normalize_method: 'lufs' }, props)).toBe(false)
    expect(isFieldVisible(props.trim_threshold_db, {}, props)).toBe(true)
    expect(isFieldVisible(props.trim_threshold_db, { trim_silence: false }, props)).toBe(false)
    expect(isFieldVisible({ type: 'number' }, {})).toBe(true)
  })
})

describe('validateNodeConfigs', () => {
  it('lists node + field + rule and skips hidden fields', () => {
    const nodes = [
      {
        id: 'cond_1',
        data: {
          nodeType: 'AudioConditioner',
          label: 'Audio Conditioner',
          config: { target_sample_rate: 0, normalize_method: 'peak', target_lufs: -500 },
          schemaProps: {
            target_sample_rate: { type: 'integer', minimum: 1, title: 'Target sample rate' },
            normalize_method: { type: 'string', enum: ['peak', 'lufs'] },
            target_lufs: { type: 'number', minimum: -70, ui: { visible_if: { normalize_method: 'lufs' } } },
          },
        },
      },
    ]
    const issues = validateNodeConfigs(nodes, (k, d) => String(d.title ?? k))
    expect(issues).toHaveLength(1)
    expect(issues[0]).toMatchObject({ nodeId: 'cond_1', field: 'target_sample_rate', rule: 'minimum' })
    expect(formatConfigIssues(issues)).toBe('Audio Conditioner › Target sample rate: must be ≥ 1 (minimum)')
  })
})
