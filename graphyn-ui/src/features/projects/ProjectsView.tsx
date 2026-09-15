import React from 'react'
import { RefreshCw, Copy, Pencil, Workflow, History, ChevronRight, CalendarClock, Play } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import type { GraphIR } from '../../types/graph'
import {
  ConfirmButton,
  CollapsibleJson,
  ErrorBanner,
  KeyValue,
  LoadingBlock,
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
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
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
  const [schedules, setSchedules] = React.useState<
    Array<{
      id?: string
      name?: string
      project?: string
      pipeline?: string
      interval_minutes?: number
      enabled?: boolean
      next_run_at?: string
      last_run_id?: string
      last_error?: string
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
      // Prefer replaceHash path in store for navigation; here we own selected state.
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
        const [runs, linkData, inputs, pipes, sched] = await Promise.all([
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
          apiJson<{ schedules?: unknown[] }>('/system/schedules').catch(() => ({ schedules: [] })),
        ])
        setRecentRuns(Array.isArray(runs) ? runs.slice(0, 8) : [])
        setProjectPipelines(Array.isArray(pipes) ? pipes : [])
        {
          const schedList = Array.isArray(sched?.schedules) ? sched.schedules : []
          const typed = schedList.filter((e): e is Record<string, unknown> => !!e && typeof e === 'object') as Array<{
            id?: string
            name?: string
            project?: string
            pipeline?: string
            interval_minutes?: number
            enabled?: boolean
            next_run_at?: string
            last_run_id?: string
            last_error?: string
          }>
          const forProject = typed.filter((s) => String(s.project || '') === name)
          setSchedules(forProject.length ? forProject : typed)
        }
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
        setSchedules([])
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
      if (h.tab) {
        setTab(h.tab)
        setDatasetOpen(true)
      }
      setSelected((cur) => {
        if (h.project) {
          if (h.project !== cur) {
            // Defer open so we do not nest setState updates incorrectly
            queueMicrotask(() => void open(h.project!))
          }
          return cur
        }
        return null
      })
    }
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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

  const runSchedule = async (id: string) => {
    try {
      const res = await apiJson<{ last_run_id?: string }>(`/system/schedules/${encodeURIComponent(id)}/run`, {
        method: 'POST',
      })
      pushToast(res?.last_run_id ? `Started ${res.last_run_id.slice(0, 10)}…` : 'Schedule fired', 'success')
      if (selected) await open(selected)
      if (res?.last_run_id) useAppStore.getState().openRun(res.last_run_id)
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
      await open(created)
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

  const [datasetOpen, setDatasetOpen] = React.useState(() => Boolean(initialHash.tab))
  const [projectFilter, setProjectFilter] = React.useState('')

  const versionOptions = versions.map((v) =>
    typeof v === 'string' ? v : String((v as { version?: string }).version ?? JSON.stringify(v)),
  )

  const filteredProjects = React.useMemo(() => {
    const q = projectFilter.trim().toLowerCase()
    if (!projects) return []
    if (!q) return projects
    return projects.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        String(p.status || '')
          .toLowerCase()
          .includes(q),
    )
  }, [projects, projectFilter])

  const authBlocked = /unauthorized|401|api token/i.test(error || '')
  const goEditor = () => {
    setView('builder')
    window.history.replaceState(null, '', '#/builder')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  }
  const goTemplates = () => {
    setView('templates')
    window.history.replaceState(null, '', '#/templates')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  }
  const openLastRun = () => {
    const id = recentRuns[0]?.run_id
    if (id) useAppStore.getState().openRun(id)
  }

  /* ── Picker: single explorer + welcome (no workspace chrome) ── */
  if (!selected) {
    return (
      <div className="flex h-full min-h-0">
        <aside className="flex w-[15.5rem] shrink-0 flex-col border-r border-ink-200/80 bg-[#f7f7f8]">
          <div className="border-b border-ink-200/60 px-3 py-2.5 space-y-2">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Projects</div>
            <div className="flex gap-1.5">
              <input
                ref={nameRef}
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="New project…"
                className="min-w-0 flex-1 rounded-md border border-ink-200 bg-white px-2 py-1 text-[12px]"
                onKeyDown={(e) => e.key === 'Enter' && void create()}
              />
              <button type="button" className="btn-primary !px-2 !py-1 text-[11px]" onClick={() => void create()}>
                New
              </button>
            </div>
            <input
              value={projectFilter}
              onChange={(e) => setProjectFilter(e.target.value)}
              placeholder="Filter…"
              aria-label="Filter projects"
              className="w-full rounded-md border border-ink-200 bg-white px-2 py-1 text-[12px]"
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-1.5">
            {error && (
              <div className="mb-2 px-1">
                <ErrorBanner
                  message={error}
                  onRetry={() => void load()}
                  actions={
                    authBlocked ? (
                      <button type="button" className="btn-primary" onClick={() => setSettingsOpen(true)}>
                        Settings
                      </button>
                    ) : undefined
                  }
                />
              </div>
            )}
            {loading || projects == null ? (
              <LoadingBlock label="Loading…" />
            ) : projects.length === 0 ? (
              <p className="px-2 py-4 text-[12px] text-ink-500">
                {authBlocked ? 'Sign in via Settings to list projects.' : 'No projects yet — create one above.'}
              </p>
            ) : filteredProjects.length === 0 ? (
              <p className="px-2 py-4 text-[12px] text-ink-500">No matches for “{projectFilter.trim()}”.</p>
            ) : (
              <ul className="space-y-0.5">
                {filteredProjects.map((p) => (
                  <li key={p.name}>
                    <button type="button" onClick={() => void open(p.name)} className="ide-row w-full">
                      <span className="min-w-0 flex-1 truncate font-medium text-ink-900">{p.name}</span>
                      <span className="shrink-0 text-[10px] uppercase tracking-wide text-ink-400">
                        {normalizeProjectStatus(p.status)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="border-t border-ink-200/60 p-2">
            <button type="button" className="ide-quiet-btn w-full justify-center" onClick={() => void load()}>
              <RefreshCw className="h-3 w-3" /> Refresh
            </button>
          </div>
        </aside>
        <main className="flex min-w-0 flex-1 flex-col items-center justify-center px-8">
          <div className="max-w-md text-center">
            <h1 className="text-type-page text-ink-950">Open a workspace</h1>
            <p className="mt-2 text-type-body text-ink-500">
              Pick a project on the left. Editor, Run, and Compare appear in the activity bar once a workspace is open.
            </p>
            <ol className="mt-6 space-y-2 text-left text-[13px] text-ink-600">
              <li className="flex gap-2"><span className="font-mono text-ink-400">1</span> Open or create a project</li>
              <li className="flex gap-2"><span className="font-mono text-ink-400">2</span> Stamp a template or build in Editor</li>
              <li className="flex gap-2"><span className="font-mono text-ink-400">3</span> Run, then review lineage from the run</li>
            </ol>
            <button type="button" className="btn-secondary mt-6" onClick={() => openData({ mode: 'outputs' })}>
              Browse data library
            </button>
          </div>
        </main>
      </div>
    )
  }

  /* ── Workspace home: full pane (no second project list) ── */
  const statusVal = normalizeProjectStatus(projects?.find((p) => p.name === selected)?.status)
  const lastRun = recentRuns[0]
  const stagingHint = projectPipelines.find((p) => p.environments?.staging)?.environments?.staging
  const prodHint = projectPipelines.find((p) => p.environments?.prod)?.environments?.prod

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-ink-200/60 bg-white/80 px-6 py-4 backdrop-blur-md">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-type-page text-ink-950">{selected}</h1>
            <p className="mt-0.5 text-type-meta text-ink-400">
              Workspace · {statusVal}
              {versionFocus ? ` · ${versionFocus}` : ''}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="btn-primary" onClick={goEditor}>
              <Workflow className="h-3.5 w-3.5" /> Open Editor
            </button>
            <button type="button" className="btn-secondary" onClick={goTemplates}>
              From template
            </button>
            {lastRun ? (
              <button type="button" className="btn-secondary" onClick={openLastRun}>
                <History className="h-3.5 w-3.5" /> Last run
              </button>
            ) : null}
            <button type="button" className="btn-icon" aria-label="Refresh" onClick={() => void open(selected)}>
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        </div>
        {/* L0 — compact metrics (status already in subtitle) */}
        <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-600">
          <div className="flex gap-1.5">
            <dt className="text-ink-400">Pipelines</dt>
            <dd className="font-medium text-ink-800">{projectPipelines.length}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="text-ink-400">Pinned inputs</dt>
            <dd className="font-medium text-ink-800">{links.inputs.length}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="text-ink-400">Last run</dt>
            <dd>
              {lastRun ? (
                <button type="button" className="font-medium text-accent-800 hover:underline" onClick={openLastRun}>
                  {lastRun.status || 'unknown'} · {lastRun.run_id.slice(0, 8)}…
                </button>
              ) : (
                <span className="text-ink-400">—</span>
              )}
            </dd>
          </div>
          {(stagingHint || prodHint) && (
            <div className="flex gap-1.5">
              <dt className="text-ink-400">Envs</dt>
              <dd className="font-medium text-ink-800">
                {stagingHint ? `staging ${stagingHint}` : null}
                {stagingHint && prodHint ? ' · ' : null}
                {prodHint ? `prod ${prodHint}` : null}
              </dd>
            </div>
          )}
        </dl>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-3xl space-y-6">
          {error && <ErrorBanner message={error} onRetry={() => void open(selected)} />}

          <p className="text-[12px] text-ink-500">
            <span className="font-medium text-ink-700">Pipelines:</span> Templates are starters · Project pipelines are the canonical saved graphs · Editor edits the active graph.
          </p>

          {/* Activity feed */}
          <section>
            <div className="ide-section-title mb-2">Activity</div>
            <div className="overflow-hidden rounded-xl border border-ink-200/70 bg-white">
              {recentRuns.length === 0 && !schedules.some((s) => s.last_run_id) ? (
                <div className="px-4 py-5 text-[13px] text-ink-600">
                  No activity yet — run a pipeline from the Editor.
                </div>
              ) : (
                <ul className="divide-y divide-ink-100">
                  {recentRuns.slice(0, 8).map((r) => (
                    <li key={r.run_id}>
                      <button
                        type="button"
                        className="ide-row w-full px-3"
                        onClick={() => useAppStore.getState().openRun(r.run_id)}
                      >
                        <History className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                        <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink-700">
                          {r.run_id.slice(0, 10)}…
                          {r.graph_name ? ` · ${r.graph_name}` : ''}
                        </span>
                        <span className="text-[11px] text-ink-400">{r.status || ''}</span>
                      </button>
                    </li>
                  ))}
                  {schedules
                    .filter((s) => s.last_run_id)
                    .slice(0, 3)
                    .map((s) => (
                      <li key={`sched-fire-${s.id}-${s.last_run_id}`}>
                        <button
                          type="button"
                          className="ide-row w-full px-3"
                          onClick={() => s.last_run_id && useAppStore.getState().openRun(String(s.last_run_id))}
                        >
                          <CalendarClock className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                          <span className="min-w-0 flex-1 truncate text-[12px] text-ink-700">
                            Schedule {s.name || s.id} · last {String(s.last_run_id).slice(0, 8)}…
                          </span>
                          <span className="text-[11px] text-ink-400">{s.pipeline || ''}</span>
                        </button>
                      </li>
                    ))}
                </ul>
              )}
            </div>
          </section>

          {/* Layer 1 — continue work */}
          <section>
            <div className="ide-section-title mb-2">Continue</div>
            <div className="overflow-hidden rounded-xl border border-ink-200/70 bg-white">
              {projectPipelines.length === 0 && recentRuns.length === 0 ? (
                <div className="px-4 py-5 text-[13px] text-ink-600">
                  No pipelines yet.{' '}
                  <button type="button" className="font-medium text-accent-800 hover:underline" onClick={goTemplates}>
                    Start from a template
                  </button>{' '}
                  or open the Editor and save a graph.
                </div>
              ) : (
                <ul className="divide-y divide-ink-100">
                  {projectPipelines.slice(0, 5).map((p) => {
                    const envs = p.environments || {}
                    return (
                      <li key={p.name} className="px-3 py-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            className="min-w-0 flex-1 truncate text-left text-[13px] font-medium text-ink-900 hover:text-accent-800"
                            onClick={() => void openProjectPipeline(p.name)}
                          >
                            {p.name}
                            <span className="ml-2 font-normal text-ink-400">
                              {p.node_count != null ? `${p.node_count} nodes` : 'pipeline'}
                              {p.latest_version ? ` · ${p.latest_version}` : ''}
                            </span>
                          </button>
                          <ChevronRight className="h-3.5 w-3.5 text-ink-300" />
                        </div>
                        {(envs.staging || envs.prod || envs.pending_prod) && (
                          <details className="mt-1">
                            <summary className="cursor-pointer text-[11px] text-ink-400 hover:text-ink-700">
                              Environments & promote
                            </summary>
                            <div className="mt-1.5 flex flex-wrap gap-1.5 pb-1">
                              <button type="button" className="btn-secondary !px-2 !py-0.5 text-[10px]" onClick={() => void publishPipeline(p.name, 'staging')}>
                                Publish → staging
                              </button>
                              {envs.staging ? (
                                <button
                                  type="button"
                                  className="btn-secondary !px-2 !py-0.5 text-[10px]"
                                  onClick={() => void promotePipeline(p.name, { to_env: 'prod', from_env: 'staging', approve: false })}
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
                              {envs.staging ? (
                                <button type="button" className="ide-quiet-btn text-[10px]" onClick={() => void openProjectPipeline(p.name, 'staging')}>
                                  Open staging
                                </button>
                              ) : null}
                              {envs.prod ? (
                                <button type="button" className="ide-quiet-btn text-[10px]" onClick={() => void openProjectPipeline(p.name, 'prod')}>
                                  Open prod
                                </button>
                              ) : null}
                            </div>
                          </details>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </section>

          {/* Schedules (project-scoped when possible) */}
          <section className="ide-section">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="ide-section-title">Schedules</div>
              <button
                type="button"
                className="ide-quiet-btn text-[11px]"
                onClick={() => {
                  setView('system')
                  window.history.replaceState(null, '', '#/system')
                }}
              >
                Manage in System
              </button>
            </div>
            <div className="overflow-hidden rounded-xl border border-ink-200/70 bg-white">
              {schedules.length === 0 ? (
                <div className="px-4 py-4 text-[13px] text-ink-500">
                  No schedules for this workspace. Create them under System, or run on demand from the Editor.
                </div>
              ) : (
                <ul className="divide-y divide-ink-100">
                  {schedules.slice(0, 6).map((s) => {
                    const scoped = String(s.project || '') === selected
                    return (
                      <li key={s.id || s.name} className="flex flex-wrap items-center gap-2 px-3 py-2">
                        <CalendarClock className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[13px] font-medium text-ink-900">
                            {s.name || s.id}
                            {!scoped ? (
                              <span className="ml-1.5 font-normal text-ink-400">(global)</span>
                            ) : null}
                          </div>
                          <div className="truncate text-[11px] text-ink-500">
                            {s.project}/{s.pipeline}
                            {s.interval_minutes != null ? ` · every ${s.interval_minutes}m` : ''}
                            {s.enabled === false ? ' · disabled' : ''}
                            {s.last_error ? ` · err: ${s.last_error}` : ''}
                          </div>
                        </div>
                        {s.id ? (
                          <button
                            type="button"
                            className="btn-secondary !px-2 !py-0.5 text-[11px]"
                            onClick={() => void runSchedule(String(s.id))}
                          >
                            <Play className="h-3 w-3" /> Run now
                          </button>
                        ) : null}
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </section>

          {/* Layer 2 — linked data (compact) */}
          <section className="ide-section">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="ide-section-title">Linked inputs</div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="ide-quiet-btn text-[11px]"
                  onClick={() => useAppStore.getState().openArtifacts({ project: selected })}
                >
                  Browse files
                </button>
                <span className="text-type-meta text-ink-400">
                  {links.inputs.length} pinned
                  {versionOptions.length ? ` · ${versionOptions.length} output version${versionOptions.length === 1 ? '' : 's'}` : ''}
                </span>
              </div>
            </div>
            <p className="mb-2 text-[12px] text-ink-500">
              Pin Data-library input labels here so Editor runs know which folders to use. Completing a run does not auto-link.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="rounded-md border border-ink-200 bg-white px-2 py-1 text-[12px]"
                value={linkPick}
                onChange={(e) => setLinkPick(e.target.value)}
                aria-label="Link input label"
              >
                <option value="">Select input…</option>
                {inputLabels.map((label) => (
                  <option key={label} value={label} disabled={links.inputs.includes(label)}>
                    {label}
                  </option>
                ))}
              </select>
              <ConfirmButton
                label="Link"
                confirmLabel={linkPick ? `Link “${linkPick}”?` : 'Confirm'}
                onConfirm={() => void linkInput()}
                disabled={!linkPick || links.inputs.includes(linkPick)}
              />
              <button
                type="button"
                className="ide-quiet-btn"
                onClick={() => openData({ mode: 'inputs' })}
              >
                Browse library
              </button>
            </div>
            {links.inputs.length === 0 && (
              <p className="mt-2 rounded-lg border border-dashed border-ink-200 bg-ink-50/50 px-3 py-2 text-[12px] text-ink-600">
                No inputs pinned yet. Pick a label above, or open the Data library and come back to Link.
              </p>
            )}
            {links.inputs.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {links.inputs.map((label) => (
                  <li key={label} className="inline-flex items-center gap-1 rounded-md bg-ink-50 px-2 py-0.5 text-[11px] text-ink-700">
                    {label}
                    <button type="button" className="text-ink-400 hover:text-rose-600" onClick={() => void unlinkInput(label)} aria-label={`Unlink ${label}`}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Layer 3 — advanced (collapsed by default) */}
          <details
            className="ide-section group"
            open={datasetOpen}
            onToggle={(e) => setDatasetOpen((e.currentTarget as HTMLDetailsElement).open)}
          >
            <summary className="flex cursor-pointer list-none items-center gap-2 text-[13px] font-medium text-ink-700 hover:text-ink-950">
              <ChevronRight className="h-4 w-4 text-ink-400 transition group-open:rotate-90" />
              Spec & metadata
              <span className="font-normal text-ink-400">spec, taxonomy, contract, versions…</span>
            </summary>
            <div className="mt-3 space-y-3 pl-1">
              <div className="flex flex-wrap gap-1 border-b border-ink-100 pb-2">
                {(
                  [
                    ['versions', 'Versions'],
                    ['spec', 'Spec'],
                    ['taxonomy', 'Taxonomy'],
                    ['contract', 'Contract'],
                    ['snapshots', 'Snapshots'],
                    ['diff', 'Diff'],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={tab === id ? 'tab-pill tab-pill-on' : 'tab-pill'}
                    onClick={() => setTab(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {tab === 'spec' && (
                <section className="space-y-2">
                  <textarea value={spec} onChange={(e) => setSpec(e.target.value)} rows={12} className="w-full rounded-lg border border-ink-200 p-3 font-mono text-[12px]" />
                  <button type="button" className="btn-secondary" onClick={() => void saveSpec()}>Save spec</button>
                </section>
              )}
              {tab === 'taxonomy' && (
                <section className="space-y-2">
                  <textarea value={taxonomy} onChange={(e) => setTaxonomy(e.target.value)} rows={12} className="w-full rounded-lg border border-ink-200 p-3 font-mono text-[12px]" />
                  <button type="button" className="btn-secondary" onClick={() => void saveTaxonomy()}>Save taxonomy</button>
                </section>
              )}
              {tab === 'contract' && (
                <section className="space-y-2">
                  <textarea value={contract} onChange={(e) => setContract(e.target.value)} rows={12} className="w-full rounded-lg border border-ink-200 p-3 font-mono text-[12px]" />
                  <button type="button" className="btn-secondary" onClick={() => void saveContract()}>Save contract</button>
                </section>
              )}
              {tab === 'versions' && (
                <section className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    <select value={versionFocus} onChange={(e) => setVersionFocus(e.target.value)} className="rounded-md border border-ink-200 px-2 py-1.5 text-[12px]">
                      {versionOptions.map((v) => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                    <button type="button" className="btn-secondary" onClick={() => void loadVersionDetail()}>Load stats</button>
                    <ConfirmButton label="Restore" confirmLabel={`Restore ${versionFocus}?`} onConfirm={() => void restoreVersion()} />
                  </div>
                  {versions.length === 0 ? (
                    <p className="text-[13px] text-ink-500">No versions yet — run a pipeline that writes dataset output.</p>
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
                    <input id="snapshot-name" value={snapshotName} onChange={(e) => setSnapshotName(e.target.value)} placeholder="snapshot-name" className="rounded-md border border-ink-200 px-2 py-1.5 text-[12px]" />
                    <button type="button" className="btn-secondary" onClick={() => void createSnapshot()}>Create</button>
                  </div>
                  {snapshots.length === 0 ? (
                    <p className="text-[13px] text-ink-500">No snapshots.</p>
                  ) : (
                    <ul className="space-y-1">
                      {snapshots.map((s, i) => {
                        const name =
                          typeof s === 'string'
                            ? s
                            : String((s as { snapshot_name?: string; name?: string }).snapshot_name ?? (s as { name?: string }).name ?? `snapshot-${i}`)
                        return (
                          <li key={name} className="flex items-center justify-between rounded-md border border-ink-100 px-2 py-1.5">
                            <span className="font-mono text-[12px]">{name}</span>
                            <ConfirmButton label="Restore" confirmLabel={`Restore ${name}?`} onConfirm={() => void restoreSnapshot(name)} />
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
                    <select value={diffA} onChange={(e) => setDiffA(e.target.value)} className="rounded-md border border-ink-200 px-2 py-1.5 text-[12px]">
                      {versionOptions.map((v) => (
                        <option key={`a-${v}`} value={v}>{v}</option>
                      ))}
                    </select>
                    <span className="self-center text-[12px] text-ink-400">vs</span>
                    <select value={diffB} onChange={(e) => setDiffB(e.target.value)} className="rounded-md border border-ink-200 px-2 py-1.5 text-[12px]">
                      {versionOptions.map((v) => (
                        <option key={`b-${v}`} value={v}>{v}</option>
                      ))}
                    </select>
                    <button type="button" className="btn-secondary" onClick={() => void runDiff()}>Diff</button>
                  </div>
                  {diffResult != null && <KeyValue data={diffResult} />}
                  {(() => {
                    const ids = lineageIds(lineage)
                    if (!ids.runId && !ids.artifactId) return null
                    return (
                      <div className="flex flex-wrap gap-2">
                        {ids.runId ? (
                          <button type="button" className="btn-secondary" onClick={() => openTrace({ runId: ids.runId })}>Open Lineage</button>
                        ) : null}
                        {ids.artifactId || ids.runId ? (
                          <button
                            type="button"
                            className="btn-secondary"
                            onClick={() => openArtifacts({ runId: ids.runId, artifactId: ids.artifactId })}
                          >
                            Open Artifacts
                          </button>
                        ) : null}
                      </div>
                    )
                  })()}
                  <CollapsibleJson value={lineage} label="Lineage JSON" />
                </section>
              )}
            </div>
          </details>

          {/* Layer 4 — settings */}
          <details className="ide-section group">
            <summary className="flex cursor-pointer list-none items-center gap-2 text-[13px] font-medium text-ink-700 hover:text-ink-950">
              <ChevronRight className="h-4 w-4 text-ink-400 transition group-open:rotate-90" />
              Project settings
            </summary>
            <div className="mt-3 flex flex-wrap items-center gap-2 pl-1">
              <label className="flex items-center gap-1.5 text-[12px] text-ink-500">
                Status
                <select
                  className="rounded-md border border-ink-200 bg-white px-2 py-1 text-[12px] text-ink-800"
                  value={statusVal}
                  onChange={(e) => void setStatus(e.target.value)}
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
              <input value={renameTo} onChange={(e) => setRenameTo(e.target.value)} className="rounded-md border border-ink-200 px-2 py-1 text-[12px]" aria-label="Rename to" />
              <button type="button" className="btn-secondary" onClick={() => void rename()}>
                <Pencil className="h-3.5 w-3.5" /> Rename
              </button>
              <input value={cloneTo} onChange={(e) => setCloneTo(e.target.value)} className="rounded-md border border-ink-200 px-2 py-1 text-[12px]" aria-label="Clone as" />
              <button type="button" className="btn-secondary" onClick={() => void clone()}>
                <Copy className="h-3.5 w-3.5" /> Clone
              </button>
              <button type="button" className="btn-secondary" onClick={useInEdge}>Use in Edge</button>
              <ConfirmButton label="Delete" confirmLabel={`Delete ${selected}?`} danger onConfirm={() => void remove()} />
            </div>
          </details>
        </div>
      </div>
    </div>
  )
}
