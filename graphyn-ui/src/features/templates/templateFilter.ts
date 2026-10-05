/**
 * Templates → the single "Show" filter control (pure). It replaces the plugin
 * chip row, the Examples / Saved pills and the "Runnable here (N hidden)"
 * checkbox with one select whose value encodes all three.
 */

export type StarterFilter = 'all' | 'examples' | 'saved'

export type TemplateFilterState = {
  filter: StarterFilter
  runnableOnly: boolean
  plugins: string[]
}

/** Select value for the current state (plugin beats kind beats runnable). */
export function templateFilterValue(s: TemplateFilterState): string {
  if (s.plugins.length === 1) return `plugin:${s.plugins[0]}`
  if (s.plugins.length > 1) return 'plugins'
  if (s.filter === 'examples' || s.filter === 'saved') return s.filter
  return s.runnableOnly ? 'runnable' : 'all'
}

/**
 * State for a picked option. Every option is a complete view, so picking one
 * resets the other dimensions (no hidden leftover filter). `current` keeps a
 * multi-plugin selection made from the detail panel when 'plugins' is picked.
 */
export function applyTemplateFilter(value: string, current: TemplateFilterState): TemplateFilterState {
  if (value.startsWith('plugin:')) return { filter: 'all', runnableOnly: false, plugins: [value.slice(7)] }
  if (value === 'plugins') return { ...current, filter: 'all', runnableOnly: false }
  if (value === 'examples' || value === 'saved') return { filter: value, runnableOnly: false, plugins: [] }
  if (value === 'runnable') return { filter: 'all', runnableOnly: true, plugins: [] }
  return { filter: 'all', runnableOnly: false, plugins: [] }
}
