import { describe, expect, it } from 'vitest'
import {
  masterDetailModeFor,
  sidebarModeFor,
  stackShowsDetail,
  viewportSizeFor,
} from './viewport'

describe('viewportSizeFor', () => {
  it('maps widths to named sizes', () => {
    expect(viewportSizeFor(390)).toBe('phone')
    expect(viewportSizeFor(768)).toBe('tablet')
    expect(viewportSizeFor(1024)).toBe('laptop')
    expect(viewportSizeFor(1366)).toBe('laptop')
    expect(viewportSizeFor(1440)).toBe('desktop')
    expect(viewportSizeFor(1920)).toBe('desktop')
  })
})

describe('sidebarModeFor', () => {
  it('desktop/laptop: full by default, rail when the user collapsed it', () => {
    expect(sidebarModeFor(1920, null)).toBe('full')
    expect(sidebarModeFor(1440, 'open')).toBe('full')
    expect(sidebarModeFor(1024, null)).toBe('full')
    expect(sidebarModeFor(1366, 'collapsed')).toBe('rail')
  })
  it('tablet: always the icon rail, even if the stored preference is open', () => {
    expect(sidebarModeFor(768, 'open')).toBe('rail')
    expect(sidebarModeFor(1023, null)).toBe('rail')
    expect(sidebarModeFor(900, 'collapsed')).toBe('rail')
  })
  it('phone: hidden (drawer) regardless of preference', () => {
    expect(sidebarModeFor(360, 'open')).toBe('hidden')
    expect(sidebarModeFor(767, null)).toBe('hidden')
  })
})

describe('masterDetailModeFor', () => {
  it('splits at ≥1024, overlays at tablet, stacks on phones', () => {
    expect(masterDetailModeFor(1920)).toBe('split')
    expect(masterDetailModeFor(1024)).toBe('split')
    expect(masterDetailModeFor(1023)).toBe('overlay')
    expect(masterDetailModeFor(768)).toBe('overlay')
    expect(masterDetailModeFor(767)).toBe('stack')
    expect(masterDetailModeFor(360)).toBe('stack')
  })
})

describe('stackShowsDetail', () => {
  it('shows the list first when nothing is selected', () => {
    expect(stackShowsDetail(false, false)).toBe(false)
  })
  it('shows the detail once something is selected, until back is pressed', () => {
    expect(stackShowsDetail(true, false)).toBe(true)
    expect(stackShowsDetail(true, true)).toBe(false)
  })
  it('without a selection concept, shows the detail (list via overlay)', () => {
    expect(stackShowsDetail(undefined, false)).toBe(true)
    expect(stackShowsDetail(undefined, true)).toBe(false)
  })
})
