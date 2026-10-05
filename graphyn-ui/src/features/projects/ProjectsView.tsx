import React from 'react'
import {
  RefreshCw,
  Archive,
  ArchiveRestore,
  Copy,
  Database,
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
  FolderOpen as EmptyFolderOpen,
  SearchX as EmptySearchX,
  History as EmptyHistory,
} from 'lucide-react'
import { apiJson } from '../../api/client'
import { unwrapList } from '../../api/unwrapList'
import { useAppStore } from '../../store/appStore'
import {
  ConfirmButton,
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  StatusBadge,
} from '../../components/ui'
import { paths } from '../../routes/paths'
import { goView, guardedNavigatePath, onPathChange, readSearchParams, replacePathSearch } from '../../routes/nav'
import { formatRelativeTime, shortRunId } from '../../lib/format'
import { runDisplayName } from '../../lib/runDisplay'
import {
  activityDetail,
  buildActivityItems,
  homeSummaryLine,
  isExceptionStatus,
  runStatusWord,
  workspaceStatusLabel,
} from './homeActivity'
import { pickLatestResult, regressionTone } from './latestResult'
import { formatMetric, formatMetricDelta, formatMetricValue, isRatioMetric, metricLabel, primaryMetric } from '../../lib/metrics'
import {
  forgetRecentWorkspace,
  noteRecentWorkspace,
  readRecentWorkspaces,
} from '../../lib/recentWorkspaces'
import { useMenuDismiss } from '../../lib/menus'
import { checkRunExists } from '../../lib/runExists'
import {
  isValidWorkspaceName,
  WORKSPACE_NAME_HINT,
  workspaceErrorMessage,
  workspaceNameError,
} from '../../lib/workspaceName'
import {
  CLONE_SCOPE_TEXT,
  deleteWorkspaceSummary,
  isArchivedWorkspace,
  partitionArchived,
  showsWorkspaceId,
  workspaceTitle,
} from './workspaceAdmin'

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
  /** UX API: human title + summary (primary metric) + regression vs best previous. */
  display_name?: string
  summary?: Record<string, unknown> | null
  regression?: Record<string, unknown> | null
  metrics?: Record<string, unknown> | null
}

/** "Test accuracy 0.561" for a run row, or null. */
function runMetricText(r: unknown): string | null {
  const pm = primaryMetric(r)
  if (!pm) return null
  return `${metricLabel(pm.name)} ${formatMetricValue(pm.name, pm.value)}`
}

/** Runs fetched for Home: enough to collapse repeated failures and still fill
 *  the 8-row Activity list; the header shows "N+ runs" when the cap is hit. */
const HOME_RUNS_LIMIT = 30
const HOME_ACTIVITY_ROWS = 8
/** Sentence-case section title (replaces the ALL-CAPS `ide-section-title`). */
const SECTION_TITLE = 'text-[13px] font-semibold text-ink-900'

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


function parseProjectsLocation(): { project?: string } {
  const { pathname } = window.location
  const params = readSearchParams()
  const parts = pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  let project: string | undefined
  if (parts[0] === 'workspaces' && parts[1]) {
    project = decodeURIComponent(parts[1])
  } else {
    project = (params.get('project') || '').trim() || undefined
  }
  return { project }
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
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const initialLoc = React.useMemo(() => parseProjectsLocation(), [])
  const [projects, setProjects] = React.useState<Project[] | null>(null)
  const [selected, setSelected] = React.useState<string | null>(initialLoc.project ?? null)
  const [newName, setNewName] = React.useState('')
  const newNameError = workspaceNameError(newName)
  const nameRef = React.useRef<HTMLInputElement | null>(null)
  /** Workspaces list: the "New workspace" inline form is opened by a button. */
  const [createOpen, setCreateOpen] = React.useState(false)
  React.useEffect(() => {
    if (createOpen) nameRef.current?.focus()
  }, [createOpen])
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
  // Workspace whose Home payload (runs, pipelines, schedules, links) finished
  // loading. Until it equals `selected` the page shows skeletons — never zeros.
  const [homeLoadedFor, setHomeLoadedFor] = React.useState<string | null>(null)
  // Collapsed "Set up" row → user asked to choose datasets: show the full card.
  const [showInputsCard, setShowInputsCard] = React.useState(false)
  // Activity "N more failed runs" groups the user expanded (by group key).
  const [expandedFailures, setExpandedFailures] = React.useState<Set<string>>(() => new Set())

  // Monotonic open() request id — results of superseded opens are dropped.
  const openSeqRef = React.useRef(0)
  /** GET /projects/{name}: display name, description, status of the open workspace. */
  const [wsMeta, setWsMeta] = React.useState<{
    display_name?: string
    description?: string
    status?: string
  } | null>(null)
  const [nameDraft, setNameDraft] = React.useState('')
  const [descDraft, setDescDraft] = React.useState('')
  const [deleteConfirm, setDeleteConfirm] = React.useState('')
  /** Workspace fold (name, archive, clone, danger zone) — controlled so the
   *  list's "Delete…" can open it at the danger zone. */
  const [workspaceFoldOpen, setWorkspaceFoldOpen] = React.useState(false)
  const [revealDanger, setRevealDanger] = React.useState(false)
  const dangerZoneRef = React.useRef<HTMLDivElement>(null)
  /** Dataset output versions of this workspace — only counted for the delete scope. */
  const [datasetVersionCount, setDatasetVersionCount] = React.useState(0)
  const [recentRuns, setRecentRuns] = React.useState<RunRow[]>([])
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
  const [links, setLinks] = React.useState<{ inputs: string[] }>({ inputs: [] })
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
      const rows = unwrapList<RunRow>(await apiJson('/runs', { query: { limit: 60, offset: 0 } }))
      setAllRuns(rows.filter((r) => r && typeof r.run_id === 'string'))
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

  /* Registered models — the Home "Latest result" card links a run to the
     model registered from it. Non-blocking; absent registry → no link. */
  const [homeModels, setHomeModels] = React.useState<
    Array<{ name: string; stages?: Record<string, { run_id?: string; source_run_id?: string } | null> }>
  >([])
  React.useEffect(() => {
    if (!selected) return
    let cancelled = false
    apiJson<{ models?: unknown }>('/models')
      .then((r) => {
        if (cancelled) return
        const list = Array.isArray(r?.models) ? r.models : unwrapList(r)
        setHomeModels(
          list.filter(
            (m): m is { name: string } => !!m && typeof (m as { name?: unknown }).name === 'string',
          ),
        )
      })
      .catch(() => {
        if (!cancelled) setHomeModels([])
      })
    return () => {
      cancelled = true
    }
  }, [selected])

  // List "Delete…": once that workspace is open, expand its Workspace fold and
  // bring the danger zone (typed-name confirmation) into view.
  React.useEffect(() => {
    if (!revealDanger || !selected) return
    setWorkspaceFoldOpen(true)
    const id = window.setTimeout(() => {
      if (!dangerZoneRef.current) return
      dangerZoneRef.current.scrollIntoView({ block: 'center', behavior: 'smooth' })
      dangerZoneRef.current.querySelector('input')?.focus({ preventScroll: true })
      setRevealDanger(false)
    }, 150)
    return () => window.clearTimeout(id)
  }, [revealDanger, selected, wsMeta])

  const open = async (name: string) => {
    const seq = ++openSeqRef.current
    const stale = () => seq !== openSeqRef.current
    noteRecentWorkspace(name)
    setSelected(name)
    setActiveProject(name)
    setCloneTo(`${name}-copy`)
    setDeleteConfirm('')
    setOpenError(null)
    setOpening(true)
    setShowInputsCard(false)
    replacePathSearch({}, paths.workspace(name))
    try {
      const [meta, vers] = await Promise.all([
        apiJson<{ display_name?: string; description?: string; status?: string; name?: string }>(
          `/projects/${encodeURIComponent(name)}`,
        ),
        apiJson<unknown[]>(`/projects/${encodeURIComponent(name)}/versions`).catch(() => []),
      ])
      if (stale()) return
      setWsMeta(meta)
      setNameDraft(workspaceTitle({ name, display_name: meta?.display_name }))
      setDescDraft(String(meta?.description ?? ''))
      setDatasetVersionCount(Array.isArray(vers) ? vers.length : 0)
      try {
        const [runs, linkData, inputs, pipes, sched] = await Promise.all([
          apiJson<unknown>('/runs', {
            query: { limit: HOME_RUNS_LIMIT, offset: 0, project: name },
          }).catch(() => []),
          apiJson<{ inputs?: string[] }>(`/projects/${encodeURIComponent(name)}/links`).catch(() => ({ inputs: [] })),
          apiJson<unknown>('/data/inputs')
            .then((raw) => unwrapList(raw) as Array<{ label?: string } | string>)
            .catch(() => []),
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
          apiJson<{ schedules?: unknown[] }>('/system/schedules', { query: { project: name } }).catch(() => ({
            schedules: [],
          })),
        ])
        if (stale()) return
        setRecentRuns(
          unwrapList<RunRow>(runs)
            .filter((r) => r && typeof r.run_id === 'string')
            .slice(0, HOME_RUNS_LIMIT),
        )
        setProjectPipelines(unwrapList<(typeof projectPipelines)[number]>(pipes).filter((p) => p && typeof p.name === 'string'))
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
          // Server filters by ?project=; keep a client filter too so a schedule of
          // another (possibly deleted) workspace can never show up on this Home.
          setSchedules(typed.filter((s) => String(s.project || '') === name))
        }
        setLinks({
          inputs: Array.isArray(linkData?.inputs) ? linkData.inputs : [],
        })
        const labels = (Array.isArray(inputs) ? inputs : [])
          .map((x) => {
            if (typeof x === 'string') return { label: x, accessible: true as boolean | undefined }
            const label = String(x?.label ?? '').trim()
            if (!label) return null
            const accessible = (x as { accessible?: boolean }).accessible
            return { label, accessible }
          })
          .filter((x): x is { label: string; accessible: boolean | undefined } => Boolean(x))
          .filter((x) => x.accessible !== false)
          .map((x) => x.label)
        setInputLabels(labels)
        setLinkPick(labels.find((l) => !(linkData?.inputs || []).includes(l)) || labels[0] || '')
      } catch {
        if (stale()) return
        setRecentRuns([])
        setProjectPipelines([])
        setSchedules([])
        setLinks({ inputs: [] })
      }
    } catch (err) {
      if (stale()) return
      setOpenError(err instanceof Error ? err.message : String(err))
      // Keep selected, but clear Home payload so we don't pretend load succeeded.
      setWsMeta(null)
      setDatasetVersionCount(0)
      setRecentRuns([])
      setProjectPipelines([])
      setSchedules([])
      setLinks({ inputs: [] })
    } finally {
      if (!stale()) {
        setOpening(false)
        setHomeLoadedFor(name)
      }
    }
  }

  React.useEffect(() => {
    const apply = () => {
      const h = parseProjectsLocation()
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

  /** The Editor loads it by name, so its toolbar keeps the pipeline + Draft/staging/prod link. */
  const openProjectPipeline = (pipelineName: string, env?: 'staging' | 'prod') => {
    if (!selected) return
    useAppStore.getState().openPipelineInEditor(pipelineName, env)
  }

  const publishPipeline = async (pipelineName: string, setEnv?: 'staging' | 'prod') => {
    if (!selected) return
    try {
      const res = await apiJson<{ version?: string; status?: string }>(
        `/projects/${encodeURIComponent(selected)}/pipelines/${encodeURIComponent(pipelineName)}/publish`,
        {
          method: 'POST',
          body: JSON.stringify({
            message: 'Published from workspace Home',
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

  /** Schedule rows link to their last run only while it still exists; otherwise Ops → Schedules. */
  const openScheduleRun = async (s: { last_run_id?: string; name?: string; id?: string }) => {
    const rid = String(s.last_run_id || '')
    if (!rid) return
    try {
      const found = await checkRunExists(rid)
      if (found.exists) {
        useAppStore.getState().openRun(rid, selected ? { project: selected } : undefined)
        return
      }
    } catch {
      /* fall through to Ops */
    }
    pushToast(`Run ${shortRunId(rid)} no longer exists — showing the schedule in Ops`, 'info')
    goView('system')
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
      pushToast('Enter a workspace name first', 'error')
      nameRef.current?.focus()
      return
    }
    if (!isValidWorkspaceName(newName)) {
      nameRef.current?.focus()
      return
    }
    try {
      const created = newName.trim()
      await apiJson('/projects', { method: 'POST', body: JSON.stringify({ name: created }) })
      pushToast(`Created ${created}`, 'success')
      setActiveProject(created)
      setNewName('')
      setCreateOpen(false)
      await load()
      await open(created)
    } catch (err) {
      pushToast(workspaceErrorMessage(err instanceof Error ? err.message : String(err)), 'error')
    }
  }

  /** PUT display_name / description (the workspace id never changes). */
  const saveDetails = async () => {
    if (!selected) return
    const body: Record<string, string> = {}
    const name = nameDraft.trim()
    if (name && name !== workspaceTitle({ name: selected, display_name: wsMeta?.display_name })) {
      body.display_name = name
    }
    if (descDraft.trim() !== String(wsMeta?.description ?? '').trim()) body.description = descDraft.trim()
    if (!Object.keys(body).length) return
    try {
      const next = await apiJson<{ display_name?: string; description?: string; status?: string }>(
        `/projects/${encodeURIComponent(selected)}`,
        { method: 'PUT', body: JSON.stringify(body) },
      )
      setWsMeta(next)
      pushToast('Workspace details saved', 'success')
      await load()
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
      pushToast(`Created ${cloneTo.trim()} from ${selected}`, 'success')
      await load()
    } catch (err) {
      pushToast(workspaceErrorMessage(err instanceof Error ? err.message : String(err)), 'error')
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
      pushToast(workspaceErrorMessage(err instanceof Error ? err.message : String(err)), 'error')
    }
  }

  /** Archive hides the workspace from the default Workspaces list; nothing is deleted. */
  const setArchived = async (archived: boolean) => {
    if (!selected) return
    try {
      const next = await apiJson<{ status?: string }>(`/projects/${encodeURIComponent(selected)}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status: archived ? 'archived' : 'in-progress' }),
      })
      setWsMeta((m) => ({ ...(m ?? {}), status: next?.status ?? (archived ? 'archived' : 'in-progress') }))
      pushToast(archived ? `Archived ${selected}` : `Unarchived ${selected}`, 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const remove = async () => {
    if (!selected || deleteConfirm.trim() !== selected) return
    const name = selected
    try {
      await apiJson(`/projects/${encodeURIComponent(name)}`, {
        method: 'DELETE',
        body: JSON.stringify({ confirm: name }),
      })
      pushToast(`Deleted ${name}`, 'success')
      forgetRecentWorkspace(name)
      if (useAppStore.getState().activeProject === name) setActiveProject(null)
      setSelected(null)
      replacePathSearch({}, paths.workspaces())
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const linkInput = async () => {
    if (!selected || !linkPick.trim()) return
    try {
      const next = await apiJson<{ inputs?: string[] }>(
        `/projects/${encodeURIComponent(selected)}/links`,
        { method: 'POST', body: JSON.stringify({ inputs: [linkPick.trim()] }) },
      )
      setLinks({ inputs: Array.isArray(next.inputs) ? next.inputs : [] })
      pushToast(
        `Pinned “${linkPick.trim()}” — set the ingest path in the Editor (Linked picker) to use it in a run`,
        'success',
      )
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const unlinkInput = async (label: string) => {
    if (!selected) return
    try {
      const next = await apiJson<{ inputs?: string[] }>(
        `/projects/${encodeURIComponent(selected)}/links`,
        { method: 'DELETE', body: JSON.stringify({ inputs: [label] }) },
      )
      setLinks({ inputs: Array.isArray(next.inputs) ? next.inputs : [] })
      pushToast(`Removed "${label}"`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const [showArchived, setShowArchived] = React.useState(false)
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
  const closeCardMenu = React.useCallback(() => setCardMenu(null), [])
  // Escape / outside click / another menu opening closes the row ⋯ menu.
  useMenuDismiss(Boolean(cardMenu), closeCardMenu, cardMenuRef)
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

  /* Archived workspaces are hidden from the list unless "Show archived" is on. */
  const { visible: unarchivedProjects, archivedCount } = React.useMemo(
    () => partitionArchived(projects ?? [], showArchived),
    [projects, showArchived],
  )
  const filteredProjects = React.useMemo(() => {
    const q = projectFilter.trim().toLowerCase()
    if (!q) return unarchivedProjects
    return unarchivedProjects.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        workspaceTitle(p).toLowerCase().includes(q) ||
        String(p.status || '')
          .toLowerCase()
          .includes(q),
    )
  }, [unarchivedProjects, projectFilter])

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
          <div className="text-[12px] font-medium text-ink-500">
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
      /* Only "Archived" changes behaviour (hidden from this list by default), so
         it is the only status that earns a chip; the legacy draft / in-progress /
         ready values are no longer editable and would just be noise. */
      if (!isArchivedWorkspace({ status: raw })) return null
      return (
        <span className="shrink-0 rounded-md bg-amber-50 px-1.5 py-px text-[11px] font-medium text-amber-800">
          Archived
        </span>
      )
    }

    /* Display name first; the id (URLs, runs, audit) muted when it differs. */
    const idHint = (p: Project) =>
      showsWorkspaceId(p) ? (
        <span className="ml-1.5 font-mono text-[11px] font-normal text-ink-400">{p.name}</span>
      ) : null

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
              {/* Same typed-name confirmation as Home's danger zone (deleting
                  removes the workspace's dataset versions), not a 2-click confirm. */}
              <button
                type="button"
                role="menuitem"
                className="block w-full rounded-md px-2 py-1.5 text-left text-[12px] text-rose-700 hover:bg-rose-50"
                onClick={() => {
                  setCardMenu(null)
                  setRevealDanger(true)
                  void open(p.name)
                }}
              >
                Delete…
              </button>
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
          className="relative z-10 flex w-full min-w-0 max-w-full items-center gap-1.5 overflow-hidden text-left text-[12px] text-ink-600 hover:text-accent-800"
          title={`Open run ${r.run_id} — ${runDisplayName(r)}${runMetricText(r) ? ` · ${runMetricText(r)}` : ''}`}
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
            {runDisplayName(r)}
            {runMetricText(r) ? ` · ${runMetricText(r)}` : ''} · {formatRelativeTime(r.created_at)}
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
      <div className="flex h-full min-h-0 flex-col bg-white">
        <div className="shrink-0 border-b border-ink-200/80 bg-white px-4 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <h1 className="text-[15px] font-semibold leading-tight tracking-tight text-ink-950">
                Workspaces
              </h1>
              <p className="mt-0.5 max-w-2xl text-type-meta text-ink-500">
                Open a workspace for Editor and Runs. Each holds pipelines, datasets, and run history.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
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
              <button
                type="button"
                className="btn-primary"
                aria-expanded={createOpen}
                onClick={() => {
                  if (createOpen) nameRef.current?.focus()
                  else setCreateOpen(true)
                }}
              >
                <Plus className="h-3.5 w-3.5" /> New workspace
              </button>
            </div>
          </div>
        </div>
        <div className="workbench-scroll space-y-4">

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

          {projects != null && list.length > 0 && list.length < 5 ? (
            // Few workspaces: one summary line instead of four KPI cards.
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-ink-500">
              <span>
                {list.length} workspace{list.length === 1 ? '' : 's'}
              </span>
              {allRuns ? (
                <>
                  <span aria-hidden>·</span>
                  {failedCount ? (
                    <button
                      type="button"
                      className={`font-medium underline-offset-2 hover:underline ${
                        activityFilter === 'failed' ? 'text-rose-800' : 'text-rose-700'
                      }`}
                      aria-pressed={activityFilter === 'failed'}
                      title={activityFilter === 'failed' ? 'Showing only failed runs — click to clear' : 'Show only failed runs in activity'}
                      onClick={() => setActivityFilter((f) => (f === 'failed' ? 'all' : 'failed'))}
                    >
                      {failedCount} failed run{failedCount === 1 ? '' : 's'}
                    </button>
                  ) : (
                    <span>nothing failing</span>
                  )}
                  <span aria-hidden>·</span>
                  <span>
                    {newestRun
                      ? `last activity ${formatRelativeTime(newestRun.created_at)}${newestRun.project ? ` in ${newestRun.project}` : ''}`
                      : 'no runs yet'}
                  </span>
                </>
              ) : null}
            </p>
          ) : null}

          {projects != null && list.length >= 5 ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {statTile(
              'Workspaces',
              loading || projects == null ? '—' : list.length,
              recentNames.length ? `${recentNames.length} opened recently` : 'None opened yet',
            )}
            {/* Was "Active = runsByProject.size", which also counted runs tagged
                with deleted / unlisted workspaces — so "Active 3" could exceed
                "Workspaces 2". Count only listed workspaces with a recent run. */}
            {statTile(
              'With recent runs',
              allRuns && projects != null ? list.filter((p) => runsByProject.has(p.name)).length : '—',
              projects != null ? `of ${list.length} workspace${list.length === 1 ? '' : 's'}` : undefined,
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
          ) : null}

          {/* New workspace: inline form opened from the header button (or the
              empty state), so the list comes first. */}
          {createOpen ? (
          <div className="rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-end gap-2">
              <label className="min-w-0 flex-1 basis-56 text-[12px] font-medium text-ink-600">
                New workspace
                <input
                  ref={nameRef}
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="my-workspace"
                  maxLength={160}
                  aria-invalid={newNameError ? true : undefined}
                  aria-describedby="new-workspace-hint"
                  className={`mt-1 w-full rounded-lg border px-3 py-2 text-sm ${
                    newNameError ? 'border-rose-300 bg-rose-50/40 focus:border-rose-400' : 'border-ink-200'
                  }`}
                  onKeyDown={(e) => e.key === 'Enter' && !newNameError && void create()}
                />
              </label>
              <button
                type="button"
                className="btn-primary mb-px"
                disabled={!newName.trim() || Boolean(newNameError)}
                title={
                  !newName.trim()
                    ? 'Type a name first'
                    : newNameError
                      ? newNameError
                      : `Create ${newName.trim()}`
                }
                onClick={() => void create()}
              >
                <Plus className="h-3.5 w-3.5" /> Create workspace
              </button>
              <button
                type="button"
                className="btn-quiet mb-px"
                onClick={() => {
                  setCreateOpen(false)
                  setNewName('')
                }}
              >
                Cancel
              </button>
            </div>
            <p
              id="new-workspace-hint"
              className={`mt-1.5 text-[12px] ${newNameError ? 'text-rose-700' : 'text-ink-400'}`}
              role={newNameError ? 'alert' : undefined}
            >
              {newNameError ?? WORKSPACE_NAME_HINT}
            </p>
            <p className="mt-2 text-[12px] text-ink-400">
              Created empty and opened immediately. Templates and Datasets are shared across
              workspaces, so you can look at those before picking one.
            </p>
          </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-0 flex-1 basis-48 sm:max-w-sm">
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
            {archivedCount > 0 ? (
              <label className="flex items-center gap-1.5 text-[12px] text-ink-500">
                <input
                  type="checkbox"
                  checked={showArchived}
                  onChange={(e) => setShowArchived(e.target.checked)}
                />
                Show archived ({archivedCount})
              </label>
            ) : null}
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_21rem]">
            <section className="min-w-0">
              {loading || projects == null ? (
                <LoadingBlock label="Loading workspaces…" />
              ) : list.length === 0 ? (
                <EmptyState
                  icon={EmptyFolderOpen}
                  title="No workspaces yet"
                  description={
                    authBlocked
                      ? 'Sign in via Settings to list workspaces.'
                      : 'Create one to start building pipelines, or open a template to see how one is put together.'
                  }
                  action={
                    <>
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => {
                          if (createOpen) nameRef.current?.focus()
                          else setCreateOpen(true)
                        }}
                      >
                        <Plus className="h-3.5 w-3.5" /> New workspace
                      </button>
                      <button type="button" className="btn-secondary" onClick={goTemplates}>
                        Browse templates
                      </button>
                    </>
                  }
                />
              ) : sorted.length === 0 && !projectFilter.trim() ? (
                <EmptyState
                  icon={Archive}
                  title="All workspaces are archived"
                  description="Archived workspaces are hidden from this list. Their runs, models and pipelines are untouched."
                  action={
                    <button type="button" className="btn-secondary" onClick={() => setShowArchived(true)}>
                      Show archived ({archivedCount})
                    </button>
                  }
                />
              ) : sorted.length === 0 ? (
                <EmptyState
                  icon={EmptySearchX}
                  title="No matching workspaces"
                  description={`No workspaces match “${projectFilter.trim()}”.`}
                  action={
                    <button type="button" className="btn-secondary" onClick={() => setProjectFilter('')}>
                      Clear search
                    </button>
                  }
                />
              ) : dense ? (
                <ul className="divide-y divide-ink-100 rounded-2xl border border-ink-200/80 bg-white shadow-sm">
                  {sorted.map((p) => (
                    <li
                      key={p.name}
                      className="group relative flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 transition first:rounded-t-2xl last:rounded-b-2xl hover:bg-ink-50/70"
                    >
                      <button
                        type="button"
                        className="min-w-0 flex-1 truncate text-left text-[13px] font-medium text-ink-900 after:absolute after:inset-0 after:content-[''] group-hover:text-accent-800"
                        onClick={() => void open(p.name)}
                      >
                        {workspaceTitle(p)}
                        {idHint(p)}
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
                      className="group relative flex min-w-0 flex-col rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm transition hover:border-accent-300 hover:shadow-soft"
                    >
                      <div className="flex items-start gap-2">
                        <div className="min-w-0 flex-1">
                          {/* Stretched-link pattern: the title is the real button
                              and its ::after covers the card, so the whole card is
                              clickable without nesting interactive elements. */}
                          <button
                            type="button"
                            className="block w-full truncate text-left text-[14px] font-semibold text-ink-950 after:absolute after:inset-0 after:content-[''] group-hover:text-accent-800"
                            title={showsWorkspaceId(p) ? `${workspaceTitle(p)} (${p.name})` : p.name}
                            onClick={() => void open(p.name)}
                          >
                            {workspaceTitle(p)}
                            {idHint(p)}
                          </button>
                          <div className="mt-1 flex flex-wrap items-center gap-1.5">
                            {recentRank.has(p.name) ? (
                              <span className="inline-flex items-center gap-1 rounded-md bg-accent-50 px-1.5 py-px text-[11px] font-medium text-accent-800">
                                <Clock className="h-2.5 w-2.5" /> Recent
                              </span>
                            ) : null}
                            {statusChip(p.status)}
                          </div>
                        </div>
                        {cardMenuFor(p)}
                      </div>
                      <div className="mt-3 min-w-0 border-t border-ink-100 pt-2.5">
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
                  <div className={SECTION_TITLE}>Recent activity</div>
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
                  <div className="px-2 py-3">
                    <EmptyState
                      compact
                      icon={EmptyHistory}
                      title={
                        activityFilter === 'failed'
                          ? 'No failed runs'
                          : 'No activity yet'
                      }
                      description={
                        activityFilter === 'failed'
                          ? 'Nothing failed in recent history across workspaces.'
                          : 'Runs from any workspace appear here once recorded.'
                      }
                    />
                  </div>
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
                            <span className="block truncate text-[12px] font-medium text-ink-900" title={`Run ${r.run_id}`}>
                              {runDisplayName(r)}
                            </span>
                            <span className="block truncate text-[11px] text-ink-500">
                              {r.project}
                              {runMetricText(r) ? ` · ${runMetricText(r)}` : ''} · {formatRelativeTime(r.created_at)}
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
  const listedMeta = projects?.find((p) => p.name === selected)
  const statusVal = normalizeProjectStatus(wsMeta?.status ?? listedMeta?.status)
  const archived = statusVal === 'archived'
  const wsTitle = workspaceTitle({ name: selected, display_name: wsMeta?.display_name ?? listedMeta?.display_name })
  const detailsDirty =
    (nameDraft.trim() !== '' && nameDraft.trim() !== wsTitle) ||
    descDraft.trim() !== String(wsMeta?.description ?? '').trim()
  const deleteScope = deleteWorkspaceSummary({
    pipelines: projectPipelines.length,
    datasetVersions: datasetVersionCount,
    schedules: schedules.filter((sc) => String(sc.project || '') === selected).length,
    linkedInputs: links.inputs.length,
  })
  const lastRun = recentRuns[0]
  const stagingHint = projectPipelines.find((p) => p.environments?.staging)?.environments?.staging
  const prodHint = projectPipelines.find((p) => p.environments?.prod)?.environments?.prod
  // Skeleton until this workspace's Home payload has loaded — no misleading
  // "0 pipelines" / "Getting started" flash while fetching.
  const homeLoading = opening || homeLoadedFor !== selected
  const statusWord = workspaceStatusLabel(statusVal, recentRuns.length > 0, homeLoading)
  const summaryCounts = homeSummaryLine({
    pipelines: projectPipelines.length,
    runs: recentRuns.length,
    runsCapped: recentRuns.length >= HOME_RUNS_LIMIT,
  })
  const projectSchedules = schedules.filter((s) => String(s.project || '') === selected)
  const setupCollapsed = !homeLoading && projectSchedules.length === 0 && links.inputs.length === 0 && !showInputsCard

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="shrink-0 border-b border-ink-200/80 bg-white px-4 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2">
              <h1
                className="truncate text-[15px] font-semibold leading-tight tracking-tight text-ink-950"
                title={wsMeta?.description ? String(wsMeta.description) : undefined}
              >
                {wsTitle}
              </h1>
              {wsTitle !== selected ? (
                <span className="shrink-0 font-mono text-[11px] text-ink-400" title="Workspace id">
                  {selected}
                </span>
              ) : null}
              {archived ? (
                <span
                  className="shrink-0 rounded-md bg-amber-50 px-1.5 py-px text-[11px] font-medium text-amber-800"
                  title="Archived — hidden from the Workspaces list. Unarchive under Workspace below."
                >
                  Archived
                </span>
              ) : statusWord ? (
                <span className="shrink-0 rounded-md bg-ink-100 px-1.5 py-px text-[11px] font-medium text-ink-600">
                  {statusWord}
                </span>
              ) : null}
            </div>
            {/* One summary line: "N pipelines · M runs · last run <name> <status> <time>".
                Pipeline versions and datasets in use live in the tooltip. */}
            {homeLoading ? (
              <div className="mt-1 h-3.5 w-72 max-w-full animate-pulse rounded bg-ink-100" aria-label="Loading workspace summary" />
            ) : (
              <p
                className="mt-0.5 truncate text-type-meta text-ink-500"
                title={[
                  stagingHint || prodHint
                    ? `Pipeline versions: ${[stagingHint ? `staging ${stagingHint}` : '', prodHint ? `production ${prodHint}` : ''].filter(Boolean).join(' · ')}`
                    : '',
                  links.inputs.length ? `Datasets in use: ${links.inputs.join(', ')}` : '',
                ]
                  .filter(Boolean)
                  .join('\n') || undefined}
              >
                <button type="button" className="hover:text-accent-800 hover:underline" onClick={() => jumpToCard('continue')}>
                  {summaryCounts}
                </button>
                {lastRun ? (
                  <>
                    {' · '}
                    <button
                      type="button"
                      className="hover:text-accent-800 hover:underline"
                      title={`Run ${lastRun.run_id}`}
                      onClick={openLastRun}
                    >
                      last run <span className="font-medium text-ink-800">{runDisplayName(lastRun)}</span>{' '}
                      <span
                        className={
                          runStatusWord(lastRun.status) === 'Failed'
                            ? 'font-medium text-rose-700'
                            : isExceptionStatus(lastRun.status)
                              ? 'font-medium text-amber-800'
                              : ''
                        }
                      >
                        {runStatusWord(lastRun.status)}
                      </span>
                      {lastRun.created_at ? ` ${formatRelativeTime(lastRun.created_at)}` : ''}
                    </button>
                  </>
                ) : null}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <button type="button" className="btn-primary" onClick={goEditor}>
              <Workflow className="h-3.5 w-3.5" /> Open Editor
            </button>
            <button type="button" className="btn-secondary" onClick={goTemplates}>
              From template
            </button>
            <button type="button" className="btn-icon" aria-label="Refresh" onClick={() => void open(selected)}>
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5">
        <div className="mx-auto max-w-6xl space-y-6">
          {openError && <ErrorBanner message={openError} onRetry={() => void open(selected)} />}

          {workspaceEmpty && !openError && !homeLoading ? (
            <section className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm">
                <h2 className="text-sm font-semibold text-ink-950">Start from template</h2>
                <p className="mt-1 flex-1 text-[12px] leading-relaxed text-ink-500">
                  Copy a ready-made pipeline into this workspace, then edit and run it in the Editor.
                </p>
                <button type="button" className="btn-secondary mt-3 w-full" onClick={goTemplates}>
                  Open Templates
                </button>
              </div>
              <div className="flex flex-col rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm">
                <h2 className="text-sm font-semibold text-ink-950">Link dataset</h2>
                <p className="mt-1 flex-1 text-[12px] leading-relaxed text-ink-500">
                  Upload or import data in Datasets, then choose the folders this workspace uses.
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
                <strong className="font-medium text-ink-900">Pipelines:</strong> Templates are starting
                points · Saved pipelines live in this workspace · The Editor is where you change and run them.
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

          {/* Latest result — newest successful run with a headline metric. */}
          {(() => {
            const latest = pickLatestResult(recentRuns, homeModels)
            if (!latest || homeLoading) return null
            const pct = isRatioMetric(latest.metric.name, latest.metric.value)
            const tone = regressionTone(latest.regression, /loss|error|mae|mse/i.test(latest.metric.name))
            return (
              <section
                className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm"
                data-testid="home-latest-result"
              >
                <div className="min-w-0">
                  <div className={SECTION_TITLE}>Latest result</div>
                  <div className="mt-1 flex flex-wrap items-baseline gap-2">
                    <span className="text-2xl font-semibold tabular-nums text-ink-950" title={`${latest.metric.name} = ${latest.metric.value}`}>
                      {formatMetric(latest.metric.value, { percent: pct })}
                    </span>
                    <span className="text-[12px] text-ink-500">{metricLabel(latest.metric.name)}</span>
                    {latest.regression && tone ? (
                      <span
                        className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${
                          tone === 'worse'
                            ? 'bg-rose-100 text-rose-800'
                            : tone === 'better'
                              ? 'bg-emerald-100 text-emerald-800'
                              : 'bg-ink-100 text-ink-600'
                        }`}
                        title={
                          latest.regression.previousValue != null
                            ? `Best earlier run: ${formatMetric(latest.regression.previousValue, { percent: pct })}`
                            : undefined
                        }
                      >
                        {tone === 'worse' ? 'Regression ' : tone === 'better' ? 'Improved ' : 'No change '}
                        {formatMetricDelta(latest.metric.name, latest.regression.delta)} vs best earlier run
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-0.5 truncate text-[12px] text-ink-500" title={`Run ${latest.run.run_id}`}>
                    {runDisplayName(latest.run)}
                    {latest.run.created_at ? ` · ${formatRelativeTime(latest.run.created_at)}` : ''}
                  </p>
                </div>
                <div className="ml-auto flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => useAppStore.getState().openRun(latest.run.run_id, { project: selected })}
                  >
                    Open run
                  </button>
                  {latest.modelName ? (
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => guardedNavigatePath(paths.model(selected, latest.modelName!))}
                    >
                      Open model
                    </button>
                  ) : null}
                </div>
              </section>
            )
          })()}

          {/* Activity feed */}
          <section>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h2 className={SECTION_TITLE}>Activity</h2>
              <button type="button" className="ide-quiet-btn text-[11px]" onClick={() => goView('runs')}>
                View all in Runs
                <ChevronRight className="h-3 w-3" />
              </button>
            </div>
            <div className="overflow-hidden rounded-xl border border-ink-200/70 bg-white">
              {homeLoading ? (
                <ul className="divide-y divide-ink-100" aria-label="Loading activity">
                  {[0, 1, 2].map((i) => (
                    <li key={i} className="flex items-center gap-3 px-3 py-2.5">
                      <div className="h-3 w-40 animate-pulse rounded bg-ink-100" />
                      <div className="h-3 flex-1 animate-pulse rounded bg-ink-50" />
                      <div className="h-3 w-12 animate-pulse rounded bg-ink-100" />
                    </li>
                  ))}
                </ul>
              ) : recentRuns.length === 0 && !schedules.some((s) => s.last_run_id) ? (
                <EmptyState
                  compact
                  icon={EmptyHistory}
                  title="No activity yet"
                  description="Run a pipeline from the Editor."
                  action={
                    <button type="button" className="btn-secondary" onClick={goEditor}>
                      Open Editor
                    </button>
                  }
                />
              ) : (
                <ul className="divide-y divide-ink-100">
                  {buildActivityItems(recentRuns, HOME_ACTIVITY_ROWS, expandedFailures).map((item) => {
                    if (item.kind === 'more-failed') {
                      return (
                        <li key={item.key}>
                          <button
                            type="button"
                            className="ide-row w-full px-3 text-[12px] text-ink-500 hover:text-ink-800"
                            title={item.runs.map((r) => `Run ${r.run_id}`).join('\n')}
                            onClick={() => setExpandedFailures((prev) => new Set(prev).add(item.key))}
                          >
                            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                            {item.runs.length} more failed run{item.runs.length === 1 ? '' : 's'} with the same error
                          </button>
                        </li>
                      )
                    }
                    const r = item.run
                    const detail = activityDetail(r, shortRunId)
                    return (
                      <li key={r.run_id}>
                        <button
                          type="button"
                          className="ide-row w-full px-3"
                          onClick={() =>
                            useAppStore.getState().openRun(r.run_id, selected ? { project: selected } : undefined)
                          }
                        >
                          <History className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                          <span className="min-w-0 flex-1 truncate text-[12px] text-ink-700" title={detail?.text}>
                            <span className="font-medium text-ink-900">{runDisplayName(r)}</span>
                            {detail ? (
                              <span className={`ml-1.5 ${detail.tone === 'error' ? 'text-rose-700' : 'text-ink-500'}`}>
                                · {detail.text}
                              </span>
                            ) : null}
                          </span>
                          <span className="shrink-0 font-mono text-[11px] text-ink-400" title={`Run ${r.run_id}`}>
                            {shortRunId(r.run_id)}
                          </span>
                          {r.created_at ? (
                            <time
                              className="w-16 shrink-0 text-right text-[11px] text-ink-400"
                              dateTime={r.created_at}
                              title={new Date(r.created_at).toLocaleString()}
                            >
                              {formatRelativeTime(r.created_at)}
                            </time>
                          ) : null}
                          {/* Shared vocabulary; coloured badge only for exceptions (Done is plain text). */}
                          <StatusBadge kind="run" status={r.status || 'unknown'} className="shrink-0" />
                        </button>
                      </li>
                    )
                  })}
                  {schedules
                    .filter((s) => s.last_run_id && String(s.project || '') === selected)
                    .slice(0, 3)
                    .map((s) => (
                      <li key={`sched-fire-${s.id}-${s.last_run_id}`}>
                        <button
                          type="button"
                          className="ide-row w-full px-3"
                          title={
                            s.last_error
                              ? `Last error: ${s.last_error}`
                              : `Open the schedule's last run (${s.last_run_id})`
                          }
                          onClick={() => void openScheduleRun(s)}
                        >
                          <CalendarClock className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                          <span className="min-w-0 flex-1 truncate text-[12px] text-ink-700">
                            Schedule {s.name || s.id} · last run{' '}
                            <span className="font-mono">{shortRunId(String(s.last_run_id))}</span>
                            {s.last_error ? (
                              <span className="ml-1 text-rose-700">· {s.last_error}</span>
                            ) : null}
                          </span>
                          <span className="text-[11px] text-ink-400">{s.pipeline || ''}</span>
                          {s.last_error ? <StatusBadge kind="run" status="failed" /> : null}
                        </button>
                      </li>
                    ))}
                </ul>
              )}
            </div>
          </section>

          {/* Continue / Always-on / Linked inputs sit side-by-side on wide screens instead of
              stacking full-width one after another — this is a dashboard, not a document. */}
          <div className={`grid gap-4 ${setupCollapsed ? '' : 'lg:grid-cols-3'}`}>
          {/* Layer 1 — continue work */}
          <section
            ref={continueRef}
            className={`flex flex-col rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm transition ${cardRing('continue')}`}
          >
            {/* Every card header now has the same shape — title left, one cross-link
                right — instead of Continue having none, Always-on having one and
                Linked inputs having an action plus a stat. */}
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className={SECTION_TITLE}>Continue</div>
              <button type="button" className="ide-quiet-btn text-[11px]" onClick={goEditor}>
                Open Editor
              </button>
            </div>
            <div className="overflow-hidden rounded-xl border border-ink-200/70 bg-white">
              {homeLoading ? (
                <div className="space-y-2 px-3 py-3" aria-label="Loading pipelines">
                  <div className="h-3 w-2/3 animate-pulse rounded bg-ink-100" />
                  <div className="h-3 w-1/2 animate-pulse rounded bg-ink-100" />
                </div>
              ) : projectPipelines.length === 0 ? (
                <EmptyState
                  compact
                  icon={Workflow}
                  title="No pipelines yet"
                  description="Start from a template or open the Editor."
                  action={
                    <button type="button" className="btn-secondary" onClick={goTemplates}>
                      Start from a template
                    </button>
                  }
                />
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
                              Pipeline versions & publishing
                            </summary>
                            <div className="mt-1.5 flex flex-wrap gap-1.5 pb-1">
                              <p className="w-full text-[10px] text-ink-500">
                                These publish the saved pipeline (graph). To move a trained model to
                                production, use the Models page.
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

          {/* Always-on — schedules filtered by project when possible. When there are
              no schedules and no datasets chosen, both cards collapse into the one
              compact "Set up" row below instead of two big empty states. */}
          {!setupCollapsed && (
          <section className="flex flex-col rounded-2xl border border-ink-200/80 bg-white p-4 shadow-sm">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className={SECTION_TITLE}>Always-on</div>
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
                if (homeLoading) {
                  return (
                    <div className="px-3 py-3" aria-label="Loading schedules">
                      <div className="h-3 w-1/2 animate-pulse rounded bg-ink-100" />
                    </div>
                  )
                }
                if (projectSchedules.length === 0) {
                  return (
                    <EmptyState
                      compact
                      icon={CalendarClock}
                      title="No schedules"
                      description="Create one under Ops, or run on demand from the Editor."
                      action={
                        <button type="button" className="btn-secondary" onClick={() => goView('system')}>
                          Open Ops
                        </button>
                      }
                    />
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
                              Last error: {s.last_error}
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

          )}

          {/* Layer 2 — linked data (compact) */}
          {!setupCollapsed && (
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
              <h2
                className={SECTION_TITLE}
                title="Pin dataset folders for this workspace (bookmarks for Datasets scoping). Pinning does not change pipeline ingest paths — set those in the Editor, or pick a linked folder from the path field."
              >
                Datasets in use
              </h2>
              <button
                type="button"
                className="ide-quiet-btn text-[11px]"
                onClick={() => openData({ mode: 'inputs' })}
              >
                Open Datasets
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="rounded-md border border-ink-200 bg-white px-2 py-1 text-[12px]"
                value={linkPick}
                onChange={(e) => setLinkPick(e.target.value)}
                aria-label="Add a dataset folder"
                disabled={homeLoading}
              >
                <option value="">{homeLoading ? 'Loading datasets…' : 'Select a dataset folder…'}</option>
                {inputLabels.map((label) => (
                  <option key={label} value={label} disabled={links.inputs.includes(label)}>
                    {label}
                  </option>
                ))}
              </select>
              <ConfirmButton
                label="Add"
                confirmLabel={linkPick ? `Add “${linkPick}”?` : 'Confirm'}
                onConfirm={() => void linkInput()}
                disabled={!linkPick || links.inputs.includes(linkPick)}
              />
              {/* "Browse library" removed — it opened the same Datasets Inputs view
                  as the card header's "Open Datasets", one row apart. */}
            </div>
            {links.inputs.length === 0 && (
              <p className="mt-2 text-[12px] text-ink-500">
                No folders pinned yet — pick one above (accessible labels only), or upload in Datasets first.
                Pinning bookmarks the folder; set the ingest path in the Editor to use it in a run.
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
                    <button type="button" className="text-ink-400 hover:text-rose-600" onClick={() => void unlinkInput(label)} aria-label={`Remove ${label}`}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          )}
          </div>

          {setupCollapsed && (
            <section
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-ink-200/80 bg-ink-50/60 px-4 py-2.5 text-[12px] text-ink-600"
              aria-label="Set up"
            >
              <span className="font-medium text-ink-800">Set up</span>
              <button
                type="button"
                className="inline-flex items-center gap-1 text-accent-800 hover:underline"
                title="Run a pipeline on a schedule (Ops → Schedules)"
                onClick={() => goView('system')}
              >
                <CalendarClock className="h-3.5 w-3.5" /> Add a schedule
              </button>
              <span className="text-ink-300" aria-hidden>
                ·
              </span>
              <button
                type="button"
                className="inline-flex items-center gap-1 text-accent-800 hover:underline"
                title="Pin dataset folders for this workspace (Editor path picker can use them). Pinning alone does not rewrite pipeline graphs."
                onClick={() => {
                  setShowInputsCard(true)
                  window.setTimeout(() => jumpToCard('inputs'), 0)
                }}
              >
                <Database className="h-3.5 w-3.5" /> Choose datasets
              </button>
            </section>
          )}

          {/* Layer 3 — workspace administration (collapsed by default).
              Replaces "Spec & metadata" (placeholder spec/taxonomy/contract nobody
              read, dataset versions duplicated from Datasets → Outputs, a "Restore"
              into an unused working area, snapshots duplicating pipeline versions)
              and "Workspace settings" (a status select with no effect, a rename that
              orphaned run history). What is left changes something real. */}
          <details
            className="group overflow-hidden rounded-2xl border border-ink-200/80 bg-white shadow-sm"
            open={workspaceFoldOpen}
            onToggle={(e) => setWorkspaceFoldOpen((e.currentTarget as HTMLDetailsElement).open)}
          >
            <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-4 py-3 text-[13px] font-medium text-ink-800 hover:bg-ink-50/70">
              <ChevronRight className="h-4 w-4 shrink-0 text-ink-400 transition group-open:rotate-90" />
              Workspace
              <span className="font-normal text-ink-400">name, description, archive, clone, delete</span>
              {archived ? (
                <span className="ml-auto shrink-0 rounded-md bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-800">
                  Archived
                </span>
              ) : null}
            </summary>
            <div className="space-y-4 border-t border-ink-100 px-4 pb-4 pt-3">
              <div className="grid gap-3 sm:max-w-xl">
                <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-2 text-[12px] text-ink-500">
                  <label htmlFor="ws-display-name" className="pt-1">
                    Display name
                  </label>
                  <div className="min-w-0">
                    <input
                      id="ws-display-name"
                      value={nameDraft}
                      maxLength={120}
                      onChange={(e) => setNameDraft(e.target.value)}
                      className="w-full rounded-md border border-ink-200 px-2 py-1 text-[12px] text-ink-900"
                    />
                    <p className="mt-1 text-[11px] text-ink-400">
                      ID <span className="font-mono">{selected}</span> — used in links, runs and the audit log; it
                      does not change.
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-2 text-[12px] text-ink-500">
                  <label htmlFor="ws-description" className="pt-1">
                    Description
                  </label>
                  <textarea
                    id="ws-description"
                    value={descDraft}
                    rows={2}
                    maxLength={500}
                    placeholder="What this workspace is for"
                    onChange={(e) => setDescDraft(e.target.value)}
                    className="w-full rounded-md border border-ink-200 px-2 py-1 text-[12px] text-ink-900"
                  />
                </div>
                <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-2">
                  <span />
                  <div>
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={!detailsDirty || homeLoading}
                      title={!detailsDirty ? 'Nothing changed' : undefined}
                      onClick={() => void saveDetails()}
                    >
                      Save details
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-2 border-t border-ink-100 pt-3 text-[12px] text-ink-500">
                  <span className="pt-1">{archived ? 'Archived' : 'Archive'}</span>
                  <div className="min-w-0">
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={homeLoading}
                      onClick={() => void setArchived(!archived)}
                    >
                      {archived ? (
                        <>
                          <ArchiveRestore className="h-3.5 w-3.5" /> Unarchive workspace
                        </>
                      ) : (
                        <>
                          <Archive className="h-3.5 w-3.5" /> Archive workspace
                        </>
                      )}
                    </button>
                    <p className="mt-1 text-[11px] text-ink-400">
                      Archived workspaces are hidden from the Workspaces list (toggle “Show archived”). Nothing is
                      deleted and they still open and run.
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-2 border-t border-ink-100 pt-3 text-[12px] text-ink-500">
                  <label htmlFor="ws-clone-to" className="pt-1">
                    Clone as
                  </label>
                  <div className="min-w-0">
                    <div className="flex min-w-0 gap-2">
                      <input
                        id="ws-clone-to"
                        value={cloneTo}
                        onChange={(e) => setCloneTo(e.target.value)}
                        aria-describedby="ws-clone-scope"
                        className="min-w-0 flex-1 rounded-md border border-ink-200 px-2 py-1 font-mono text-[12px]"
                      />
                      <button
                        type="button"
                        className="btn-secondary shrink-0"
                        disabled={!cloneTo.trim() || cloneTo.trim() === selected || !isValidWorkspaceName(cloneTo)}
                        title={
                          !cloneTo.trim()
                            ? 'Enter a new workspace id first'
                            : cloneTo.trim() === selected
                              ? 'Pick a different id for the copy'
                              : !isValidWorkspaceName(cloneTo)
                                ? WORKSPACE_NAME_HINT
                                : undefined
                        }
                        onClick={() => void clone()}
                      >
                        <Copy className="h-3.5 w-3.5" /> Clone
                      </button>
                    </div>
                    <p id="ws-clone-scope" className="mt-1 text-[11px] text-ink-400">
                      {CLONE_SCOPE_TEXT}
                    </p>
                  </div>
                </div>
              </div>
              <div ref={dangerZoneRef} className="rounded-xl border border-rose-200 bg-rose-50/50 px-3 py-3">
                {/* Scope verified against ProjectManager.delete: it rmtree's
                    workspace/datasets/output/{id} and disables its schedules; runs,
                    artifacts, models and the audit log live elsewhere and survive. */}
                <div className="text-[12px] font-semibold text-rose-900">Danger zone — delete workspace</div>
                <div className="mt-2 grid gap-3 text-[12px] sm:grid-cols-2">
                  <div>
                    <div className="font-medium text-rose-900">Removed</div>
                    {homeLoading ? (
                      <div className="mt-1 h-3 w-2/3 animate-pulse rounded bg-rose-100" aria-label="Counting workspace contents" />
                    ) : (
                      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-rose-900/90">
                        {deleteScope.removed.map((line) => (
                          <li key={line}>{line}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div>
                    <div className="font-medium text-ink-800">Kept</div>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-ink-700">
                      {deleteScope.kept.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-end gap-2">
                  <label className="min-w-0 flex-1 basis-56 text-[12px] text-rose-900">
                    Type <span className="font-mono font-semibold">{selected}</span> to confirm
                    <input
                      value={deleteConfirm}
                      onChange={(e) => setDeleteConfirm(e.target.value)}
                      autoComplete="off"
                      spellCheck={false}
                      aria-label={`Type ${selected} to confirm deletion`}
                      className="mt-1 w-full rounded-md border border-rose-200 bg-white px-2 py-1 font-mono text-[12px]"
                    />
                  </label>
                  <button
                    type="button"
                    className="btn-danger mb-px"
                    disabled={homeLoading || deleteConfirm.trim() !== selected}
                    onClick={() => void remove()}
                  >
                    Delete workspace
                  </button>
                </div>
              </div>
            </div>
          </details>
        </div>
      </div>
    </div>
  )
}
