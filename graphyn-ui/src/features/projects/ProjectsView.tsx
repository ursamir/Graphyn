import React from 'react'
import {
  RefreshCw,
  Copy,
  Database,
  Pencil,
  Workflow,
  History,
  ChevronRight,
  CalendarClock,
  Clock,
  LayoutGrid,
  LayoutTemplate,
  MoreHorizontal,
  Play,
  Plus,
  Rows3,
  Search,
  Star,
} from 'lucide-react'
import { apiJson } from '../../api/client'
import { unwrapList } from '../../api/unwrapList'
import { useAppStore } from '../../store/appStore'
import type { GraphIR } from '../../types/graph'
import {
  ConfirmButton,
  CollapsibleJson,
  ErrorBanner,
  KeyValue,
  LoadingBlock,
  StatusBadge,
} from '../../components/ui'
import { paths } from '../../routes/paths'
import { goView, onPathChange, readSearchParams, replacePathSearch } from '../../routes/nav'
import { formatRelativeTime, shortRunId } from '../../lib/format'
import {
  forgetRecentWorkspace,
  noteRecentWorkspace,
  readRecentWorkspaces,
} from '../../lib/recentWorkspaces'

interface Project {
  name: string
  status?: string
  /** GET /projects already returns these — the picker discarded all of them and
   *  rendered a bare name, so there was no way to tell 30 workspaces apart. */
  created_at?: string
  updated_at?: string
  versions?: string[]
  [key: string]: unknown
}

/** Row from GET /runs. The global (unscoped) listing carries `project` for any
 *  run that recorded one, which is what makes a cross-workspace activity feed
 *  and per-workspace last-run possible in a single request. */
type RunRow = {
  run_id: string
  status?: string
  project?: string
  graph_name?: string
  created_at?: string
}

type WorkspaceSort = 'recent' | 'updated' | 'activity' | 'name'

/** Approximate height of the workspace ⋯ menu (4 items + separator), used to
 *  decide whether it still fits below the trigger or has to open upwards. */
const MENU_HEIGHT_PX = 190

const SORT_LABEL: Record<WorkspaceSort, string> = {
  recent: 'Recently opened',
  updated: 'Recently updated',
  activity: 'Recent activity',
  name: 'Name (A–Z)',
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


function parseProjectsLocation(): { project?: string; tab?: Tab } {
  const { pathname } = window.location
  const params = readSearchParams()
  const parts = pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  let project: string | undefined
  if (parts[0] === 'workspaces' && parts[1]) {
    project = decodeURIComponent(parts[1])
  } else {
    project = (params.get('project') || '').trim() || undefined
  }
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

function pinnedKey(project: string) {
  return `graphyn.pinnedPipelines.${project}`
}

function readPinnedPipelines(project: string): string[] {
  try {
    const raw = localStorage.getItem(pinnedKey(project))
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? parsed.map(String).filter(Boolean) : []
  } catch {
    return []
  }
}

function writePinnedPipelines(project: string, names: string[]) {
  try {
    localStorage.setItem(pinnedKey(project), JSON.stringify(names))
  } catch {
    /* ignore */
  }
}


export default function ProjectsView() {
  const activeProject = useAppStore((s) => s.activeProject)
  const pushToast = useAppStore((s) => s.pushToast)
  const openData = useAppStore((s) => s.openData)
  const openTrace = useAppStore((s) => s.openTrace)
  const openArtifacts = useAppStore((s) => s.openArtifacts)
  const openEdge = useAppStore((s) => s.openEdge)
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const initialLoc = React.useMemo(() => parseProjectsLocation(), [])
  const [projects, setProjects] = React.useState<Project[] | null>(null)
  const [selected, setSelected] = React.useState<string | null>(initialLoc.project ?? null)
  const [tab, setTab] = React.useState<Tab>(initialLoc.tab ?? 'versions')
  const [newName, setNewName] = React.useState('')
  const nameRef = React.useRef<HTMLInputElement | null>(null)
  const [renameTo, setRenameTo] = React.useState('')
  const [cloneTo, setCloneTo] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  // Separate from `error` (the projects-list load failure) — open() failing
  // for one project (e.g. "Project 'X' not found" after it's deleted) used
  // to write to the same `error` state, so that message kept showing in the
  // list panel's own banner even after navigating away to browse other
  // projects, with a misleading "reload the list" retry action attached.
  const [openError, setOpenError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  // True for the whole duration of open()'s multi-endpoint fetch. Every
  // "empty" section below (Activity/Continue/etc.) keys off array lengths,
  // which are also [] before the fetch resolves — without this flag every
  // workspace open briefly, falsely renders as "no pipelines / no activity".
  const [opening, setOpening] = React.useState(false)

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
  const [pipelinesHintDismissed, setPipelinesHintDismissed] = React.useState(() => {
    try {
      return localStorage.getItem('graphyn.home.pipelinesHint') === '1'
    } catch {
      return false
    }
  })

  const load = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      setProjects(unwrapList<Project>(await apiJson('/projects')))
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

  /* One unscoped /runs call powers the whole landing page: the cross-workspace
     activity feed, each workspace's last run, and the failure count. Fetching
     per-project would be ~30 requests for the same information. */
  const [allRuns, setAllRuns] = React.useState<RunRow[] | null>(null)
  const loadAllRuns = React.useCallback(async () => {
    try {
      const rows = await apiJson<RunRow[]>('/runs', { query: { limit: 60, offset: 0 } })
      setAllRuns(Array.isArray(rows) ? rows : [])
    } catch {
      /* The workspace list is the page; a missing activity feed degrades it but
         must not blank it, so this failure is deliberately not surfaced as an
         error banner — the feed renders its own "couldn't load" state. */
      setAllRuns([])
    }
  }, [])
  React.useEffect(() => {
    if (!selected) void loadAllRuns()
  }, [selected, loadAllRuns])

  const open = async (name: string) => {
    noteRecentWorkspace(name)
    setSelected(name)
    setActiveProject(name)
    setRenameTo(name)
    setCloneTo(`${name}-copy`)
    setOpenError(null)
    setOpening(true)
    replacePathSearch(
      tab && tab !== 'versions' ? { tab } : {},
      paths.workspace(name),
    )
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
          setSchedules(typed)
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
      setOpenError(err instanceof Error ? err.message : String(err))
      // Keep selected, but clear Home payload so we don't pretend load succeeded.
      setVersions([])
      setSpec('')
      setTaxonomy('[]')
      setContract('{}')
      setSnapshots([])
      setLineage(null)
      setRecentRuns([])
      setProjectPipelines([])
      setSchedules([])
      setLinks({ inputs: [], outputs: [] })
      setVersionFocus('')
      setDiffA('')
      setDiffB('')
    } finally {
      setOpening(false)
    }
  }

  React.useEffect(() => {
    const apply = () => {
      const h = parseProjectsLocation()
      if (h.tab) {
        setTab(h.tab)
        setDatasetOpen(true)
      }
      if (h.project) {
        setSelected((cur) => {
          if (h.project !== cur) {
            queueMicrotask(() => void open(h.project!))
          }
          return h.project!
        })
      } else {
        setSelected(null)
        setOpenError(null)
      }
    }
    return onPathChange(apply)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  React.useEffect(() => {
    if (initialLoc.project) void open(initialLoc.project)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** URL/store sync: workspace chip can set activeProject before ProjectsView selected catches up. */
  React.useEffect(() => {
    const fromUrl = parseProjectsLocation().project
    const name = fromUrl || activeProject
    if (!name || selected === name) return
    if (fromUrl || (activeProject && window.location.pathname.startsWith('/workspaces/'))) {
      void open(name)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProject])

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

  const rollbackPipeline = async (
    pipelineName: string,
    defaultVersion?: string | null,
  ) => {
    if (!selected) return
    const suggested = (defaultVersion || '').trim()
    const version = window
      .prompt('Rollback draft to version (required):', suggested)
      ?.trim()
    if (!version) {
      pushToast('Rollback cancelled — version is required', 'info')
      return
    }
    try {
      await apiJson(
        `/projects/${encodeURIComponent(selected)}/pipelines/${encodeURIComponent(pipelineName)}/rollback`,
        {
          method: 'POST',
          body: JSON.stringify({ version }),
        },
      )
      pushToast(`Rolled draft back to ${version}`, 'success')
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
      forgetRecentWorkspace(selected)
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

  /* Name-addressed variants for the landing page, where there is no `selected`
     workspace — the console acts on whichever card you used. */
  const cloneProject = async (from: string, to: string) => {
    try {
      await apiJson(`/projects/${encodeURIComponent(from)}/clone`, {
        method: 'POST',
        body: JSON.stringify({ new_name: to }),
      })
      pushToast(`Cloned ${from} → ${to}`, 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const removeProject = async (name: string) => {
    try {
      await apiJson(`/projects/${encodeURIComponent(name)}`, {
        method: 'DELETE',
        body: JSON.stringify({ confirm: name }),
      })
      pushToast(`Deleted ${name}`, 'success')
      forgetRecentWorkspace(name)
      if (useAppStore.getState().activeProject === name) setActiveProject(null)
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

  const [datasetOpen, setDatasetOpen] = React.useState(() => Boolean(initialLoc.tab))
  const [projectFilter, setProjectFilter] = React.useState('')
  /* Landing-page console controls. Sort and density persist — a management list
     you re-sort on every visit is a list that doesn't remember you. */
  const [sortBy, setSortBy] = React.useState<WorkspaceSort>(() => {
    try {
      const raw = localStorage.getItem('graphyn.workspaces.sort')
      return raw && raw in SORT_LABEL ? (raw as WorkspaceSort) : 'recent'
    } catch {
      return 'recent'
    }
  })
  const [dense, setDense] = React.useState<boolean>(() => {
    try {
      return localStorage.getItem('graphyn.workspaces.dense') === '1'
    } catch {
      return false
    }
  })
  const [cardMenu, setCardMenu] = React.useState<string | null>(null)
  const [cloneDialog, setCloneDialog] = React.useState<{ from: string; to: string } | null>(null)
  const [activityFilter, setActivityFilter] = React.useState<'all' | 'failed'>('all')
  const [menuUp, setMenuUp] = React.useState(false)
  const cardMenuRef = React.useRef<HTMLDivElement | null>(null)
  React.useEffect(() => {
    if (!cardMenu) return
    const onDoc = (e: MouseEvent) => {
      if (!cardMenuRef.current?.contains(e.target as Node)) setCardMenu(null)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setCardMenu(null)
    }
    document.addEventListener('mousedown', onDoc)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      window.removeEventListener('keydown', onKey)
    }
  }, [cardMenu])
  const setSortPref = (next: WorkspaceSort) => {
    setSortBy(next)
    try {
      localStorage.setItem('graphyn.workspaces.sort', next)
    } catch {
      /* ignore */
    }
  }
  const setDensePref = (next: boolean) => {
    setDense(next)
    try {
      localStorage.setItem('graphyn.workspaces.dense', next ? '1' : '0')
    } catch {
      /* ignore */
    }
  }
  const [pinnedPipelines, setPinnedPipelines] = React.useState<string[]>([])

  React.useEffect(() => {
    if (!selected) {
      setPinnedPipelines([])
      return
    }
    setPinnedPipelines(readPinnedPipelines(selected))
  }, [selected])

  const togglePinPipeline = (name: string) => {
    if (!selected) return
    setPinnedPipelines((prev) => {
      const next = prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
      writePinnedPipelines(selected, next)
      return next
    })
  }

  const sortedPipelines = React.useMemo(() => {
    const pinSet = new Set(pinnedPipelines)
    return [...projectPipelines].sort((a, b) => {
      const ap = pinSet.has(a.name) ? 0 : 1
      const bp = pinSet.has(b.name) ? 0 : 1
      if (ap !== bp) return ap - bp
      return a.name.localeCompare(b.name)
    })
  }, [projectPipelines, pinnedPipelines])

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

  /* The header stats used to be plain text sitting next to a "Last run" link —
     three things that look identical, one of which happens to be clickable.
     Each stat now jumps to the card that owns it and flashes it, so the summary
     line is a table of contents for the page rather than decoration. */
  const continueRef = React.useRef<HTMLElement | null>(null)
  const inputsRef = React.useRef<HTMLElement | null>(null)
  const [flashed, setFlashed] = React.useState<'continue' | 'inputs' | null>(null)
  const flashTimer = React.useRef<number | null>(null)
  React.useEffect(
    () => () => {
      if (flashTimer.current) window.clearTimeout(flashTimer.current)
    },
    [],
  )
  const jumpToCard = (which: 'continue' | 'inputs') => {
    const el = which === 'continue' ? continueRef.current : inputsRef.current
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setFlashed(which)
    if (flashTimer.current) window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => setFlashed(null), 1500)
  }
  const cardRing = (which: 'continue' | 'inputs') =>
    flashed === which ? 'ring-2 ring-accent-400 ring-offset-2' : ''

  const authBlocked = /unauthorized|401|api token/i.test(error || '')
  const goEditor = () => goView('builder')
  const goTemplates = () => goView('templates')
  const openLastRun = () => {
    const id = recentRuns[0]?.run_id
    if (id) useAppStore.getState().openRun(id)
  }
  const goLinkDataset = () => {
    if (!selected) return
    openData({ project: selected })
    replacePathSearch({ mode: 'inputs', manage: '1' })
  }
  const workspaceEmpty = projectPipelines.length === 0 && recentRuns.length === 0

  /* ── Landing console: manage every workspace from one surface ───────────────
     This used to be a 15.5rem column of 30 bare names (each one truncated, each
     badged "DRAFT") beside an otherwise-empty welcome pane. Nothing on it told
     you which workspace had run recently, which had failed, or which you touched
     last — you had to open them one at a time to find out. GET /projects already
     returns updated_at and versions, and the unscoped GET /runs carries the
     project on each row, so all of that is available for two requests. */
  if (!selected) {
    const list = projects ?? []
    const known = new Set(list.map((p) => p.name))
    /* Recents are only meaningful while the workspace still exists — a deleted
       or renamed one would otherwise sit at the top of the list forever. */
    const recentNames = readRecentWorkspaces().filter((n) => known.has(n))
    const recentRank = new Map(recentNames.map((n, i) => [n, i] as const))

    const runsByProject = new Map<string, RunRow[]>()
    for (const r of allRuns ?? []) {
      const key = (r.project || '').trim()
      if (!key) continue
      const bucket = runsByProject.get(key)
      if (bucket) bucket.push(r)
      else runsByProject.set(key, [r])
    }
    const lastRunOf = (name: string) => runsByProject.get(name)?.[0]
    const ts = (iso?: string) => {
      const t = iso ? Date.parse(iso) : NaN
      return Number.isNaN(t) ? 0 : t
    }
    const isFailed = (status?: string) => /fail|error/i.test(status || '')

    const sorted = [...filteredProjects].sort((a, b) => {
      if (sortBy === 'name') return a.name.localeCompare(b.name)
      if (sortBy === 'updated') {
        return ts(b.updated_at) - ts(a.updated_at) || a.name.localeCompare(b.name)
      }
      if (sortBy === 'activity') {
        return (
          ts(lastRunOf(b.name)?.created_at) - ts(lastRunOf(a.name)?.created_at) ||
          a.name.localeCompare(b.name)
        )
      }
      const ar = recentRank.get(a.name) ?? Number.POSITIVE_INFINITY
      const br = recentRank.get(b.name) ?? Number.POSITIVE_INFINITY
      if (ar !== br) return ar - br
      return ts(b.updated_at) - ts(a.updated_at) || a.name.localeCompare(b.name)
    })

    /* Only runs that recorded a project can be opened from here — openRun with
       no workspace resolves to no path and silently does nothing. Rather than
       render rows that look clickable and aren't, the untagged ones are counted
       out loud instead of being quietly dropped. */
    const feedAll = (allRuns ?? []).filter((r) => r.project)
    const untagged = (allRuns?.length ?? 0) - feedAll.length
    const feed = activityFilter === 'failed' ? feedAll.filter((r) => isFailed(r.status)) : feedAll
    const failedCount = feedAll.filter((r) => isFailed(r.status)).length
    const newestRun = feedAll[0]

    const statTile = (
      label: string,
      value: React.ReactNode,
      hint?: string,
      onClick?: () => void,
      active?: boolean,
    ) => {
      const body = (
        <>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">
            {label}
          </div>
          <div className="mt-1 text-[22px] font-semibold leading-none text-ink-950">{value}</div>
          {hint ? <div className="mt-1 text-[11px] text-ink-500">{hint}</div> : null}
        </>
      )
      const base = 'rounded-2xl border bg-white p-3.5 text-left shadow-sm transition'
      return onClick ? (
        <button
          type="button"
          onClick={onClick}
          aria-pressed={active}
          className={`${base} ${active ? 'border-accent-400 ring-1 ring-accent-200' : 'border-ink-200/80 hover:border-accent-300'}`}
        >
          {body}
        </button>
      ) : (
        <div className={`${base} border-ink-200/80`}>{body}</div>
      )
    }

    const statusChip = (raw: unknown) => {
      const s = normalizeProjectStatus(raw)
      /* Every project is "draft" until someone changes it, so badging all 30 of
         them printed the same word 30 times and told you nothing. Only the
         statuses that actually distinguish a workspace earn the pixels. */
      if (s === 'draft') return null
      return (
        <span className="shrink-0 rounded-md bg-ink-100 px-1.5 py-px text-[10px] font-medium uppercase tracking-wide text-ink-600">
          {s}
        </span>
      )
    }

    const cardMenuFor = (p: Project) => (
      /* Every row's trigger sits in its own `relative` wrapper. They all shared
         one z-index, so an open menu was painted UNDER the wrappers of the rows
         below it (later siblings win at equal z) — the neighbouring ⋯ buttons
         showed straight through the menu and it read as garbled. The open one
         has to outrank its siblings, not just its own contents. */
      <div
        className={`relative shrink-0 ${cardMenu === p.name ? 'z-40' : 'z-10'}`}
        ref={cardMenu === p.name ? cardMenuRef : undefined}
      >
        <button
          type="button"
          className="btn-icon"
          aria-label={`More actions for ${p.name}`}
          aria-expanded={cardMenu === p.name}
          aria-haspopup="menu"
          onClick={(e) => {
            if (cardMenu === p.name) {
              setCardMenu(null)
              return
            }
            /* Open upwards near the bottom of the viewport — on the last rows of
               a 30-workspace list the menu was cut off by the window edge and
               Clone/Delete were unreachable. */
            const rect = e.currentTarget.getBoundingClientRect()
            setMenuUp(window.innerHeight - rect.bottom < MENU_HEIGHT_PX)
            setCardMenu(p.name)
          }}
        >
          <MoreHorizontal className="h-4 w-4" />
        </button>
        {cardMenu === p.name && (
          <div
            role="menu"
            className={`absolute right-0 z-40 w-52 rounded-xl border border-ink-200 bg-white p-1.5 shadow-soft ${
              menuUp ? 'bottom-full mb-1' : 'top-full mt-1'
            }`}
          >
            <button
              type="button"
              role="menuitem"
              className="block w-full rounded-md px-2 py-1.5 text-left text-[12px] text-ink-800 hover:bg-ink-50"
              onClick={() => {
                setCardMenu(null)
                void open(p.name).then(goEditor)
              }}
            >
              Open in Editor
            </button>
            <button
              type="button"
              role="menuitem"
              className="block w-full rounded-md px-2 py-1.5 text-left text-[12px] text-ink-800 hover:bg-ink-50"
              onClick={() => {
                setCardMenu(null)
                void open(p.name).then(() => goView('runs', { workspaceId: p.name }))
              }}
            >
              View runs
            </button>
            <button
              type="button"
              role="menuitem"
              className="block w-full rounded-md px-2 py-1.5 text-left text-[12px] text-ink-800 hover:bg-ink-50"
              onClick={() => {
                setCardMenu(null)
                setCloneDialog({ from: p.name, to: `${p.name}-copy` })
              }}
            >
              Clone…
            </button>
            <div className="mt-1 border-t border-ink-100 pt-1">
              <ConfirmButton
                label="Delete"
                confirmLabel={`Delete ${p.name}?`}
                danger
                className="w-full justify-start"
                onConfirm={() => {
                  setCardMenu(null)
                  void removeProject(p.name)
                }}
              />
            </div>
          </div>
        )}
      </div>
    )

    /* Last run, rendered identically in card and row layouts. Clicking it opens
       that run directly instead of making you open the workspace and find it. */
    const lastRunLine = (p: Project) => {
      const r = lastRunOf(p.name)
      if (!allRuns) return <span className="text-[12px] text-ink-300">Loading activity…</span>
      if (!r) return <span className="text-[12px] text-ink-400">No runs in recent history</span>
      return (
        <button
          type="button"
          className="relative z-10 flex min-w-0 items-center gap-1.5 text-left text-[12px] text-ink-600 hover:text-accent-800"
          title={`Open run ${r.run_id}`}
          onClick={() => useAppStore.getState().openRun(r.run_id, { project: p.name })}
        >
          <span
            aria-hidden
            className={`h-1.5 w-1.5 shrink-0 rounded-full ${
              isFailed(r.status)
                ? 'bg-rose-500'
                : /complete|succe/i.test(r.status || '')
                  ? 'bg-emerald-500'
                  : 'bg-amber-500'
            }`}
          />
          <span className="min-w-0 truncate">
            {r.graph_name || shortRunId(r.run_id)} · {formatRelativeTime(r.created_at)}
          </span>
        </button>
      )
    }

    const metaLine = (p: Project) => {
      const versionCount = Array.isArray(p.versions) ? p.versions.length : 0
      const runCount = runsByProject.get(p.name)?.length ?? 0
      const bits: string[] = []
      if (runCount) bits.push(`${runCount} recent run${runCount === 1 ? '' : 's'}`)
      if (versionCount) bits.push(`${versionCount} dataset version${versionCount === 1 ? '' : 's'}`)
      if (p.updated_at) bits.push(`updated ${formatRelativeTime(p.updated_at)}`)
      return bits.length ? bits.join(' · ') : 'No pipelines or runs yet'
    }

    return (
      <div className="h-full min-h-0 overflow-y-auto">
        <div className="mx-auto max-w-[92rem] space-y-6 px-6 py-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-type-page text-ink-950">Workspaces</h1>
              <p className="mt-1 max-w-2xl text-type-body text-ink-500">
                Every workspace on this API. A workspace holds its own pipelines, linked datasets and
                run history — Editor and Runs stay greyed out in the sidebar until one is open.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn-quiet"
                onClick={() => {
                  void load()
                  void loadAllRuns()
                }}
              >
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </button>
              <button type="button" className="btn-secondary" onClick={goTemplates}>
                <LayoutTemplate className="h-3.5 w-3.5" /> Browse templates
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => openData({ mode: 'inputs' })}
              >
                <Database className="h-3.5 w-3.5" /> Browse shared library
              </button>
            </div>
          </div>

          {error && (
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
          )}

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {statTile(
              'Workspaces',
              loading || projects == null ? '—' : list.length,
              recentNames.length ? `${recentNames.length} opened recently` : 'None opened yet',
            )}
            {statTile(
              'Active',
              allRuns ? runsByProject.size : '—',
              'with runs in recent history',
            )}
            {statTile(
              'Failed runs',
              allRuns ? failedCount : '—',
              failedCount
                ? activityFilter === 'failed'
                  ? 'Showing only these — click to clear'
                  : 'Click to filter activity'
                : 'Nothing failing',
              failedCount ? () => setActivityFilter((f) => (f === 'failed' ? 'all' : 'failed')) : undefined,
              activityFilter === 'failed',
            )}
            {statTile(
              'Last activity',
              newestRun ? formatRelativeTime(newestRun.created_at) : allRuns ? 'None' : '—',
              newestRun?.project ? `in ${newestRun.project}` : undefined,
            )}
          </div>

          {/* Creating a workspace was a bare text box in a sidebar gutter. It is
              the primary action of this page, so it looks like one. */}
          <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-end gap-2">
              <label className="min-w-[14rem] flex-1 text-[12px] font-medium text-ink-600">
                New workspace
                <input
                  ref={nameRef}
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="my-pipeline-project"
                  className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
                  onKeyDown={(e) => e.key === 'Enter' && void create()}
                />
              </label>
              <button
                type="button"
                className="btn-primary mb-px"
                disabled={!newName.trim()}
                title={!newName.trim() ? 'Type a name first' : `Create ${newName.trim()}`}
                onClick={() => void create()}
              >
                <Plus className="h-3.5 w-3.5" /> Create workspace
              </button>
            </div>
            <p className="mt-2 text-[12px] text-ink-400">
              Created empty and opened immediately. Templates and Datasets are shared across
              workspaces, so you can look at those before picking one.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[13rem] flex-1 sm:max-w-sm">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
              <input
                value={projectFilter}
                onChange={(e) => setProjectFilter(e.target.value)}
                placeholder="Search workspaces"
                aria-label="Search workspaces"
                className="w-full rounded-lg border border-ink-200 bg-white py-1.5 pl-8 pr-2 text-sm"
              />
            </div>
            <label className="flex items-center gap-1.5 text-[12px] text-ink-500">
              Sort
              <select
                className="rounded-md border border-ink-200 bg-white px-2 py-1 text-[12px] text-ink-800"
                value={sortBy}
                onChange={(e) => setSortPref(e.target.value as WorkspaceSort)}
              >
                {(Object.keys(SORT_LABEL) as WorkspaceSort[]).map((k) => (
                  <option key={k} value={k}>
                    {SORT_LABEL[k]}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex overflow-hidden rounded-md border border-ink-200">
              <button
                type="button"
                className={`px-2 py-1 ${!dense ? 'bg-ink-100 text-ink-900' : 'bg-white text-ink-500 hover:text-ink-800'}`}
                aria-pressed={!dense}
                title="Card view"
                onClick={() => setDensePref(false)}
              >
                <LayoutGrid className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                className={`border-l border-ink-200 px-2 py-1 ${dense ? 'bg-ink-100 text-ink-900' : 'bg-white text-ink-500 hover:text-ink-800'}`}
                aria-pressed={dense}
                title="Compact list"
                onClick={() => setDensePref(true)}
              >
                <Rows3 className="h-3.5 w-3.5" />
              </button>
            </div>
            <span className="text-[12px] text-ink-400">
              {loading || projects == null
                ? 'Loading…'
                : `${sorted.length}${sorted.length === list.length ? '' : ` of ${list.length}`} shown`}
            </span>
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_21rem]">
            <section className="min-w-0">
              {loading || projects == null ? (
                <LoadingBlock label="Loading workspaces…" />
              ) : list.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-ink-300 bg-white px-6 py-10 text-center">
                  <h2 className="text-base font-semibold text-ink-950">No workspaces yet</h2>
                  <p className="mx-auto mt-1 max-w-md text-[13px] text-ink-500">
                    {authBlocked
                      ? 'Sign in via Settings to list workspaces.'
                      : 'Create one above to start building pipelines, or open a template to see how one is put together.'}
                  </p>
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => nameRef.current?.focus()}
                    >
                      <Plus className="h-3.5 w-3.5" /> New workspace
                    </button>
                    <button type="button" className="btn-secondary" onClick={goTemplates}>
                      Browse templates
                    </button>
                  </div>
                </div>
              ) : sorted.length === 0 ? (
                <div className="rounded-2xl border border-ink-200/80 bg-white px-6 py-10 text-center">
                  <p className="text-[13px] text-ink-600">
                    No workspaces match “{projectFilter.trim()}”.
                  </p>
                  <button
                    type="button"
                    className="btn-secondary mt-3"
                    onClick={() => setProjectFilter('')}
                  >
                    Clear search
                  </button>
                </div>
              ) : dense ? (
                <ul className="divide-y divide-ink-100 overflow-hidden rounded-2xl border border-ink-200/80 bg-white shadow-sm">
                  {sorted.map((p) => (
                    <li
                      key={p.name}
                      className="group relative flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 transition hover:bg-ink-50/70"
                    >
                      <button
                        type="button"
                        className="min-w-0 flex-1 truncate text-left text-[13px] font-medium text-ink-900 after:absolute after:inset-0 after:content-[''] group-hover:text-accent-800"
                        onClick={() => void open(p.name)}
                      >
                        {p.name}
                      </button>
                      {recentRank.has(p.name) ? (
                        <Clock className="h-3 w-3 shrink-0 text-ink-300" aria-label="Opened recently" />
                      ) : null}
                      {statusChip(p.status)}
                      <div className="hidden min-w-0 max-w-[16rem] flex-1 sm:block">
                        {lastRunLine(p)}
                      </div>
                      <span className="hidden shrink-0 text-[11px] text-ink-400 lg:inline">
                        {p.updated_at ? `updated ${formatRelativeTime(p.updated_at)}` : ''}
                      </span>
                      {cardMenuFor(p)}
                    </li>
                  ))}
                </ul>
              ) : (
                <ul className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                  {sorted.map((p) => (
                    <li
                      key={p.name}
                      className="group relative flex flex-col rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm transition hover:border-accent-300 hover:shadow-soft"
                    >
                      <div className="flex items-start gap-2">
                        <div className="min-w-0 flex-1">
                          {/* Stretched-link pattern: the title is the real button
                              and its ::after covers the card, so the whole card is
                              clickable without nesting interactive elements. */}
                          <button
                            type="button"
                            className="block w-full truncate text-left text-[14px] font-semibold text-ink-950 after:absolute after:inset-0 after:content-[''] group-hover:text-accent-800"
                            title={p.name}
                            onClick={() => void open(p.name)}
                          >
                            {p.name}
                          </button>
                          <div className="mt-1 flex flex-wrap items-center gap-1.5">
                            {recentRank.has(p.name) ? (
                              <span className="inline-flex items-center gap-1 rounded-md bg-accent-50 px-1.5 py-px text-[10px] font-medium uppercase tracking-wide text-accent-800">
                                <Clock className="h-2.5 w-2.5" /> Recent
                              </span>
                            ) : null}
                            {statusChip(p.status)}
                          </div>
                        </div>
                        {cardMenuFor(p)}
                      </div>
                      <div className="mt-3 border-t border-ink-100 pt-2.5">
                        {lastRunLine(p)}
                        <p className="mt-1 truncate text-[11px] text-ink-400" title={metaLine(p)}>
                          {metaLine(p)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Activity across every workspace — previously you had to open each
                one in turn to discover that something had failed in it. */}
            {/* Sticky: the workspace list is 30 rows tall and the rail is short, so
                it scrolled out of view almost immediately and the cross-workspace
                activity — the reason the rail exists — was only visible at the top
                of the page. */}
            <aside className="min-w-0 xl:sticky xl:top-4 xl:self-start">
              <div className="flex flex-col rounded-2xl border border-ink-200/80 bg-white shadow-sm">
                <div className="flex items-center justify-between gap-2 border-b border-ink-100 px-4 py-3">
                  <div className="ide-section-title">Recent activity</div>
                  <div className="flex overflow-hidden rounded-md border border-ink-200 text-[11px]">
                    {(['all', 'failed'] as const).map((f) => (
                      <button
                        key={f}
                        type="button"
                        className={`px-2 py-0.5 capitalize ${
                          activityFilter === f
                            ? 'bg-ink-100 text-ink-900'
                            : 'bg-white text-ink-500 hover:text-ink-800'
                        } ${f === 'failed' ? 'border-l border-ink-200' : ''}`}
                        aria-pressed={activityFilter === f}
                        onClick={() => setActivityFilter(f)}
                      >
                        {f}
                      </button>
                    ))}
                  </div>
                </div>
                {allRuns == null ? (
                  <div className="px-4 py-5">
                    <LoadingBlock label="Loading activity…" />
                  </div>
                ) : feed.length === 0 ? (
                  <p className="px-4 py-5 text-[12px] text-ink-500">
                    {activityFilter === 'failed'
                      ? 'No failed runs in recent history.'
                      : 'No runs recorded against a workspace yet.'}
                  </p>
                ) : (
                  <ul className="divide-y divide-ink-100">
                    {feed.slice(0, 14).map((r) => (
                      <li key={r.run_id}>
                        <button
                          type="button"
                          className="ide-row w-full items-start px-3 py-2"
                          onClick={() =>
                            useAppStore.getState().openRun(r.run_id, { project: r.project })
                          }
                        >
                          <span
                            aria-hidden
                            className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                              isFailed(r.status)
                                ? 'bg-rose-500'
                                : /complete|succe/i.test(r.status || '')
                                  ? 'bg-emerald-500'
                                  : 'bg-amber-500'
                            }`}
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[12px] font-medium text-ink-900">
                              {r.graph_name || shortRunId(r.run_id)}
                            </span>
                            <span className="block truncate text-[11px] text-ink-500">
                              {r.project} · {formatRelativeTime(r.created_at)}
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {untagged > 0 && (
                  <p className="border-t border-ink-100 px-4 py-2 text-[11px] text-ink-400">
                    {untagged} run{untagged === 1 ? '' : 's'} not tagged with a workspace are hidden
                    — they can't be opened from here.
                  </p>
                )}
              </div>
            </aside>
          </div>
        </div>

        {cloneDialog && (
          <div
            className="fixed inset-0 z-[100] flex items-center justify-center bg-ink-950/40 p-4"
            role="dialog"
            aria-modal="true"
            aria-labelledby="clone-ws-title"
            onClick={() => setCloneDialog(null)}
          >
            <div
              className="w-full max-w-md rounded-2xl border border-ink-200 bg-white p-5 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <h2 id="clone-ws-title" className="text-lg font-semibold text-ink-950">
                Clone {cloneDialog.from}
              </h2>
              <p className="mt-1 text-sm text-ink-500">
                Copies the workspace's pipelines and metadata under a new name. Run history is not
                copied.
              </p>
              <label className="mt-4 block text-sm text-ink-600">
                New workspace name
                <input
                  autoFocus
                  className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
                  value={cloneDialog.to}
                  onChange={(e) => setCloneDialog({ ...cloneDialog, to: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key !== 'Enter' || !cloneDialog.to.trim()) return
                    const { from, to } = cloneDialog
                    setCloneDialog(null)
                    void cloneProject(from, to.trim())
                  }}
                />
              </label>
              <div className="mt-4 flex justify-end gap-2">
                <button type="button" className="btn-secondary" onClick={() => setCloneDialog(null)}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  disabled={!cloneDialog.to.trim() || cloneDialog.to.trim() === cloneDialog.from}
                  title={
                    !cloneDialog.to.trim()
                      ? 'Enter a name first'
                      : cloneDialog.to.trim() === cloneDialog.from
                        ? 'Pick a different name for the copy'
                        : undefined
                  }
                  onClick={() => {
                    const { from, to } = cloneDialog
                    setCloneDialog(null)
                    void cloneProject(from, to.trim())
                  }}
                >
                  Clone
                </button>
              </div>
            </div>
          </div>
        )}
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
            {/* "Last run" lived here as well as in the metrics line below and in the
                header's own run chip — three controls for one run on one screen. The
                metrics entry wins: it shows the status and id, not just a label. */}
            <button type="button" className="btn-icon" aria-label="Refresh" onClick={() => void open(selected)}>
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        </div>
        {/* L0 — compact metrics (status already in subtitle). Every entry links to
            the section it summarises; a stat that reads like a link and isn't one is
            worse than no stat. */}
        <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-600">
          <div className="flex gap-1.5">
            <dt className="text-ink-400">Pipelines</dt>
            <dd>
              <button
                type="button"
                className="font-medium text-accent-800 hover:underline"
                title="Jump to the Continue list"
                onClick={() => jumpToCard('continue')}
              >
                {projectPipelines.length}
              </button>
            </dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="text-ink-400">Pinned inputs</dt>
            <dd>
              <button
                type="button"
                className="font-medium text-accent-800 hover:underline"
                title="Jump to Linked inputs"
                onClick={() => jumpToCard('inputs')}
              >
                {links.inputs.length}
              </button>
            </dd>
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
        <div className="mx-auto max-w-6xl space-y-6">
          {openError && <ErrorBanner message={openError} onRetry={() => void open(selected)} />}

          {workspaceEmpty && !openError && !opening ? (
            <section className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm">
                <h2 className="text-sm font-semibold text-ink-950">Start from template</h2>
                <p className="mt-1 flex-1 text-[12px] leading-relaxed text-ink-500">
                  Stamp starter GraphIR into this workspace, then edit and run in the Editor.
                </p>
                <button type="button" className="btn-secondary mt-3 w-full" onClick={goTemplates}>
                  Open Templates
                </button>
              </div>
              <div className="flex flex-col rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm">
                <h2 className="text-sm font-semibold text-ink-950">Link dataset</h2>
                <p className="mt-1 flex-1 text-[12px] leading-relaxed text-ink-500">
                  Upload or ingest shared Inputs under Datasets, then pin labels here for pipelines.
                </p>
                <button type="button" className="btn-secondary mt-3 w-full" onClick={goLinkDataset}>
                  Open Datasets
                </button>
              </div>
            </section>
          ) : null}

          {!pipelinesHintDismissed ? (
            <div
              role="note"
              className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-ink-200 bg-ink-50/80 px-3 py-2 text-[12px] leading-relaxed text-ink-700"
            >
              <p>
                <strong className="font-medium text-ink-900">Pipelines:</strong> Templates are starters
                · Project pipelines are the canonical saved graphs · Editor edits the active graph.
              </p>
              <button
                type="button"
                className="shrink-0 text-[11px] font-semibold text-ink-500 hover:text-ink-800"
                onClick={() => {
                  try {
                    localStorage.setItem('graphyn.home.pipelinesHint', '1')
                  } catch {
                    /* ignore */
                  }
                  setPipelinesHintDismissed(true)
                }}
              >
                Got it
              </button>
            </div>
          ) : null}

          {/* Activity feed */}
          <section>
            {/* Activity was the one section with no way out of it: eight rows, then
                nothing. Runs (full history + filters) and Artifacts (what those runs
                produced) are both one click from here now. */}
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className="ide-section-title">Activity</div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="ide-quiet-btn text-[11px]"
                  onClick={() => useAppStore.getState().openArtifacts({ project: selected })}
                >
                  Browse artifacts
                </button>
                <button
                  type="button"
                  className="ide-quiet-btn text-[11px]"
                  onClick={() => goView('runs')}
                >
                  View all in Runs
                  <ChevronRight className="h-3 w-3" />
                </button>
              </div>
            </div>
            <p className="mb-2 text-[12px] text-ink-500">
              {recentRuns.length >= 8
                ? 'Latest 8 runs — click a row to open it, or View all in Runs for the full history.'
                : 'Recent runs — click a row to open it.'}
            </p>
            <div className="overflow-hidden rounded-xl border border-ink-200/70 bg-white">
              {opening ? (
                <div className="px-4 py-5 text-[13px] text-ink-400">Loading…</div>
              ) : recentRuns.length === 0 && !schedules.some((s) => s.last_run_id) ? (
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
                        {r.status ? <StatusBadge status={r.status} /> : null}
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

          {/* Continue / Always-on / Linked inputs sit side-by-side on wide screens instead of
              stacking full-width one after another — this is a dashboard, not a document. */}
          <div className="grid gap-4 lg:grid-cols-3">
          {/* Layer 1 — continue work */}
          <section
            ref={continueRef}
            className={`flex flex-col rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm transition ${cardRing('continue')}`}
          >
            {/* Every card header now has the same shape — title left, one cross-link
                right — instead of Continue having none, Always-on having one and
                Linked inputs having an action plus a stat. */}
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="ide-section-title">Continue</div>
              <button type="button" className="ide-quiet-btn text-[11px]" onClick={goEditor}>
                Open Editor
              </button>
            </div>
            <p className="mb-2 text-[12px] text-ink-500">Open a pipeline in the Editor to keep working.</p>
            <div className="overflow-hidden rounded-xl border border-ink-200/70 bg-white">
              {opening ? (
                <div className="px-4 py-5 text-[13px] text-ink-400">Loading…</div>
              ) : projectPipelines.length === 0 ? (
                <div className="px-4 py-5 text-[13px] text-ink-600">
                  No pipelines yet.{' '}
                  <button type="button" className="font-medium text-accent-800 hover:underline" onClick={goTemplates}>
                    Start from a template
                  </button>
                  .
                </div>
              ) : (
                <ul className="divide-y divide-ink-100">
                  {sortedPipelines.slice(0, 8).map((p) => {
                    const envs = p.environments || {}
                    const pinned = pinnedPipelines.includes(p.name)
                    return (
                      <li key={p.name} className="px-3 py-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            className="shrink-0 rounded p-0.5 text-ink-300 hover:text-amber-500"
                            aria-label={pinned ? `Unpin ${p.name}` : `Pin ${p.name}`}
                            title={pinned ? 'Unpin favorite' : 'Pin favorite'}
                            onClick={() => togglePinPipeline(p.name)}
                          >
                            <Star
                              className={`h-3.5 w-3.5 ${pinned ? 'fill-amber-400 text-amber-500' : ''}`}
                            />
                          </button>
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
                              <p className="w-full text-[10px] text-ink-500">
                                Model prod approval is API-only (POST /models/.../request-prod | approve-prod).
                              </p>
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
                              <button
                                type="button"
                                className="btn-secondary !px-2 !py-0.5 text-[10px]"
                                onClick={() =>
                                  void rollbackPipeline(
                                    p.name,
                                    envs.staging || envs.prod || p.latest_version || undefined,
                                  )
                                }
                              >
                                Rollback
                              </button>
                            </div>
                          </details>
                        )}
                        {!(envs.staging || envs.prod || envs.pending_prod) && p.latest_version ? (
                          <div className="mt-1.5">
                            <button
                              type="button"
                              className="btn-secondary !px-2 !py-0.5 text-[10px]"
                              onClick={() => void rollbackPipeline(p.name, p.latest_version)}
                            >
                              Rollback draft
                            </button>
                          </div>
                        ) : null}
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </section>

          {/* Always-on — schedules filtered by project when possible */}
          <section className="flex flex-col rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="ide-section-title">Always-on</div>
              <button
                type="button"
                className="ide-quiet-btn text-[11px]"
                onClick={() => goView('system')}
              >
                Manage in Ops
              </button>
            </div>
            <div className="overflow-hidden rounded-xl border border-ink-200/70 bg-white">
              {(() => {
                const projectSchedules = schedules.filter((s) => String(s.project || '') === selected)
                if (projectSchedules.length === 0) {
                  return (
                    <div className="px-4 py-4 text-[13px] text-ink-500">
                      {schedules.length === 0
                        ? 'No schedules yet. Create them under Ops, or run on demand from the Editor.'
                        : `${schedules.length} schedule${schedules.length === 1 ? '' : 's'} on this API — none bound to this project.`}{' '}
                      <button
                        type="button"
                        className="font-medium text-accent-800 hover:underline"
                        onClick={() => goView('system')}
                      >
                        Open Ops
                      </button>
                    </div>
                  )
                }
                return (
                  <ul className="divide-y divide-ink-100">
                    {projectSchedules.slice(0, 6).map((s) => (
                      <li key={s.id || s.name} className="flex flex-wrap items-center gap-2 px-3 py-2">
                        <CalendarClock className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[13px] font-medium text-ink-900">{s.name || s.id}</div>
                          <div className="truncate text-[11px] text-ink-500">
                            {s.project}/{s.pipeline}
                            {s.interval_minutes != null ? ` · every ${s.interval_minutes}m` : ''}
                            {s.enabled === false ? ' · disabled' : ''}
                          </div>
                          {s.last_error ? (
                            <div className="mt-0.5 truncate text-[11px] text-rose-700" title={s.last_error}>
                              last_error: {s.last_error}
                            </div>
                          ) : null}
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
                    ))}
                  </ul>
                )
              })()}
            </div>
          </section>

          {/* Layer 2 — linked data (compact) */}
          <section
            ref={inputsRef}
            className={`flex flex-col rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm transition ${cardRing('inputs')}`}
          >
            {/* This card is entirely about Datasets input labels, yet its header
                action went to Artifacts (run *outputs*) while the Datasets link was
                buried as a tertiary button below the form. Swapped: the header links
                where the card points, and Artifacts moved up to Activity where the
                runs that produce them live. */}
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="ide-section-title">Linked inputs</div>
              <button
                type="button"
                className="ide-quiet-btn text-[11px]"
                onClick={() => openData({ mode: 'inputs' })}
              >
                Open Datasets
              </button>
            </div>
            <p className="mb-2 text-[12px] text-ink-500">
              Pin Datasets input labels here so Editor runs know which folders to use. Completing a run does not auto-link.
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
              {/* "Browse library" removed — it opened the same Datasets Inputs view
                  as the card header's "Open Datasets", one row apart. */}
            </div>
            {links.inputs.length === 0 && (
              <p className="mt-2 rounded-lg border border-dashed border-ink-200 bg-ink-50/50 px-3 py-2 text-[12px] text-ink-600">
                No inputs pinned yet. Pick a label above, or open Datasets and come back to Link.
              </p>
            )}
            {links.inputs.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {links.inputs.map((label) => (
                  <li key={label} className="inline-flex items-center gap-1 rounded-md bg-ink-50 px-2 py-0.5 text-[11px] text-ink-700">
                    <button
                      type="button"
                      className="hover:text-accent-800 hover:underline"
                      title="Open in Datasets"
                      onClick={() => openData({ mode: 'inputs', label })}
                    >
                      {label}
                    </button>
                    <button type="button" className="text-ink-400 hover:text-rose-600" onClick={() => void unlinkInput(label)} aria-label={`Unlink ${label}`}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          </div>

          {/* Layer 3 — advanced (collapsed by default).
              These two drawers were bare `border-t` rows on the page background while
              everything above them was a white card, so they read as page footer
              rather than content and were easy to scroll past without registering.
              They get the same card chrome as the rest of the dashboard, and their
              summaries say what is inside before you open them. */}
          <details
            className="group overflow-hidden rounded-2xl border border-ink-200/80 bg-white shadow-sm"
            open={datasetOpen}
            onToggle={(e) => setDatasetOpen((e.currentTarget as HTMLDetailsElement).open)}
          >
            <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-4 py-3 text-[13px] font-medium text-ink-800 hover:bg-ink-50/70">
              <ChevronRight className="h-4 w-4 shrink-0 text-ink-400 transition group-open:rotate-90" />
              Spec &amp; metadata
              <span className="font-normal text-ink-400">
                spec, taxonomy, contract, dataset versions, snapshots, diff
              </span>
              <span className="ml-auto flex shrink-0 items-center gap-1.5 text-[11px] text-ink-500">
                <span className="rounded-md bg-ink-100 px-1.5 py-0.5">
                  {versions.length} version{versions.length === 1 ? '' : 's'}
                </span>
                <span className="rounded-md bg-ink-100 px-1.5 py-0.5">
                  {snapshots.length} snapshot{snapshots.length === 1 ? '' : 's'}
                </span>
              </span>
            </summary>
            <div className="space-y-3 border-t border-ink-100 px-4 pb-4 pt-3">
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
                  {/* Load stats / Restore both silently no-op on an empty versionFocus (the
                      handlers guard on it), but with zero versions the select has nothing to
                      pick — showing them anyway meant a user could click "Restore" with nothing
                      selected and see it arm into the literal, broken-looking "Restore ?" (the
                      version name interpolates to nothing). Only show this toolbar once there's
                      something in it to select. */}
                  {versions.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      <select value={versionFocus} onChange={(e) => setVersionFocus(e.target.value)} className="rounded-md border border-ink-200 px-2 py-1.5 text-[12px]">
                        {versionOptions.map((v) => (
                          <option key={v} value={v}>{v}</option>
                        ))}
                      </select>
                      <button type="button" className="btn-secondary" onClick={() => void loadVersionDetail()}>Load stats</button>
                      <ConfirmButton label="Restore" confirmLabel={`Restore ${versionFocus}?`} onConfirm={() => void restoreVersion()} />
                    </div>
                  )}
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
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={!snapshotName.trim()}
                      title={!snapshotName.trim() ? 'Type a snapshot name first' : undefined}
                      onClick={() => void createSnapshot()}
                    >
                      Create
                    </button>
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
                  {/* Needs two versions to compare — with fewer, the selects have nothing
                      meaningful to offer and "Diff" would fire with empty version_a/version_b. */}
                  {versionOptions.length >= 2 ? (
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
                  ) : (
                    <p className="text-[13px] text-ink-500">Need at least 2 dataset versions to diff — run a pipeline that writes dataset output more than once.</p>
                  )}
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

          {/* Layer 4 — settings.
              Was a single undifferentiated flex row: a status select, two bare text
              inputs whose only labels were `aria-label` (so sighted users saw two
              identical prefilled boxes and had to infer which was Rename and which
              was Clone from the button beside it), and Delete sitting in the same
              row as everything else. Each action is now its own labelled row, and
              the destructive one is separated out. */}
          <details className="group overflow-hidden rounded-2xl border border-ink-200/80 bg-white shadow-sm">
            <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-4 py-3 text-[13px] font-medium text-ink-800 hover:bg-ink-50/70">
              <ChevronRight className="h-4 w-4 shrink-0 text-ink-400 transition group-open:rotate-90" />
              Project settings
              <span className="font-normal text-ink-400">status, rename, clone, delete</span>
              <span className="ml-auto shrink-0 rounded-md bg-ink-100 px-1.5 py-0.5 text-[11px] text-ink-500">
                {statusVal}
              </span>
            </summary>
            <div className="border-t border-ink-100 px-4 pb-4 pt-3">
              <div className="grid gap-3 sm:max-w-xl">
                <label className="grid grid-cols-[6rem_minmax(0,1fr)] items-center gap-2 text-[12px] text-ink-500">
                  Status
                  <select
                    className="w-full rounded-md border border-ink-200 bg-white px-2 py-1 text-[12px] text-ink-800"
                    value={statusVal}
                    onChange={(e) => void setStatus(e.target.value)}
                  >
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <div className="grid grid-cols-[6rem_minmax(0,1fr)] items-center gap-2 text-[12px] text-ink-500">
                  <label htmlFor="ws-rename-to">Rename to</label>
                  <div className="flex min-w-0 gap-2">
                    <input
                      id="ws-rename-to"
                      value={renameTo}
                      onChange={(e) => setRenameTo(e.target.value)}
                      className="min-w-0 flex-1 rounded-md border border-ink-200 px-2 py-1 text-[12px]"
                    />
                    <button
                      type="button"
                      className="btn-secondary shrink-0"
                      disabled={!renameTo.trim() || renameTo.trim() === selected}
                      title={
                        !renameTo.trim()
                          ? 'Enter a name first'
                          : renameTo.trim() === selected
                            ? 'That is already the current name'
                            : undefined
                      }
                      onClick={() => void rename()}
                    >
                      <Pencil className="h-3.5 w-3.5" /> Rename
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-[6rem_minmax(0,1fr)] items-center gap-2 text-[12px] text-ink-500">
                  <label htmlFor="ws-clone-to">Clone as</label>
                  <div className="flex min-w-0 gap-2">
                    <input
                      id="ws-clone-to"
                      value={cloneTo}
                      onChange={(e) => setCloneTo(e.target.value)}
                      className="min-w-0 flex-1 rounded-md border border-ink-200 px-2 py-1 text-[12px]"
                    />
                    <button
                      type="button"
                      className="btn-secondary shrink-0"
                      disabled={!cloneTo.trim() || cloneTo.trim() === selected}
                      title={
                        !cloneTo.trim()
                          ? 'Enter a name first'
                          : cloneTo.trim() === selected
                            ? 'Pick a different name for the copy'
                            : undefined
                      }
                      onClick={() => void clone()}
                    >
                      <Copy className="h-3.5 w-3.5" /> Clone
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-[6rem_minmax(0,1fr)] items-center gap-2 text-[12px] text-ink-500">
                  <span>Deploy</span>
                  <div>
                    <button type="button" className="btn-secondary" onClick={useInEdge}>
                      Use in Ship
                    </button>
                  </div>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-rose-200 bg-rose-50/50 px-3 py-2.5">
                {/* Scope verified against ProjectManager.delete: it rmtree's
                    workspace/datasets/output/{name} only — artifacts under
                    workspace/artifacts/{name}/runs are a separate tree and survive. */}
                <p className="text-[12px] text-rose-900">
                  <span className="font-medium">Delete this workspace.</span> Removes its pipelines,
                  spec/taxonomy/contract, links and dataset output versions. Artifacts and run
                  history are kept.
                </p>
                <ConfirmButton
                  label="Delete"
                  confirmLabel={`Delete ${selected}?`}
                  danger
                  onConfirm={() => void remove()}
                />
              </div>
            </div>
          </details>
        </div>
      </div>
    </div>
  )
}
