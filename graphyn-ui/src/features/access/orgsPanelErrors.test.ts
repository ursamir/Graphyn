import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// F18 carried / F19: Orgs usage / billing / members / users load failures must
// surface (ErrorBanner), never be swallowed by `.catch(() => setX(null))`.
describe('OrgsPanel load errors', () => {
  const src = readFileSync(new URL('./OrgsPanel.tsx', import.meta.url), 'utf8')
  it('has no silent catch handlers', () => {
    expect(src).not.toMatch(/\.catch\(\(\)\s*=>/)
  })
  it('renders each load error', () => {
    for (const name of ['membersError', 'usersError', 'usageError', 'billingError']) {
      expect(src).toContain(`set${name[0].toUpperCase()}${name.slice(1)}(\``)
    }
    expect(src).toContain('[membersError, usersError, usageError, billingError].map')
  })
})
