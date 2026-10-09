/**
 * F19 (F18 carried): muted text must meet WCAG 2.x AA (4.5:1) on the console's
 * light surfaces. ink-400 was #768ea3 (3.4:1 on white).
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import config from '../../tailwind.config.js'

const ink = (config as { theme: { extend: { colors: { ink: Record<string, string> } } } }).theme.extend.colors.ink

function luminance(hex: string): number {
  const h = hex.replace('#', '')
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) return files(p)
    return /\.tsx$/.test(name) ? [p] : []
  })
}

describe('ink palette contrast', () => {
  it('computes known ratios', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 0)
    expect(contrastRatio('#768ea3', '#ffffff')).toBeLessThan(4.5) // the old ink-400
  })

  it.each(['400', '500', '600', '700', '800', '900'])('text-ink-%s is AA on white and ink-50', (step) => {
    expect(contrastRatio(ink[step], '#ffffff')).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(ink[step], ink['50'])).toBeGreaterThanOrEqual(4.5)
  })

  it('keeps a visible step between muted (400) and secondary (500) text', () => {
    expect(contrastRatio(ink['500'], '#ffffff') - contrastRatio(ink['400'], '#ffffff')).toBeGreaterThan(0.5)
  })

  it('never puts muted ink text on a dark ink surface', () => {
    const dark = /(?<![\w:-])bg-ink-(800|900|950)(?![\w/-])/
    const muted = /(?<![\w:-])text-ink-(400|500)(?![\w/-])/
    const offenders: string[] = []
    for (const f of files(join(__dirname, '..'))) {
      readFileSync(f, 'utf8')
        .split('\n')
        .forEach((line, i) => {
          if (dark.test(line) && muted.test(line)) offenders.push(`${f}:${i + 1}`)
        })
    }
    expect(offenders).toEqual([])
  })
})
