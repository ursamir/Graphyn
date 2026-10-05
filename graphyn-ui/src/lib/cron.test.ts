import { describe, expect, it } from 'vitest'
import { describeCron, intervalText, scheduleCadence } from './cron'

const text = (e: string) => {
  const p = describeCron(e)
  return p.ok ? p.text : `ERR ${p.error}`
}

describe('describeCron', () => {
  it('reads common schedules in plain English (UTC)', () => {
    expect(text('0 9 * * 1-5')).toBe('every weekday at 09:00 UTC')
    expect(text('*/15 * * * *')).toBe('every 15 minutes')
    expect(text('0 * * * *')).toBe('every hour')
    expect(text('30 * * * *')).toBe('every hour at :30 UTC')
    expect(text('0 2 * * *')).toBe('every day at 02:00 UTC')
    expect(text('0 6 * * 1')).toBe('every Monday at 06:00 UTC')
    expect(text('0 0 1 * *')).toBe('on the 1st of the month at 00:00 UTC')
    expect(text('0 8 * * sat,sun')).toBe('on weekends at 08:00 UTC')
    expect(text('0 0 */6 * *')).toContain('on days 1, 7, 13, 19, 25 and 31 of the month')
    expect(text('0 12 * jan,jul *')).toBe('every day in January and July at 12:00 UTC')
  })
  it('expands macros', () => {
    expect(text('@daily')).toBe('every day at 00:00 UTC')
    expect(text('@hourly')).toBe('every hour')
    expect(text('@weekly')).toBe('every Sunday at 00:00 UTC')
  })
  it('treats weekday 7 as Sunday and lists several times', () => {
    expect(text('0 9 * * 7')).toBe('every Sunday at 09:00 UTC')
    expect(text('0 9,17 * * *')).toBe('every day at 09:00 and 17:00 UTC')
  })
  it('rejects malformed expressions', () => {
    expect(describeCron('').ok).toBe(false)
    expect(describeCron('* * * *').ok).toBe(false)
    expect(describeCron('60 * * * *').ok).toBe(false)
    expect(describeCron('0 9 * * 1-').ok).toBe(false)
    expect(describeCron('5-1 * * * *').ok).toBe(false)
  })
})

describe('intervalText / scheduleCadence', () => {
  it('humanizes intervals', () => {
    expect(intervalText(60)).toBe('every hour')
    expect(intervalText(1440)).toBe('every day')
    expect(intervalText(120)).toBe('every 2 hours')
    expect(intervalText(90)).toBe('every 90 minutes')
  })
  it('prefers cron over interval', () => {
    expect(scheduleCadence({ cron: '0 9 * * 1-5', interval_minutes: 60 })).toEqual({
      text: 'every weekday at 09:00 UTC',
      raw: '0 9 * * 1-5',
    })
    expect(scheduleCadence({ cron: null, interval_minutes: 30 }).text).toBe('every 30 minutes')
  })
})
