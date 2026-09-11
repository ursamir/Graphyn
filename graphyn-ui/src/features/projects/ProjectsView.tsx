import React from 'react'
import { RefreshCw, Copy, Pencil } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import type { GraphIR } from '../../types/graph'
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

/** API ProjectManager.set_status enum (never 'active'). */
const STATUSES = ['draft', 'in-progress', 'ready', 'archived'] as const
type ProjectStatus = (typeof STATUSES)[number]

/** Map legacy stored 'active' → 'in-progress' for display / select value. */
function normalizeProjectStatus(raw: unknown): ProjectStatus {
  const s = String(raw ?? 'draft').trim().toLowerCase()
  if (s === 'active') return 'in-progress'
  if ((STATUSES as readonly string[]).includes(s)) return s as ProjectStatus
  return 'draft'
}


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
  const openEdge = useAppStore((s) => s.openEdge)
  const setView = useAppStore((s) => s.setView)
  const setActiveProject = useAppStore((s) => s.setActiveProject)
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
  const [recentRuns, setRecentRuns] = React.useState<Array<{ run_id: string; status?: string; graph_name?: string; created_at?: string; project?: string }>>([])
  const [projectPipelines, setProjectPipelines] = React.useState<
    Array<{
      name: string
      updated_at?: string | null
      node_count?: number
      graph_name?: string | null
      version_count?: number
      latest_version?: string | null
      environments?: {
        draft?: string | null
        staging?: string | null
        prod?: string | null
        pending_prod?: { version?: string } | null
      }
    }>
  >([])
  const [links, setLinks] = React.useState<{ inputs: string[]; outputs: Array<{ version: string }> }>({ inputs: [], outputs: [] })
  const [inputLabels, setInputLabels] = React.useState<string[]>([])
  const [linkPick, setLinkPick] = React.useState('')

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
    setActiveProject(name)
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
      try {
        const [runs, linkData, inputs, pipes] = await Promise.all([
          apiJson<Array<{ run_id: string; status?: string; graph_name?: string; created_at?: string; project?: string }>>('/runs', {
            query: { limit: 8, offset: 0, project: name },
          }),
          apiJson<{ inputs?: string[]; outputs?: Array<{ version: string }> }>(`/projects/${encodeURIComponent(name)}/links`).catch(() => ({ inputs: [], outputs: [] })),
          apiJson<Array<{ label?: string } | string>>('/data/inputs').catch(() => []),
          apiJson<
            Array<{
              name: string
              updated_at?: string | null
              node_count?: number
              graph_name?: string | null
              version_count?: number
              latest_version?: string | null
              environments?: {
                draft?: string | null
                staging?: string | null
                prod?: string | null
                pending_prod?: { version?: string } | null
              }
            }>
          >(`/projects/${encodeURIComponent(name)}/pipelines`).catch(() => []),
        ])
        setRecentRuns(Array.isArray(runs) ? runs.slice(0, 8) : [])
        setProjectPipelines(Array.isArray(pipes) ? pipes : [])
        setLinks({
          inputs: Array.isArray(linkData?.inputs) ? linkData.inputs : [],
          outputs: Array.isArray(linkData?.outputs) ? linkData.outputs : [],
        })
        const labels = (Array.isArray(inputs) ? inputs : [])
          .map((x) => (typeof x === 'string' ? x : String(x?.label ?? '')))
          .filter(Boolean)
        setInputLabels(labels)
        setLinkPick(labels.find((l) => !(linkData?.inputs || []).includes(l)) || labels[0] || '')
      } catch {
        setRecentRuns([])
        setProjectPipelines([])
        setLinks({ inputs: [], outputs: [] })
      }
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

  const useInEdge = () => {
    openEdge({
      project: selected || undefined,
      version: versionFocus || undefined,
      runId: recentRuns[0]?.run_id || undefined,
    })
  }

  const openProjectPipeline = async (pipelineName: string, env?: string) => {
    if (!selected) return
    try {
      const graph = await apiJson<GraphIR>(
        `/projects/${encodeURIComponent(selected)}/pipelines/${encodeURIComponent(pipelineName)}`,
        env ? { query: { env } } : undefined,
      )
      useAppStore.getState().loadGraphIntoBuilder(graph)
      pushToast(`Opened ${pipelineName}${env ? ` (${env})` : ''} in Editor`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const publishPipeline = async (pipelineName: string, setEnv?: 'staging' | 'prod') => {
    if (!selected) return
    try {
      const res = await apiJson<{ version?: string; status?: string }>(
        `/projects/${encodeURIComponent(selected)}/pipelines/${encodeURIComponent(pipelineName)}/publish`,
        {
          method: 'POST',
          body: JSON.stringify({
            message: 'Published from Projects',
            set_env: setEnv,
          }),
        },
      )
      pushToast(
        setEnv === 'prod'
          ? `Published ${res.version} — prod pending approval`
          : `Published ${res.version}${setEnv ? ` → ${setEnv}` : ''}`,
        'success',
      )
      await open(selected)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const promotePipeline = async (
    pipelineName: string,
    opts: { to_env: 'staging' | 'prod'; from_env?: string; version?: string; approve?: boolean },
  ) => {
    if (!selected) return
    try {
      const res = await apiJson<{ status?: string; version?: string }>(
        `/projects/${encodeURIComponent(selected)}/pipelines/${encodeURIComponent(pipelineName)}/promote`,
        {
          method: 'POST',
          body: JSON.stringify(opts),
        },
      )
      pushToast(
        res.status === 'pending_approval'
          ? `Prod promotion pending approval (${res.version || opts.version || ''})`
          : `Promoted to ${opts.to_env}`,
        'success',
      )
      await open(selected)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const create = async () => {
    if (!newName.trim()) {
      pushToast('Enter a project name first', 'error')
      nameRef.current?.focus()
      return
    }
    try {
      const created = newName.trim()
      await apiJson('/projects', { method: 'POST', body: JSON.stringify({ name: created }) })
      pushToast(`Created ${created}`, 'success')
      setActiveProject(created)
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

  const linkInput = async () => {
    if (!selected || !linkPick.trim()) return
    try {
      const next = await apiJson<{ inputs: string[]; outputs: Array<{ version: string }> }>(
        `/projects/${encodeURIComponent(selected)}/links`,
        { method: 'POST', body: JSON.stringify({ inputs: [linkPick.trim()] }) },
      )
      setLinks({ inputs: next.inputs ?? [], outputs: next.outputs ?? [] })
      pushToast(`Linked input "${linkPick.trim()}"`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const unlinkInput = async (label: string) => {
    if (!selected) return
    try {
      const next = await apiJson<{ inputs: string[]; outputs: Array<{ version: string }> }>(
        `/projects/${encodeURIComponent(selected)}/links`,
        { method: 'DELETE', body: JSON.stringify({ inputs: [label] }) },
      )
      setLinks({ inputs: next.inputs ?? [], outputs: next.outputs ?? [] })
      pushToast(`Unlinked "${label}"`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const versionOptions = versions.map((v) =>
    typeof v === 'string' ? v : String((v as { version?: string }).version ?? JSON.stringify(v)),
  )

  return (
    <div className="flex h-full flex-col">
      <div className="page-shell-header">
        <PageHeader
          title={selected ? 'Workspace' : 'Workspaces'}
          scope={selected ? 'project' : 'global'}
          description={
            selected
              ? `Scoped to ${selected} — linked data, pipelines, runs, and experiments (like an opened IDE folder).`
              : 'Open a workspace to edit pipelines, run, and explore linked data. Global Data library stays available anytime.'
          }
          actions={
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn-secondary" onClick={() => openData({ mode: 'outputs' })}>
                Browse library
              </button>
              <button type="button" className="btn-secondary" onClick={() => void load()}>
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </button>
            </div>
          }
        />
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[240px_1fr]">
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
            title="No projects yet"
            description="Create a workspace above, then open Templates (stamps the project) or link data under Data so versions appear under output/{project}."
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
                  className={`w-full rounded-xl border px-3 py-2.5 text-left transition ${
                    selected === p.name ? 'border-accent-300/80 bg-accent-50/80 shadow-sm' : 'border-ink-200/70 bg-white hover:border-ink-300 hover:bg-ink-50/40'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{p.name}</span>
                    {p.status && <StatusBadge status={normalizeProjectStatus(p.status)} />}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="overflow-y-auto p-4 space-y-4">
        {!selected ? (
          <div className="mx-auto max-w-lg rounded-2xl border border-ink-200/50 bg-gradient-to-b from-white to-[#f7f9fb] px-8 py-10 shadow-sm">
            <h3 className="text-lg font-semibold tracking-tight text-ink-950">Open or create a project to start work</h3>
            <p className="mt-2.5 text-sm leading-relaxed text-ink-500">
              Like opening a folder in an IDE — a project is the workspace for pipelines (Editor), runs, experiments, and linked data under{' '}
              <code className="font-mono text-[12px] text-ink-700">{'workspace/datasets/output/{project}'}</code>.
            </p>
            <ol className="mt-4 list-decimal space-y-1.5 pl-5 text-sm text-ink-700">
              <li>Create or open a workspace (header shows Project · name).</li>
              <li>Use From template (or the Editor sidebar) to stamp pipelines.</li>
              <li>Link data from the library, run from the Editor, then review in Run / Experiments.</li>
            </ol>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-xl font-semibold tracking-tight text-ink-950">{selected}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-ink-500">
                  Opened workspace · key <code className="font-mono">{selected}</code>
                  {versionFocus ? <> / <code className="font-mono">{versionFocus}</code></> : null}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-1.5 text-xs text-ink-500">
                    Status
                    <select
                      className="rounded-lg border border-ink-200 bg-white px-2 py-1 text-sm text-ink-800"
                      value={normalizeProjectStatus(projects?.find((p) => p.name === selected)?.status)}
                      onChange={(e) => void setStatus(e.target.value)}
                      aria-label="Project status"
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
            </div>

            <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
              <div className="editorial-card border-accent-200/40 sm:col-span-2 xl:col-span-2">
                <div className="text-[11px] font-medium uppercase tracking-wide text-ink-400">Linked data</div>
                <div className="mt-1 text-sm font-semibold text-ink-900">
                  {links.inputs.length} input{links.inputs.length === 1 ? '' : 's'} · {versionOptions.length} version{versionOptions.length === 1 ? '' : 's'}
                </div>
                <p className="mt-1 text-xs text-ink-500">
                  Explorer — link labels from the global library into this workspace.
                </p>
                <div className="mt-2 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      className="rounded-lg border border-ink-200 bg-white px-2 py-1 text-sm"
                      value={linkPick}
                      onChange={(e) => setLinkPick(e.target.value)}
                      aria-label="Link input label from Data"
                    >
                      <option value="">Select input label…</option>
                      {inputLabels.map((label) => (
                        <option key={label} value={label} disabled={links.inputs.includes(label)}>
                          {label}{links.inputs.includes(label) ? ' (already linked)' : ''}
                        </option>
                      ))}
                    </select>
                    <ConfirmButton
                      label={linkPick ? `Link “${linkPick}”` : 'Link from library'}
                      confirmLabel={linkPick ? `Confirm link “${linkPick}”?` : 'Confirm link'}
                      onConfirm={() => void linkInput()}
                      disabled={!linkPick || links.inputs.includes(linkPick)}
                    />
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => openData({ mode: 'outputs', project: selected, version: versionFocus || undefined })}
                    >
                      Browse
                    </button>
                  </div>
                  {linkPick ? (
                    <p className="text-[11px] text-ink-500">
                      Selected to link:{' '}
                      <span className="font-semibold text-ink-800">{linkPick}</span>
                      {links.inputs.includes(linkPick) ? (
                        <span className="text-amber-800"> · already linked</span>
                      ) : links.inputs.length > 0 ? (
                        <span>
                          {' '}
                          · currently linked:{' '}
                          <span className="font-medium text-ink-700">{links.inputs.join(', ')}</span>
                        </span>
                      ) : (
                        <span> · none linked yet</span>
                      )}
                    </p>
                  ) : links.inputs.length > 0 ? (
                    <p className="text-[11px] text-ink-500">
                      Currently linked:{' '}
                      <span className="font-medium text-ink-700">{links.inputs.join(', ')}</span>
                    </p>
                  ) : null}
                </div>
                {links.inputs.length > 0 && (
                  <ul className="mt-2 flex flex-wrap gap-1.5">
                    {links.inputs.map((label) => (
                      <li key={label} className="inline-flex items-center gap-1 rounded-full border border-accent-200 bg-accent-50 px-2 py-0.5 text-xs text-accent-950">
                        <span className="font-medium">{label}</span>
                        <span className="text-[10px] text-accent-700/80">linked</span>
                        <button type="button" className="text-ink-400 hover:text-danger-600" onClick={() => void unlinkInput(label)} aria-label={`Unlink ${label}`}>
                          ×
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="editorial-card">
                <div className="text-[11px] font-medium uppercase tracking-wide text-ink-400">Pipelines</div>
                <div className="mt-1 text-sm font-semibold text-ink-900">
                  {projectPipelines.length === 0 ? 'None yet' : `${projectPipelines.length} saved`}
                </div>
                <p className="mt-1 text-xs leading-relaxed text-ink-500">
                  Draft head in Editor; publish versions to staging, approve for prod.
                </p>
                {projectPipelines.length > 0 ? (
                  <ul className="mt-2 space-y-2">
                    {projectPipelines.slice(0, 6).map((p) => {
                      const envs = p.environments || {}
                      return (
                        <li key={p.name} className="rounded-lg border border-ink-100 px-2 py-1.5">
                          <button
                            type="button"
                            className="text-left text-xs font-medium text-accent-800 hover:underline"
                            onClick={() => void openProjectPipeline(p.name)}
                          >
                            {p.name}
                            {p.node_count != null ? ` · ${p.node_count} nodes` : ''}
                            {p.latest_version ? ` · ${p.latest_version}` : ''}
                          </button>
                          <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-ink-500">
                            <span className="rounded bg-ink-50 px-1.5 py-0.5">draft</span>
                            {envs.staging ? (
                              <button
                                type="button"
                                className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-900 hover:underline"
                                onClick={() => void openProjectPipeline(p.name, 'staging')}
                              >
                                staging:{envs.staging}
                              </button>
                            ) : (
                              <span className="rounded bg-ink-50 px-1.5 py-0.5">staging:—</span>
                            )}
                            {envs.prod ? (
                              <button
                                type="button"
                                className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-900 hover:underline"
                                onClick={() => void openProjectPipeline(p.name, 'prod')}
                              >
                                prod:{envs.prod}
                              </button>
                            ) : (
                              <span className="rounded bg-ink-50 px-1.5 py-0.5">prod:—</span>
                            )}
                            {envs.pending_prod?.version ? (
                              <span className="rounded bg-rose-50 px-1.5 py-0.5 text-rose-800">
                                pending {envs.pending_prod.version}
                              </span>
                            ) : null}
                          </div>
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            <button
                              type="button"
                              className="btn-secondary !px-2 !py-0.5 text-[10px]"
                              onClick={() => void publishPipeline(p.name, 'staging')}
                            >
                              Publish → staging
                            </button>
                            {envs.staging ? (
                              <button
                                type="button"
                                className="btn-secondary !px-2 !py-0.5 text-[10px]"
                                onClick={() =>
                                  void promotePipeline(p.name, {
                                    to_env: 'prod',
                                    from_env: 'staging',
                                    approve: false,
                                  })
                                }
                              >
                                Request prod
                              </button>
                            ) : null}
                            {envs.pending_prod?.version ? (
                              <button
                                type="button"
                                className="btn-primary !px-2 !py-0.5 text-[10px]"
                                onClick={() =>
                                  void promotePipeline(p.name, {
                                    to_env: 'prod',
                                    version: envs.pending_prod?.version,
                                    approve: true,
                                  })
                                }
                              >
                                Approve prod
                              </button>
                            ) : null}
                          </div>
                        </li>
                      )
                    })}
                  </ul>
                ) : null}
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => {
                      setView('templates')
                      window.history.replaceState(null, '', '#/templates')
                    }}
                  >
                    From template
                  </button>
                </div>
              </div>
              <div className="editorial-card">
                <div className="text-[11px] font-medium uppercase tracking-wide text-ink-400">Recent runs</div>
                <div className="mt-1 text-sm font-semibold text-ink-900">
                  {recentRuns.length === 0 ? 'None yet' : `${recentRuns.length} matched`}
                </div>
                <p className="mt-1 text-xs leading-relaxed text-ink-500">
                  {recentRuns.length === 0
                    ? 'Stamp a template, then run from the Editor. The Run sidebar lists all workspace runs.'
                    : 'Latest matches for this workspace — open one below.'}
                </p>
                {recentRuns.length === 0 ? (
                  <div className="mt-2">
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => {
                        setView('templates')
                        window.history.replaceState(null, '', '#/templates')
                      }}
                    >
                      From template
                    </button>
                  </div>
                ) : (
                  <ul className="mt-2 space-y-1">
                    {recentRuns.slice(0, 4).map((r) => (
                      <li key={r.run_id}>
                        <button
                          type="button"
                          className="text-left text-xs text-accent-800 hover:underline"
                          onClick={() => useAppStore.getState().openRun(r.run_id)}
                        >
                          {r.run_id.slice(0, 8)}… {r.status || ''} {r.graph_name ? `· ${r.graph_name}` : ''}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="editorial-card bg-[#fafbfc]">
                <div className="text-[11px] font-medium uppercase tracking-wide text-ink-400">Experiments</div>
                <div className="mt-1 text-sm font-semibold text-ink-900">Compare quietly</div>
                <p className="mt-1 text-xs leading-relaxed text-ink-500">
                  Diff params and metrics across runs from the Experiments sidebar — no extra hop from here.
                </p>
              </div>
            </div>

            <details className="rounded-xl border border-ink-200 bg-white">
              <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-ink-600 hover:text-ink-900">
                Project settings
              </summary>
              <div className="flex flex-wrap items-center gap-2 border-t border-ink-100 px-3 py-3">
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
                <button type="button" className="btn-secondary" onClick={useInEdge}>
                  Use in Edge
                </button>
                <ConfirmButton label="Delete project" confirmLabel={`Delete ${selected}?`} danger onConfirm={() => void remove()} />
              </div>
            </details>

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
                  placeholder={"# Project spec\n\nDescribe goals, labels, and quality bar…"}
                  className="w-full rounded-xl border border-ink-200 p-3 font-mono text-sm"
                />
                <button type="button" className="btn-primary" onClick={() => void saveSpec()}>
                  Save spec
                </button>
              </section>
            )}

            {tab === 'taxonomy' && (
              <section className="space-y-2">
                <p className="text-sm text-ink-500">JSON list of labels/classes (starter: one unlabeled node). Edit and save when ready.</p>
                <textarea
                  value={taxonomy}
                  onChange={(e) => setTaxonomy(e.target.value)}
                  rows={16}
                  placeholder={'[\n  { "name": "unlabeled", "children": [] }\n]'}
                  className="w-full rounded-xl border border-ink-200 p-3 font-mono text-sm"
                />
                <button type="button" className="btn-primary" onClick={() => void saveTaxonomy()}>
                  Save taxonomy
                </button>
              </section>
            )}

            {tab === 'contract' && (
              <section className="space-y-2">
                <p className="text-sm text-ink-500">JSON data contract (duration bounds, sample rate, required fields). Empty object is fine until you need gates.</p>
                <textarea
                  value={contract}
                  onChange={(e) => setContract(e.target.value)}
                  rows={16}
                  placeholder={'{\n  "_hint": "Optional data contract",\n  "required_fields": ["path", "label", "split"]\n}'}
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
                {versions.length === 0 ? (
                  <EmptyState
                    title="No versions yet"
                    description="Versions appear after a pipeline writes under workspace/datasets/output/{project}/{version}. Stamp a template, then run from the Editor sidebar."
                    action={
                      <button type="button" className="btn-primary" onClick={() => setView('templates')}>
                        From template
                      </button>
                    }
                  />
                ) : (
                  <KeyValue data={versions} />
                )}
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
                          : String(
                              (s as { snapshot_name?: string; name?: string }).snapshot_name ??
                                (s as { name?: string }).name ??
                                `snapshot-${i}`,
                            )
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
