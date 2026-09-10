import React from 'react'
import { RefreshCw, Copy, Pencil } from 'lucide-react'
import { apiJson } from '../../api/client'
import type { GraphIR } from '../../types/graph'
import { useAppStore } from '../../store/appStore'
import {
  ConfirmButton,
  CollapsibleJson,
  EmptyState,
  ErrorBanner,
  KeyValue,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'

interface Project {
  name: string
  status?: string
  [key: string]: unknown
}

type Tab = 'spec' | 'taxonomy' | 'contract' | 'versions' | 'snapshots' | 'diff'

const TABS: Tab[] = ['spec', 'taxonomy', 'contract', 'versions', 'snapshots', 'diff']

const STATUSES = ['active', 'archived', 'draft', 'ready'] as const

function parseProjectsHash(): { project?: string; tab?: Tab } {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const qIdx = raw.indexOf('?')
  if (qIdx < 0) return {}
  const params = new URLSearchParams(raw.slice(qIdx + 1))
  const project = (params.get('project') || '').trim() || undefined
  const tabRaw = (params.get('tab') || '').trim()
  const tab = TABS.includes(tabRaw as Tab) ? (tabRaw as Tab) : undefined
  return { project, tab }
}


const DATA_PREP_NAME_HINTS = [
  'audio-classification',
  'speech-commands',
  'dataset_ingest',
  'data-prep',
  'data_prep',
]

function templatePriority(name: string, nodeTypes: string[] | undefined, description?: string): number {
  const blob = [name, description ?? '', ...(nodeTypes ?? [])].join(' ').toLowerCase()
  let score = 0
  if (name === 'audio-classification' || name.endsWith('/audio-classification')) score += 100
  if (/speech-commands/.test(blob)) score += 80
  if (/dataset_ingest/.test(blob) || (nodeTypes ?? []).includes('dataset_ingest')) score += 60
  if (/audio-classification|data-prep|data_prep|ingest/.test(blob)) score += 40
  return score
}

function applyProjectToGraph(graph: GraphIR, project: string, version?: string): GraphIR {
  const nodes = (graph.nodes ?? []).map((n) => {
    const cfg = { ...(n.config ?? {}) } as Record<string, unknown>
    let changed = false
    // Stamp project(+version) onto dataset/export nodes; leave ingest input paths alone.
    if (
      n.node_type === 'dataset_versioner' ||
      n.node_type === 'dataset_builder' ||
      n.node_type === 'audio_exporter' ||
      n.node_type === 'export' ||
      'project' in cfg
    ) {
      if (cfg.project === undefined || cfg.project === null || cfg.project === '') {
        cfg.project = project
        changed = true
      }
    }
    if (typeof cfg.output_dir === 'string' && cfg.output_dir.includes('workspace/artifacts/')) {
      const next = `workspace/artifacts/${project}/${n.node_type}`
      if (cfg.output_dir !== next) {
        cfg.output_dir = next
        changed = true
      }
    }
    if (version) {
      if (
        ('version' in cfg || n.node_type === 'dataset_versioner' || n.node_type === 'dataset_builder') &&
        (cfg.version === undefined || cfg.version === null || cfg.version === '')
      ) {
        cfg.version = version
        changed = true
      }
      if (
        ('version_tag' in cfg || n.node_type === 'audio_exporter') &&
        (cfg.version_tag === undefined || cfg.version_tag === null || cfg.version_tag === '')
      ) {
        cfg.version_tag = version
        changed = true
      }
    }
    return changed ? { ...n, config: cfg } : n
  })
  const meta = { ...(graph.metadata ?? {}), name: graph.metadata?.name || project }
  return { ...graph, nodes, metadata: meta }
}

function lineageIds(lineage: unknown): { runId?: string; artifactId?: string } {
  if (!lineage || typeof lineage !== 'object') return {}
  const o = lineage as Record<string, unknown>
  const runId = String(o.run_id ?? o.runId ?? '').trim() || undefined
  const artifactId = String(o.artifact_id ?? o.artifactId ?? '').trim() || undefined
  return { runId, artifactId }
}

export default function ProjectsView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const openData = useAppStore((s) => s.openData)
  const openTrace = useAppStore((s) => s.openTrace)
  const openArtifacts = useAppStore((s) => s.openArtifacts)
  const setView = useAppStore((s) => s.setView)
  const setBuilderDataset = useAppStore((s) => s.setBuilderDataset)
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)
  const initialHash = React.useMemo(() => parseProjectsHash(), [])
  const [projects, setProjects] = React.useState<Project[] | null>(null)
  const [selected, setSelected] = React.useState<string | null>(initialHash.project ?? null)
  const [tab, setTab] = React.useState<Tab>(initialHash.tab ?? 'versions')
  const [newName, setNewName] = React.useState('')
  const nameRef = React.useRef<HTMLInputElement | null>(null)
  const [renameTo, setRenameTo] = React.useState('')
  const [cloneTo, setCloneTo] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  const [spec, setSpec] = React.useState('')
  const [taxonomy, setTaxonomy] = React.useState('[]')
  const [contract, setContract] = React.useState('{}')
  const [versions, setVersions] = React.useState<unknown[]>([])
  const [versionFocus, setVersionFocus] = React.useState('')
  const [versionStats, setVersionStats] = React.useState<unknown>(null)
  const [versionSamples, setVersionSamples] = React.useState<unknown>(null)
  const [snapshots, setSnapshots] = React.useState<unknown[]>([])
  const [snapshotName, setSnapshotName] = React.useState('')
  const [diffA, setDiffA] = React.useState('')
  const [diffB, setDiffB] = React.useState('')
  const [diffResult, setDiffResult] = React.useState<unknown>(null)
  const [lineage, setLineage] = React.useState<unknown>(null)

  const load = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      setProjects(await apiJson<Project[]>('/projects'))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setProjects([])
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  const open = async (name: string) => {
    setSelected(name)
    setRenameTo(name)
    setCloneTo(`${name}-copy`)
    setError(null)
    {
      const params = new URLSearchParams()
      params.set('project', name)
      if (tab && tab !== 'versions') params.set('tab', tab)
      window.history.replaceState(null, '', `#/projects?${params.toString()}`)
    }
    setVersionStats(null)
    setVersionSamples(null)
    setDiffResult(null)
    try {
      const [vers, sp, tax, con, snaps, lin] = await Promise.all([
        apiJson<unknown[]>(`/projects/${encodeURIComponent(name)}/versions`),
        apiJson<{ markdown?: string }>(`/projects/${encodeURIComponent(name)}/spec`).catch(() => ({
          markdown: '',
        })),
        apiJson(`/projects/${encodeURIComponent(name)}/taxonomy`).catch(() => []),
        apiJson(`/projects/${encodeURIComponent(name)}/contract`).catch(() => ({})),
        apiJson<unknown[]>(`/projects/${encodeURIComponent(name)}/snapshots`).catch(() => []),
        apiJson(`/projects/${encodeURIComponent(name)}/lineage`).catch(() => null),
      ])
      setVersions(vers)
      setSpec(sp?.markdown ?? '')
      setTaxonomy(JSON.stringify(tax, null, 2))
      setContract(JSON.stringify(con, null, 2))
      setSnapshots(Array.isArray(snaps) ? snaps : [])
      setLineage(lin)
      const first =
        typeof vers[0] === 'string'
          ? vers[0]
          : String((vers[0] as { version?: string } | undefined)?.version ?? '')
      setVersionFocus(first)
      setDiffA(first)
      setDiffB(typeof vers[1] === 'string' ? vers[1] : first)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  React.useEffect(() => {
    const apply = () => {
      const h = parseProjectsHash()
      if (h.tab) setTab(h.tab)
      if (h.project && h.project !== selected) void open(h.project)
    }
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected])

  React.useEffect(() => {
    if (initialHash.project) void open(initialHash.project)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const openInBuilder = async () => {
    if (!selected) {
      setView('builder')
      window.history.replaceState(null, '', '#/builder')
      pushToast('Open a data-prep template or wire dataset nodes on the canvas', 'info')
      return
    }
    const version = versionFocus.trim() || undefined
    setBuilderDataset({ project: selected, version })

    try {
      const raw = await apiJson<unknown>('/pipelines/templates')
      const list = Array.isArray(raw)
        ? raw.map((item) => {
            if (typeof item === 'string') return { name: item }
            if (item && typeof item === 'object' && typeof (item as { name?: unknown }).name === 'string') {
              return item as { name: string; description?: string; node_types?: string[] }
            }
            return { name: String(item) }
          })
        : []
      const preferredNames = [
        'audio-classification',
        'ex-02-speech-commands',
        'ex-06-speech-commands-e2e',
        ...DATA_PREP_NAME_HINTS,
      ]
      let pick: string | undefined
      for (const hint of preferredNames) {
        const hit = list.find((t) => t.name === hint || t.name.includes(hint))
        if (hit) {
          pick = hit.name
          break
        }
      }
      if (!pick) {
        const ranked = list
          .map((t) => ({
            ...t,
            score: templatePriority(t.name, t.node_types, t.description),
          }))
          .filter((t) => t.score > 0)
          .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name))
        pick = ranked[0]?.name
      }

      if (pick) {
        const data = await apiJson<{ graph?: GraphIR }>(
          `/pipelines/templates/${encodeURIComponent(pick)}`,
        )
        if (data.graph) {
          const graph = applyProjectToGraph(data.graph, selected, version)
          loadGraphIntoBuilder(graph)
          pushToast(`Opened ${pick} with dataset "${selected}"`, 'success')
          return
        }
      }

      setView('builder')
      window.history.replaceState(null, '', '#/builder')
      pushToast(
        `Builder ready — dataset "${selected}" linked (no data-prep template found)`,
        'info',
      )
    } catch (err) {
      setView('builder')
      window.history.replaceState(null, '', '#/builder')
      pushToast(
        err instanceof Error
          ? `Dataset "${selected}" linked — ${err.message}`
          : `Dataset "${selected}" linked`,
        'info',
      )
    }
  }

  const useInEdge = () => {
    const params = new URLSearchParams()
    if (selected) params.set('project', selected)
    if (versionFocus) params.set('version', versionFocus)
    const qs = params.toString()
    window.history.replaceState(null, '', qs ? `#/edge?${qs}` : '#/edge')
    setView('edge')
  }

  const create = async () => {
    if (!newName.trim()) {
      pushToast('Enter a project name first', 'error')
      nameRef.current?.focus()
      return
    }
    try {
      await apiJson('/projects', { method: 'POST', body: JSON.stringify({ name: newName.trim() }) })
      pushToast(`Created ${newName}`, 'success')
      setNewName('')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const rename = async () => {
    if (!selected || !renameTo.trim()) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}`, {
        method: 'PATCH',
        body: JSON.stringify({ new_name: renameTo.trim() }),
      })
      pushToast(`Renamed to ${renameTo}`, 'success')
      await load()
      await open(renameTo.trim())
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const clone = async () => {
    if (!selected || !cloneTo.trim()) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}/clone`, {
        method: 'POST',
        body: JSON.stringify({ new_name: cloneTo.trim() }),
      })
      pushToast(`Cloned to ${cloneTo}`, 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const setStatus = async (status: string) => {
    if (!selected) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      })
      pushToast(`Status → ${status}`, 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const remove = async () => {
    if (!selected) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}`, {
        method: 'DELETE',
        body: JSON.stringify({ confirm: selected }),
      })
      pushToast(`Deleted ${selected}`, 'success')
      setSelected(null)
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const saveSpec = async () => {
    if (!selected) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}/spec`, {
        method: 'PUT',
        body: JSON.stringify({ markdown: spec }),
      })
      pushToast('Spec saved', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const saveTaxonomy = async () => {
    if (!selected) return
    try {
      const body = JSON.parse(taxonomy) as unknown
      await apiJson(`/projects/${encodeURIComponent(selected)}/taxonomy`, {
        method: 'PUT',
        body: JSON.stringify(body),
      })
      pushToast('Taxonomy saved', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const saveContract = async () => {
    if (!selected) return
    try {
      const body = JSON.parse(contract) as unknown
      await apiJson(`/projects/${encodeURIComponent(selected)}/contract`, {
        method: 'PUT',
        body: JSON.stringify(body),
      })
      pushToast('Contract saved', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const loadVersionDetail = async () => {
    if (!selected || !versionFocus) return
    try {
      const [st, samp] = await Promise.all([
        apiJson(
          `/projects/${encodeURIComponent(selected)}/versions/${encodeURIComponent(versionFocus)}/stats`,
        ),
        apiJson(
          `/projects/${encodeURIComponent(selected)}/versions/${encodeURIComponent(versionFocus)}/samples`,
          { query: { page: 1, page_size: 20 } },
        ).catch(() => null),
      ])
      setVersionStats(st)
      setVersionSamples(samp)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const restoreVersion = async () => {
    if (!selected || !versionFocus) return
    try {
      await apiJson(
        `/projects/${encodeURIComponent(selected)}/versions/${encodeURIComponent(versionFocus)}/restore`,
        { method: 'POST' },
      )
      pushToast(`Restored ${versionFocus}`, 'success')
      await open(selected)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const createSnapshot = async () => {
    if (!selected || !snapshotName.trim()) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}/snapshots`, {
        method: 'POST',
        body: JSON.stringify({ snapshot_name: snapshotName.trim() }),
      })
      pushToast(`Snapshot ${snapshotName} created`, 'success')
      setSnapshotName('')
      await open(selected)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const restoreSnapshot = async (name: string) => {
    if (!selected) return
    try {
      await apiJson(
        `/projects/${encodeURIComponent(selected)}/snapshots/${encodeURIComponent(name)}/restore`,
        { method: 'POST' },
      )
      pushToast(`Restored snapshot ${name}`, 'success')
      await open(selected)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const runDiff = async () => {
    if (!selected) return
    try {
      const res = await apiJson(`/projects/${encodeURIComponent(selected)}/diff`, {
        query: { version_a: diffA, version_b: diffB },
      })
      setDiffResult(res)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const versionOptions = versions.map((v) =>
    typeof v === 'string' ? v : String((v as { version?: string }).version ?? JSON.stringify(v)),
  )

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-ink-200/70 bg-white/60 px-5 pt-5 pb-3">
        <PageHeader
          title="Projects"
          description="Workspace for Data outputs — versions, snapshots, lineage (not a second file browser). Browse files in Data."
          actions={
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn-secondary" onClick={() => openData({ mode: 'outputs' })}>
                Browse files
              </button>
              <button type="button" className="btn-secondary" onClick={() => void load()}>
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </button>
            </div>
          }
        />
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[320px_1fr]">
      <div className="overflow-y-auto border-r border-ink-200 p-3 space-y-2">
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        <div className="flex gap-2">
          <input
            ref={nameRef}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="new-project"
            className="flex-1 rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
            onKeyDown={(e) => e.key === 'Enter' && void create()}
          />
          <button type="button" className="btn-primary" onClick={() => void create()}>
            Create
          </button>
        </div>
        {loading || projects == null ? (
          <LoadingBlock />
        ) : projects.length === 0 ? (
          <EmptyState
            title="No dataset projects"
            description="Create a named workspace above, or upload/ingest files under Library → Data first."
            action={
              <button
                type="button"
                className="btn-secondary"
                onClick={() => openData({ mode: 'inputs' })}
              >
                Open Data
              </button>
            }
          />
        ) : (
          <ul className="space-y-2">
            {projects.map((p) => (
              <li key={p.name}>
                <button
                  type="button"
                  onClick={() => void open(p.name)}
                  className={`w-full rounded-xl border px-3 py-2 text-left ${
                    selected === p.name ? 'border-accent-400 bg-accent-50' : 'border-ink-200 bg-white'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{p.name}</span>
                    {p.status && <StatusBadge status={String(p.status)} />}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="overflow-y-auto p-4 space-y-4">
        {!selected ? (
          <div className="mx-auto max-w-md rounded-2xl border border-ink-200/80 bg-white px-6 py-8 shadow-sm">
            <h3 className="text-lg font-semibold text-ink-950">Select a dataset project</h3>
            <p className="mt-2 text-sm leading-relaxed text-ink-500">
              A project is the dataset workspace UI over the same{' '}
              <code className="font-mono text-[12px] text-ink-700">{'workspace/datasets/output/{project}'}</code>
              {' '}folder Data browses as files. Versions, snapshots, and lineage live here — not a second file browser.
            </p>
            <ol className="mt-4 list-decimal space-y-1.5 pl-5 text-sm text-ink-700">
              <li>Create a project with the name field on the left.</li>
              <li>Run a pipeline or merge datasets into that folder.</li>
              <li>Open the project to inspect versions, snapshots, and diffs.</li>
            </ol>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold">{selected}</h3>
                <p className="mt-1 text-xs text-ink-500">
                  Shared key with Data outputs: <code className="font-mono">{selected}</code>
                  {versionFocus ? <> / <code className="font-mono">{versionFocus}</code></> : null}
                </p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {STATUSES.map((s) => (
                    <button key={s} type="button" className="btn-secondary" onClick={() => void setStatus(s)}>
                      {s}
                    </button>
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => openData({ mode: 'outputs', project: selected, version: versionFocus || undefined })}
                  >
                    Browse files
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => void openInBuilder()}>
                    Open in Builder
                  </button>
                  <button type="button" className="btn-secondary" onClick={useInEdge}>
                    Use in Edge
                  </button>
                </div>
              </div>
              <ConfirmButton label="Delete project" confirmLabel={`Delete ${selected}?`} danger onConfirm={() => void remove()} />
            </div>

            <div className="flex flex-wrap gap-2 rounded-xl border border-ink-200 bg-white p-3">
              <input
                value={renameTo}
                onChange={(e) => setRenameTo(e.target.value)}
                className="rounded-lg border border-ink-200 px-2 py-1 text-sm"
                aria-label="Rename to"
              />
              <button type="button" className="btn-secondary" onClick={() => void rename()}>
                <Pencil className="h-3.5 w-3.5" /> Rename
              </button>
              <input
                value={cloneTo}
                onChange={(e) => setCloneTo(e.target.value)}
                className="rounded-lg border border-ink-200 px-2 py-1 text-sm"
                aria-label="Clone as"
              />
              <button type="button" className="btn-secondary" onClick={() => void clone()}>
                <Copy className="h-3.5 w-3.5" /> Clone
              </button>
            </div>

            <div className="flex flex-wrap gap-1">
              {(
                [
                  ['versions', 'Versions'],
                  ['spec', 'Spec'],
                  ['taxonomy', 'Taxonomy'],
                  ['contract', 'Contract'],
                  ['snapshots', 'Snapshots'],
                  ['diff', 'Diff / lineage'],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={tab === id ? 'btn-primary' : 'btn-secondary'}
                  onClick={() => setTab(id)}
                >
                  {label}
                </button>
              ))}
            </div>

            {tab === 'spec' && (
              <section className="space-y-2">
                <p className="text-sm text-ink-500">Markdown description of what this dataset is for. Saved as the project spec.</p>
                <textarea
                  value={spec}
                  onChange={(e) => setSpec(e.target.value)}
                  rows={16}
                  className="w-full rounded-xl border border-ink-200 p-3 font-mono text-sm"
                />
                <button type="button" className="btn-primary" onClick={() => void saveSpec()}>
                  Save spec
                </button>
              </section>
            )}

            {tab === 'taxonomy' && (
              <section className="space-y-2">
                <p className="text-sm text-ink-500">JSON list or map of labels/classes this dataset uses (the taxonomy).</p>
                <textarea
                  value={taxonomy}
                  onChange={(e) => setTaxonomy(e.target.value)}
                  rows={16}
                  className="w-full rounded-xl border border-ink-200 p-3 font-mono text-sm"
                />
                <button type="button" className="btn-primary" onClick={() => void saveTaxonomy()}>
                  Save taxonomy
                </button>
              </section>
            )}

            {tab === 'contract' && (
              <section className="space-y-2">
                <p className="text-sm text-ink-500">JSON schema/contract for records in this project (fields, types, required keys).</p>
                <textarea
                  value={contract}
                  onChange={(e) => setContract(e.target.value)}
                  rows={16}
                  className="w-full rounded-xl border border-ink-200 p-3 font-mono text-sm"
                />
                <button type="button" className="btn-primary" onClick={() => void saveContract()}>
                  Save contract
                </button>
              </section>
            )}

            {tab === 'versions' && (
              <section className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <select
                    value={versionFocus}
                    onChange={(e) => setVersionFocus(e.target.value)}
                    className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
                  >
                    {versionOptions.map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="btn-secondary" onClick={() => void loadVersionDetail()}>
                    Load stats / samples
                  </button>
                  <ConfirmButton
                    label="Restore version"
                    confirmLabel={`Restore ${versionFocus}?`}
                    onConfirm={() => void restoreVersion()}
                  />
                </div>
                <KeyValue data={versions} empty="No versions." />
                {versionStats != null && <KeyValue data={versionStats} />}
                {versionSamples != null && <CollapsibleJson value={versionSamples} label="Samples" />}
              </section>
            )}

            {tab === 'snapshots' && (
              <section className="space-y-3">
                <div className="flex gap-2">
                  <input
                    id="snapshot-name"
                    value={snapshotName}
                    onChange={(e) => setSnapshotName(e.target.value)}
                    placeholder="snapshot-name"
                    className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
                  />
                  <button type="button" className="btn-primary" onClick={() => void createSnapshot()}>
                    Create snapshot
                  </button>
                </div>
                {snapshots.length === 0 ? (
                  <EmptyState
                    title="No snapshots"
                    description="Create a named snapshot to restore this project later."
                    action={
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => document.getElementById('snapshot-name')?.focus()}
                      >
                        Name a snapshot
                      </button>
                    }
                  />
                ) : (
                  <ul className="space-y-2">
                    {snapshots.map((s, i) => {
                      const name =
                        typeof s === 'string'
                          ? s
                          : String((s as { name?: string }).name ?? `snapshot-${i}`)
                      return (
                        <li
                          key={name}
                          className="flex items-center justify-between rounded-xl border border-ink-200 bg-white px-3 py-2"
                        >
                          <span className="font-mono text-sm">{name}</span>
                          <ConfirmButton
                            label="Restore"
                            confirmLabel={`Restore ${name}?`}
                            onConfirm={() => void restoreSnapshot(name)}
                          />
                        </li>
                      )
                    })}
                  </ul>
                )}
              </section>
            )}

            {tab === 'diff' && (
              <section className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <select
                    value={diffA}
                    onChange={(e) => setDiffA(e.target.value)}
                    className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
                  >
                    {versionOptions.map((v) => (
                      <option key={`a-${v}`} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                  <span className="self-center text-sm text-ink-500">vs</span>
                  <select
                    value={diffB}
                    onChange={(e) => setDiffB(e.target.value)}
                    className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
                  >
                    {versionOptions.map((v) => (
                      <option key={`b-${v}`} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="btn-primary" onClick={() => void runDiff()}>
                    Diff
                  </button>
                </div>
                {diffResult != null && <KeyValue data={diffResult} />}
                <h4 className="text-sm font-semibold">Lineage</h4>
                {(() => {
                  const ids = lineageIds(lineage)
                  if (!ids.runId && !ids.artifactId) return null
                  return (
                    <div className="flex flex-wrap gap-2">
                      {ids.runId ? (
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => openTrace({ runId: ids.runId })}
                        >
                          Open Trace
                        </button>
                      ) : null}
                      {ids.artifactId || ids.runId ? (
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() =>
                            openArtifacts({
                              runId: ids.runId,
                              artifactId: ids.artifactId,
                            })
                          }
                        >
                          Open Artifacts
                        </button>
                      ) : null}
                    </div>
                  )
                })()}
                <KeyValue data={lineage} empty="No lineage." />
              </section>
            )}
          </>
        )}
      </div>
      </div>
    </div>
  )
}
