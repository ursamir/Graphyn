/**
 * Linked / workspace-output / recent path picker for Builder ingest-like fields.
 * Pins alone do not rewrite graphs — this control is how users pick reusable
 * Inputs or prepared Outputs without typing raw paths.
 */
import React from 'react'
import { apiJson } from '../../api/client'
import { unwrapList } from '../../api/unwrapList'
import { useAppStore } from '../../store/appStore'
import { runDatasetPaths } from '../data/datasetUsage'

const INPUT_PREFIX = 'workspace/datasets/input/'
const OUTPUT_PREFIX = 'workspace/datasets/output/'

export type PathOption = { path: string; label: string; group: string }

/** Config keys that read a dataset folder (input, output version, or legacy artifact). */
export function isDatasetInputPathKey(key: string): boolean {
  const k = key.toLowerCase()
  return (
    k === 'path' ||
    k === 'dataset_path' ||
    k === 'input_path' ||
    k === 'source_path' ||
    k === 'manifest_path' ||
    k === 'dataset'
  )
}

export function labelFromInputPath(path: string): string | null {
  const p = path.trim().replace(/\\/g, '/')
  if (!p.includes('datasets/input/')) return null
  const after = p.split('datasets/input/')[1] || ''
  const label = after.split('/').filter(Boolean)[0]
  return label || null
}

/** Pretty label for an Outputs (or legacy artifact) path. */
export function shortDatasetPath(path: string): string {
  const p = path.trim().replace(/\\/g, '/').replace(/^workspace\//, '')
  return p || path
}

/** Human label for any dataset path: what kind of folder it is, then its short name. */
export function describeDatasetPath(path: string): string {
  const p = path.trim().replace(/\\/g, '/').replace(/\/+$/, '')
  const input = labelFromInputPath(p)
  if (input) return `Input · ${input}`
  const out = p.split('datasets/output/')[1]
  if (out !== undefined) {
    const parts = out.split('/').filter(Boolean)
    if (parts[0] === '_inputs') return `Frozen input · ${parts.slice(1).join('/')}`
    if (parts[parts.length - 1] === 'latest') return `Prepared · ${parts.slice(0, -1).join('/')} (newest)`
    return `Prepared · ${parts.join('/')}`
  }
  const legacy = p.match(/artifacts\/[^/]+\/dataset\/(.+)$/)
  if (legacy) return `Legacy · ${legacy[1]}`
  return shortDatasetPath(p)
}

function isOutputFamilyPath(path: string): boolean {
  const p = path.replace(/\\/g, '/')
  return p.includes('datasets/output/') || /artifacts\/[^/]+\/dataset\//.test(p)
}

export function DatasetPathPicker({
  value,
  onPick,
}: {
  value: unknown
  onPick: (path: string) => void
}) {
  const activeProject = useAppStore((s) => s.activeProject)
  const [linked, setLinked] = React.useState<string[]>([])
  const [recentPaths, setRecentPaths] = React.useState<string[]>([])
  const [allLabels, setAllLabels] = React.useState<string[]>([])
  const [outputRows, setOutputRows] = React.useState<
    Array<{ project: string; version: string; kind?: string; fs_path?: string; label?: string }>
  >([])
  const [loading, setLoading] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    setLoading(true)
    void (async () => {
      try {
        const [inputs, outputsRaw] = await Promise.all([
          apiJson<Array<{ label?: string; accessible?: boolean } | string>>('/data/inputs').catch(() => []),
          apiJson<unknown>('/data/outputs').catch(() => []),
        ])
        if (cancelled) return
        const labels = (Array.isArray(inputs) ? inputs : [])
          .map((x) => {
            if (typeof x === 'string') return x
            if (x && typeof x === 'object' && (x as { accessible?: boolean }).accessible === false) return ''
            return String((x as { label?: string })?.label ?? '').trim()
          })
          .filter(Boolean)
        setAllLabels(labels)

        const outs = unwrapList(outputsRaw) as Array<{
          project?: string
          versions?: string[]
          kind?: string
          fs_path?: string
          label?: string
        }>
        const rows: Array<{
          project: string
          version: string
          kind?: string
          fs_path?: string
          label?: string
        }> = []
        for (const o of outs) {
          const project = String(o?.project ?? '').trim()
          if (!project) continue
          for (const v of Array.isArray(o.versions) ? o.versions : []) {
            if (v)
              rows.push({
                project,
                version: String(v),
                kind: o.kind,
                fs_path: o.fs_path,
                label: o.label,
              })
          }
        }
        setOutputRows(rows)

        if (!activeProject) {
          setLinked([])
          setRecentPaths([])
          return
        }
        const [linkData, runsRaw] = await Promise.all([
          apiJson<{ inputs?: string[] }>(`/projects/${encodeURIComponent(activeProject)}/links`).catch(() => ({
            inputs: [] as string[],
          })),
          apiJson<unknown>('/runs', { query: { limit: 30, offset: 0, project: activeProject } }).catch(() => []),
        ])
        if (cancelled) return
        const pinned = Array.isArray(linkData?.inputs) ? linkData.inputs.filter(Boolean) : []
        setLinked(pinned.filter((l) => labels.includes(l)))

        const runs = unwrapList(runsRaw)
        const counts = new Map<string, number>()
        for (const run of runs) {
          for (const p of runDatasetPaths(run)) {
            const path = String(p || '').trim().replace(/\\/g, '/')
            if (!path) continue
            counts.set(path, (counts.get(path) || 0) + 1)
          }
        }
        const ranked = [...counts.entries()]
          .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
          .map(([p]) => p)
          .slice(0, 10)
        setRecentPaths(ranked)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [activeProject])

  const current = String(value ?? '').trim().replace(/\\/g, '/')
  const options: PathOption[] = []
  const seen = new Set<string>()
  const add = (path: string, label: string, group: string) => {
    const p = path.replace(/\\/g, '/')
    if (!p || seen.has(p)) return
    seen.add(p)
    options.push({ path: p, label, group })
  }

  if (current) {
    add(current, describeDatasetPath(current), 'Current path')
  }

  for (const l of linked) {
    add(`${INPUT_PREFIX}${l}`, `Input · ${l}`, 'Linked inputs')
  }

  const workspaceOuts = activeProject
    ? outputRows.filter((r) => r.project === activeProject && r.kind !== 'artifact_dataset')
    : []
  if (activeProject && workspaceOuts.length > 0) {
    add(`${OUTPUT_PREFIX}${activeProject}/latest`, `Prepared · ${activeProject} (newest)`, 'Workspace outputs')
  }
  for (const r of workspaceOuts) {
    add(`${OUTPUT_PREFIX}${r.project}/${r.version}`, `Prepared · ${r.project}/${r.version}`, 'Workspace outputs')
  }

  for (const p of recentPaths) {
    const lab = labelFromInputPath(p)
    if (lab) add(`${INPUT_PREFIX}${lab}`, `Input · ${lab}`, 'Recent runs')
    else if (isOutputFamilyPath(p)) add(p, describeDatasetPath(p), 'Recent runs')
  }

  for (const l of allLabels) {
    add(`${INPUT_PREFIX}${l}`, `Input · ${l}`, 'All inputs')
  }

  // Other library output versions (shared / freezes / legacy artifact soft-list)
  for (const r of outputRows) {
    if (activeProject && r.project === activeProject && r.kind !== 'artifact_dataset') continue
    const group =
      r.kind === 'input_snapshot'
        ? 'Frozen inputs'
        : r.kind === 'artifact_dataset'
          ? 'Legacy artifacts'
          : 'Other outputs'
    if (r.kind === 'artifact_dataset' && r.fs_path) {
      add(`${r.fs_path}/${r.version}`, `Legacy · ${r.label ?? r.project}/${r.version}`, group)
    } else {
      const path = `${OUTPUT_PREFIX}${r.project}/${r.version}`
      add(path, describeDatasetPath(path), group)
    }
  }

  if (!options.length && !loading) return null

  const selectValue = options.some((o) => o.path === current) ? current : ''

  return (
    <div className="mt-1" data-testid="dataset-path-picker">
      <select
        className="field-control text-[11px]"
        value={selectValue}
        title="Pick a shared input, a prepared Outputs version, or a recent run path."
        onChange={(e) => {
          const next = e.target.value
          if (!next) return
          onPick(next)
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <option value="">{loading ? 'Loading datasets…' : 'Linked / outputs / recent…'}</option>
        {(
          [
            'Current path',
            'Linked inputs',
            'Workspace outputs',
            'Recent runs',
            'All inputs',
            'Frozen inputs',
            'Other outputs',
            'Legacy artifacts',
          ] as const
        ).map((group) => {
          const rows = options.filter((o) => o.group === group)
          if (!rows.length) return null
          return (
            <optgroup key={group} label={group}>
              {rows.map((o) => (
                <option key={`${group}-${o.path}`} value={o.path}>
                  {o.label}
                </option>
              ))}
            </optgroup>
          )
        })}
      </select>
      <p className="mt-0.5 text-[10px] leading-snug text-ink-400">
        Linked = Home pins (Inputs). Workspace outputs = prepared versions under this workspace.
      </p>
    </div>
  )
}
