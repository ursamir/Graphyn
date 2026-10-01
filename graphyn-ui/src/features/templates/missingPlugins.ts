/**
 * Map a template's missing node types → plugin names using plugin manifests
 * (`GET /plugins` → `manifest.node_types`, plus `GET /plugins/search` index
 * entries when they carry node types). Node types no manifest claims stay as
 * "missing node types" — never labelled as plugin names.
 */

export type PluginManifestLike = {
  name?: string
  node_types?: string[]
  manifest?: { name?: string; node_types?: string[] } | null
}

const norm = (nt: string) => nt.replace(/^isolated_/i, '').trim().toLowerCase()

/** node_type (normalized) → plugin name. First claimant wins. */
export function buildNodeTypePluginMap(rows: readonly PluginManifestLike[]): Map<string, string> {
  const out = new Map<string, string>()
  for (const r of rows) {
    if (!r || typeof r !== 'object') continue
    const name = String(r.manifest?.name || r.name || '').trim()
    if (!name) continue
    const types = [...(r.manifest?.node_types ?? []), ...(r.node_types ?? [])]
    for (const t of types) {
      const k = norm(String(t))
      if (k && !out.has(k)) out.set(k, name)
    }
  }
  return out
}

export type MissingSummary = {
  /** Plugin names that provide some of the missing node types. */
  plugins: string[]
  /** Missing node types no known manifest provides. */
  unmapped: string[]
  /** Short label, e.g. "Needs plugins: trainer" / "Missing node types: asr_transcribe". */
  label: string
  /** Tooltip: every missing node type (and its plugin, when known). */
  tooltip: string
}

export function summarizeMissing(
  missing: readonly string[],
  map: ReadonlyMap<string, string>,
  maxShown = 3,
): MissingSummary {
  const plugins: string[] = []
  const unmapped: string[] = []
  for (const nt of missing) {
    const p = map.get(norm(nt))
    if (p) {
      if (!plugins.includes(p)) plugins.push(p)
    } else if (!unmapped.includes(nt)) unmapped.push(nt)
  }
  const list = (xs: string[]) =>
    xs.slice(0, maxShown).join(', ') + (xs.length > maxShown ? ` +${xs.length - maxShown}` : '')
  const parts: string[] = []
  if (plugins.length) parts.push(`Needs plugins: ${list(plugins)}`)
  if (unmapped.length) parts.push(`${plugins.length ? 'missing' : 'Missing'} node types: ${list(unmapped)}`)
  const detail = missing
    .map((nt) => {
      const p = map.get(norm(nt))
      return p ? `${nt} (${p})` : nt
    })
    .join(', ')
  return {
    plugins,
    unmapped,
    label: parts.join(' · '),
    tooltip: `Node types not in the loaded catalog: ${detail}. Install or enable the plugin(s) that provide them (Library → Plugins).`,
  }
}
