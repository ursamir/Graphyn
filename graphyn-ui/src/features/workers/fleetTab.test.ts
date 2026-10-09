import { describe, expect, it } from 'vitest'
import { paths } from '../../routes/paths'
import { parsePathname } from '../../routes/parsePath'
import { fleetTabFromPath, fleetTabPath } from './fleetTab'

describe('fleet tab deep links', () => {
  it('selects the Queue tab from /deploy/workers/queue', () => {
    expect(fleetTabFromPath(paths.deployQueue())).toBe('queue')
    expect(fleetTabFromPath('/deploy/workers/queue/')).toBe('queue')
    expect(fleetTabFromPath('/deploy/workers/join')).toBe('join')
    expect(fleetTabFromPath('/deploy/workers')).toBe('workers')
    expect(fleetTabFromPath('/workspaces/x')).toBe('workers')
  })
  it('round-trips tab ↔ path and the route resolves to the workers view', () => {
    for (const t of ['workers', 'queue', 'join'] as const) {
      expect(fleetTabFromPath(fleetTabPath(t))).toBe(t)
      expect(parsePathname(fleetTabPath(t), '').view).toBe('workers')
    }
    expect(fleetTabPath('queue')).toBe(paths.deployQueue())
  })
})
