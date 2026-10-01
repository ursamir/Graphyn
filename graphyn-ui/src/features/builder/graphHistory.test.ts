import { describe, expect, it } from 'vitest'
import {
  changeKey,
  createHistory,
  editorSnapshot,
  historyShortcut,
  pushHistory,
  redoHistory,
  snapshotSignature,
  undoHistory,
} from './graphHistory'

const node = (id: string, config: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => ({
  id,
  position: { x: 10, y: 20 },
  data: { nodeType: 'T', label: id, config, onChangeConfig: () => {}, ...extra },
})
const edge = { id: 'a->b', source: 'a', target: 'b', sourceHandle: 'output', targetHandle: 'input' }

describe('snapshot signature (dirty tracking)', () => {
  it('ignores run status, handlers, selection and node/edge order', () => {
    const a = editorSnapshot([node('a'), node('b')], [edge], 'p', 42)
    const b = editorSnapshot(
      [{ ...node('b'), selected: true } as never, node('a', {}, { status: 'failed', lastError: 'x', configIssues: 2 })],
      [{ ...edge, selected: true } as never],
      'p',
      42,
    )
    expect(snapshotSignature(a)).toBe(snapshotSignature(b))
  })

  it('changes on config / label / name / seed / edges / position', () => {
    const base = snapshotSignature(editorSnapshot([node('a', { x: 1 })], [], 'p', 1))
    expect(snapshotSignature(editorSnapshot([node('a', { x: 2 })], [], 'p', 1))).not.toBe(base)
    expect(snapshotSignature(editorSnapshot([node('a', { x: 1 }, { label: 'L' })], [], 'p', 1))).not.toBe(base)
    expect(snapshotSignature(editorSnapshot([node('a', { x: 1 })], [], 'q', 1))).not.toBe(base)
    expect(snapshotSignature(editorSnapshot([node('a', { x: 1 })], [], 'p', 2))).not.toBe(base)
    const moved = { ...node('a', { x: 1 }), position: { x: 300, y: 20 } }
    expect(snapshotSignature(editorSnapshot([moved], [], 'p', 1))).not.toBe(base)
    expect(snapshotSignature(editorSnapshot([moved], [], 'p', 1), { positions: false })).toBe(
      snapshotSignature(editorSnapshot([node('a', { x: 1 })], [], 'p', 1), { positions: false }),
    )
  })

  it('treats config key order as irrelevant', () => {
    const a = editorSnapshot([node('a', { x: 1, y: 2 })], [], 'p', 1)
    const b = editorSnapshot([node('a', { y: 2, x: 1 })], [], 'p', 1)
    expect(snapshotSignature(a)).toBe(snapshotSignature(b))
  })
})

describe('changeKey (coalescing)', () => {
  const s = (cfg: Record<string, unknown>, name = 'p') => editorSnapshot([node('a', cfg), node('b')], [edge], name, 1)
  it('identifies a single config field edit', () => {
    expect(changeKey(s({ v: 1 }), s({ v: 12 }))).toBe('config:a:v')
    expect(changeKey(s({}), s({}, 'q'))).toBe('graph:name')
  })
  it('returns null for structural changes or multi-field edits', () => {
    expect(changeKey(s({ v: 1, w: 1 }), s({ v: 2, w: 2 }))).toBeNull()
    expect(changeKey(s({}), editorSnapshot([node('a')], [edge], 'p', 1))).toBeNull()
    expect(changeKey(s({}), editorSnapshot([node('a'), node('b')], [], 'p', 1))).toBeNull()
  })
})

describe('bounded history', () => {
  it('undo / redo / new edit clears redo', () => {
    let h = createHistory(0)
    h = pushHistory(h, 1)
    h = pushHistory(h, 2)
    h = undoHistory(h)
    expect(h.present).toBe(1)
    h = redoHistory(h)
    expect(h.present).toBe(2)
    h = undoHistory(undoHistory(h))
    expect(h.present).toBe(0)
    expect(undoHistory(h)).toBe(h)
    h = pushHistory(h, 9)
    expect(h.future).toEqual([])
    expect(redoHistory(h)).toBe(h)
  })
  it('coalesces into the current step and caps past at the limit', () => {
    let h = pushHistory(createHistory('a'), 'ab')
    h = pushHistory(h, 'abc', { coalesce: true })
    expect(h.past).toEqual(['a'])
    expect(h.present).toBe('abc')
    let big = createHistory(0)
    for (let i = 1; i <= 60; i++) big = pushHistory(big, i, { limit: 50 })
    expect(big.past.length).toBe(50)
    expect(big.past[0]).toBe(10)
  })
})

describe('historyShortcut', () => {
  const ev = (key: string, o: Partial<{ ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; target: unknown }> = {}) => ({
    key,
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    ...o,
  })
  it('maps Ctrl/Cmd+Z, Shift+Ctrl+Z and Ctrl+Y', () => {
    expect(historyShortcut(ev('z', { ctrlKey: true }))).toBe('undo')
    expect(historyShortcut(ev('z', { metaKey: true }))).toBe('undo')
    expect(historyShortcut(ev('Z', { ctrlKey: true, shiftKey: true }))).toBe('redo')
    expect(historyShortcut(ev('y', { ctrlKey: true }))).toBe('redo')
    expect(historyShortcut(ev('z'))).toBeNull()
  })
  it('never fires while typing in inputs', () => {
    for (const tagName of ['INPUT', 'TEXTAREA', 'SELECT']) {
      expect(historyShortcut(ev('z', { ctrlKey: true, target: { tagName } }))).toBeNull()
    }
    expect(historyShortcut(ev('z', { ctrlKey: true, target: { tagName: 'DIV', isContentEditable: true } }))).toBeNull()
    expect(historyShortcut(ev('z', { ctrlKey: true, target: { tagName: 'DIV' } }))).toBe('undo')
  })
})
