/**
 * Pure JSON-Schema-subset validation + conditional visibility for node config
 * fields rendered by the Editor inspector.
 *
 * Supported per-property keywords (from `config_schema.properties`):
 *   type (integer / number / string), enum, minimum, maximum,
 *   exclusiveMinimum, exclusiveMaximum (draft-6 numeric or draft-4 boolean
 *   form), multipleOf, minLength, maxLength, pattern.
 *
 * Conditional visibility (plugin.toml `ui = { visible_if = { field = value } }`):
 *   visible_if  = { other_field = value | [values] }   — every entry must match
 *   depends_on  = "other_field"                         — visible when truthy
 *   depends_on  = { other_field = value | [values] }    — same as visible_if
 * Read from the property itself, from a nested `ui` object, or from an
 * `x-visible-if` / `x-depends-on` extension key. Hidden fields are not
 * validated (they don't apply).
 *
 * No React here so it can be unit-tested in the node vitest env.
 */

export type FieldDef = Record<string, unknown>

/** Collapse `anyOf: [{type: X, ...}, {type: 'null'}]` into one schema. */
export function unwrapFieldSchema(def: FieldDef): FieldDef {
  if (!def || typeof def !== 'object') return {}
  if (def.enum || def.type) return def
  const anyOf = def.anyOf as FieldDef[] | undefined
  if (!Array.isArray(anyOf)) return def
  const useful = anyOf.find((x) => x && typeof x === 'object' && x.type !== 'null')
  if (!useful) return def
  return { ...def, ...useful }
}

export function fieldType(def: FieldDef): string {
  const t = unwrapFieldSchema(def).type
  if (Array.isArray(t)) return String(t.find((x) => x !== 'null') ?? 'string')
  return String(t ?? 'string')
}

export function isNullableField(def: FieldDef): boolean {
  const t = def.type
  if (Array.isArray(t) && t.includes('null')) return true
  const anyOf = def.anyOf as FieldDef[] | undefined
  if (Array.isArray(anyOf) && anyOf.some((x) => x && x.type === 'null')) return true
  return def.default === null
}

function num(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v)
  return null
}

export type NumericBounds = {
  /** Inclusive lower bound (for <input min>). */
  min: number | null
  /** Inclusive upper bound (for <input max>). */
  max: number | null
  exclusiveMin: number | null
  exclusiveMax: number | null
  multipleOf: number | null
  integer: boolean
}

export function numericBounds(def: FieldDef): NumericBounds {
  const d = unwrapFieldSchema(def)
  const integer = fieldType(def) === 'integer'
  let min = num(d.minimum)
  let max = num(d.maximum)
  let exclusiveMin: number | null = null
  let exclusiveMax: number | null = null
  // Draft-6+: exclusiveMinimum is a number. Draft-4: boolean modifier on minimum.
  if (d.exclusiveMinimum === true && min != null) {
    exclusiveMin = min
    min = null
  } else if (num(d.exclusiveMinimum) != null) {
    exclusiveMin = num(d.exclusiveMinimum)
  }
  if (d.exclusiveMaximum === true && max != null) {
    exclusiveMax = max
    max = null
  } else if (num(d.exclusiveMaximum) != null) {
    exclusiveMax = num(d.exclusiveMaximum)
  }
  const m = num(d.multipleOf)
  return { min, max, exclusiveMin, exclusiveMax, multipleOf: m != null && m > 0 ? m : null, integer }
}

/** Attributes for `<input type="number">` derived from the schema. */
export function numberInputAttrs(def: FieldDef): { min?: number; max?: number; step: number | 'any' } {
  const b = numericBounds(def)
  const out: { min?: number; max?: number; step: number | 'any' } = {
    step: b.multipleOf ?? (b.integer ? 1 : 'any'),
  }
  const lo = b.min ?? (b.exclusiveMin != null && b.integer ? b.exclusiveMin + 1 : null)
  const hi = b.max ?? (b.exclusiveMax != null && b.integer ? b.exclusiveMax - 1 : null)
  if (lo != null) out.min = lo
  if (hi != null) out.max = hi
  return out
}

export type FieldIssue = { rule: string; message: string }

function isEmpty(v: unknown): boolean {
  return v === undefined || v === null || (typeof v === 'string' && v.trim() === '')
}

function fmt(n: number): string {
  return Number.isInteger(n) ? String(n) : String(Number(n.toPrecision(12)))
}

/**
 * Validate one value against its property schema. Empty values are not
 * checked (the backend applies defaults / reports required fields).
 */
export function validateFieldValue(def: FieldDef, value: unknown): FieldIssue[] {
  if (!def || typeof def !== 'object') return []
  const d = unwrapFieldSchema(def)
  const type = fieldType(def)
  const issues: FieldIssue[] = []
  if (isEmpty(value)) return issues

  if (Array.isArray(d.enum) && d.enum.length > 0 && type !== 'array') {
    const ok = (d.enum as unknown[]).some((opt) => opt === value || String(opt) === String(value))
    if (!ok) issues.push({ rule: 'enum', message: `must be one of ${(d.enum as unknown[]).map(String).join(', ')}` })
  }

  if (type === 'number' || type === 'integer') {
    const n = num(value)
    if (n == null) {
      issues.push({ rule: 'type', message: 'must be a number' })
      return issues
    }
    const b = numericBounds(def)
    if (b.integer && !Number.isInteger(n)) issues.push({ rule: 'integer', message: 'must be a whole number' })
    if (b.min != null && n < b.min) issues.push({ rule: 'minimum', message: `must be ≥ ${fmt(b.min)}` })
    if (b.max != null && n > b.max) issues.push({ rule: 'maximum', message: `must be ≤ ${fmt(b.max)}` })
    if (b.exclusiveMin != null && n <= b.exclusiveMin) {
      issues.push({ rule: 'exclusiveMinimum', message: `must be > ${fmt(b.exclusiveMin)}` })
    }
    if (b.exclusiveMax != null && n >= b.exclusiveMax) {
      issues.push({ rule: 'exclusiveMaximum', message: `must be < ${fmt(b.exclusiveMax)}` })
    }
    if (b.multipleOf != null) {
      const q = n / b.multipleOf
      if (Math.abs(q - Math.round(q)) > 1e-9) {
        issues.push({ rule: 'multipleOf', message: `must be a multiple of ${fmt(b.multipleOf)}` })
      }
    }
    return issues
  }

  if (type === 'string' && typeof value === 'string') {
    const minLen = num(d.minLength)
    const maxLen = num(d.maxLength)
    if (minLen != null && value.length < minLen) {
      issues.push({ rule: 'minLength', message: `must be at least ${minLen} characters` })
    }
    if (maxLen != null && value.length > maxLen) {
      issues.push({ rule: 'maxLength', message: `must be at most ${maxLen} characters` })
    }
    if (typeof d.pattern === 'string' && d.pattern) {
      try {
        if (!new RegExp(d.pattern, 'u').test(value)) {
          issues.push({ rule: 'pattern', message: `must match ${d.pattern}` })
        }
      } catch {
        /* invalid pattern in the schema — not the user's fault */
      }
    }
  }
  return issues
}

type Condition = Record<string, unknown>

function conditionOf(def: FieldDef): { kind: 'map'; cond: Condition } | { kind: 'truthy'; field: string } | null {
  const ui = def.ui && typeof def.ui === 'object' && !Array.isArray(def.ui) ? (def.ui as FieldDef) : null
  const visibleIf = def.visible_if ?? ui?.visible_if ?? def['x-visible-if'] ?? def.visibleIf ?? ui?.visibleIf
  if (visibleIf && typeof visibleIf === 'object' && !Array.isArray(visibleIf)) {
    return { kind: 'map', cond: visibleIf as Condition }
  }
  const dependsOn = def.depends_on ?? ui?.depends_on ?? def['x-depends-on'] ?? def.dependsOn ?? ui?.dependsOn
  if (typeof dependsOn === 'string' && dependsOn.trim()) return { kind: 'truthy', field: dependsOn.trim() }
  if (dependsOn && typeof dependsOn === 'object' && !Array.isArray(dependsOn)) {
    return { kind: 'map', cond: dependsOn as Condition }
  }
  return null
}

function matches(actual: unknown, expected: unknown): boolean {
  if (Array.isArray(expected)) return expected.some((e) => matches(actual, e))
  if (typeof expected === 'boolean') return Boolean(actual) === expected
  if (actual === expected) return true
  if (actual == null || expected == null) return false
  return String(actual) === String(expected)
}

/** Resolve a field's effective value: config value, else schema default. */
function effective(field: string, config: Record<string, unknown>, props?: Record<string, FieldDef>): unknown {
  if (config && field in config && config[field] !== undefined) return config[field]
  return props?.[field]?.default
}

/**
 * Whether a field applies given the node's other config values. Fields without
 * a visibility hint are always visible. `props` lets a condition on a field the
 * user never touched fall back to that field's schema default.
 */
export function isFieldVisible(
  def: FieldDef,
  config: Record<string, unknown>,
  props?: Record<string, FieldDef>,
): boolean {
  if (!def || typeof def !== 'object') return true
  const c = conditionOf(def)
  if (!c) return true
  if (c.kind === 'truthy') return Boolean(effective(c.field, config, props))
  return Object.entries(c.cond).every(([field, expected]) => matches(effective(field, config, props), expected))
}

export type ConfigIssue = {
  nodeId: string
  nodeLabel: string
  field: string
  fieldLabel: string
  rule: string
  message: string
}

/** Validate every visible config field of every node. */
export function validateNodeConfigs(
  nodes: Array<{
    id: string
    data: {
      label?: string
      nodeType: string
      config?: Record<string, unknown>
      schemaProps?: Record<string, Record<string, unknown>>
    }
  }>,
  fieldLabel: (key: string, def: FieldDef) => string = (k) => k,
): ConfigIssue[] {
  const out: ConfigIssue[] = []
  for (const n of nodes) {
    const props = n.data.schemaProps ?? {}
    const config = n.data.config ?? {}
    for (const [key, def] of Object.entries(props)) {
      if (!def || typeof def !== 'object') continue
      if (!isFieldVisible(def, config, props)) continue
      const value = key in config ? config[key] : def.default
      for (const issue of validateFieldValue(def, value)) {
        out.push({
          nodeId: n.id,
          nodeLabel: n.data.label || n.data.nodeType,
          field: key,
          fieldLabel: fieldLabel(key, def),
          rule: issue.rule,
          message: issue.message,
        })
      }
    }
  }
  return out
}

/** One-line-per-issue summary for banners / toasts. */
export function formatConfigIssues(issues: ConfigIssue[], max = 6): string {
  const lines = issues
    .slice(0, max)
    .map((i) => `${i.nodeLabel} › ${i.fieldLabel}: ${i.message} (${i.rule})`)
  if (issues.length > max) lines.push(`…and ${issues.length - max} more`)
  return lines.join('\n')
}
