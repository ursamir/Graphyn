import React from 'react'
import clsx from 'clsx'
import { LayoutTemplate as EmptyLayoutTemplate } from 'lucide-react'
import { RefreshCw, ChevronRight, Database, Download, MoreHorizontal, Puzzle, Search, Upload } from 'lucide-react'
import { apiJson } from '../../api/client'
import { unwrapList } from '../../api/unwrapList'
import { useAppStore } from '../../store/appStore'
import { stampProjectOnGraph } from '../../lib/projectStamp'
import type { GraphIR } from '../../types/graph'
import { useMenuDismiss } from '../../lib/menus'
import { ConfirmButton, EmptyState, ErrorBanner, LoadingBlock } from '../../components/ui'
import { MasterDetail, MasterDetailToggle, WorkbenchPage } from '../../layout'
import { MarketplaceBrowse } from './MarketplaceBrowse'
import { loadMarketplaceCatalog } from './marketplaceCatalog'
import { humanizeTemplateName, humanNodeLabel, stripIsolatedPrefix } from '../../lib/format'
import { workspaceErrorMessage, workspaceNameError } from '../../lib/workspaceName'
import { buildNodeTypePluginMap, summarizeMissing, type PluginManifestLike } from './missingPlugins'
import { apiFetch } from '../../api/client'
import { onPathChange, readSearchParams, replacePathSearch } from '../../routes/nav'
import { probePathExists } from '../edge/edgeDeployTemplate'
import { applyTemplateFilter, templateFilterValue } from './templateFilter'
import {
  findStep,
  groupTemplates,
  isTemplateRunnable,
  templateMissing,
  type TemplateEntry,
} from './templateGroups'

function isExampleTemplate(name: string): boolean {
  return name.startsWith('ex-')
}

export type TemplateSummary = {
  name: string
  description?: string
  difficulty?: string | null
  required_plugins?: string[]
  inputs?: string[]
  outputs?: string[]
  tags?: string[]
  node_count?: number
  node_types?: string[]
  /** Display title from the API (unique across starters/examples). */
  title?: string
  /** UX API: can every node run on this host? (null/absent on older APIs) */
  runnable?: boolean | null
  missing_node_types?: string[] | null
  /** Guided multi-step series (e.g. Example 06 prepare → train). */
  group?: string | null
  phase?: string | number | null
  step_title?: string | null
}

const RUNNABLE_ONLY_KEY = 'graphyn.templates.runnableOnly'

function readRunnableOnly(): boolean {
  try {
    return window.localStorage.getItem(RUNNABLE_ONLY_KEY) !== '0'
  } catch {
    return true
  }
}

/** Do the dataset paths a later step reads exist in this workspace yet? */
type StepReadiness = 'checking' | 'ready' | 'missing' | 'unknown'


/* Removed: isDatasetRelatedTemplate(). It keyword-matched a template's text to
   decide whether to show a context-free "Open Datasets" button — which landed you
   in an unfiltered library even when the template declared no input at all. The
   Datasets link now hangs off the declared input path itself, so a template
   without one simply doesn't offer a link it can't target. */

/** Templates declare inputs as full workspace paths ("workspace/datasets/input/
 *  speech-commands/go"), but the Datasets page addresses the same data by its
 *  *label* — the first segment under `.../input/`. Strip the prefix so the
 *  "Open Datasets" action can hand `openData({ label })` something it resolves,
 *  instead of dumping you in an unfiltered library to find the folder by hand. */
function datasetInputLabel(tpl: TemplateSummary): string | null {
  for (const raw of tpl.inputs ?? []) {
    const m = /(?:^|\/)datasets\/input\/([^/]+)/.exec(raw)
    if (m?.[1]) return m[1]
  }
  return null
}

/** Every declared path repeats the same long `workspace/...` prefix, so a
 *  truncated chip spent its whole width on characters shared by every card and
 *  elided the part that actually differs. Chips keep the full path in `title`. */
function shortPath(raw: string): string {
  return raw.replace(/^workspace\/(?:datasets\/(?:input|output)|artifacts)\//, '')
}

type TemplateSort = 'name' | 'nodes' | 'plugins'

const TEMPLATE_SORT_LABEL: Record<TemplateSort, string> = {
  name: 'Name (A–Z)',
  nodes: 'Most nodes',
  plugins: 'Most plugins',
}

/** `example` is on all 30 templates and already shown as the EXAMPLE badge, so
 *  rendering it as a tag too would repeat the same word twice on every card. */
const HIDDEN_TAGS = new Set(['example'])

/** Approximate height of a template card's ⋯ menu, used to decide whether it
 *  still fits below the trigger or has to open upwards. */
const CARD_MENU_HEIGHT_PX = 120

function normalizeList(raw: unknown): TemplateSummary[] {
  return unwrapList<unknown>(raw).map((item) => {
    if (typeof item === 'string') return { name: item }
    if (item && typeof item === 'object' && typeof (item as { name?: unknown }).name === 'string') {
      return item as TemplateSummary
    }
    return { name: String(item) }
  })
}

function chipList(items: string[] | undefined, empty: string, mapLabel?: (s: string) => string) {
  if (!items || items.length === 0) {
    return <span className="text-type-meta text-ink-400">{empty}</span>
  }
  return (
    <span className="flex flex-wrap gap-1">
      {items.slice(0, 4).map((item) => (
        <span
          key={item}
          className="max-w-[12rem] truncate rounded-md bg-ink-50 px-1.5 py-0.5 text-type-meta text-ink-600"
          title={item}
        >
          {mapLabel ? mapLabel(item) : item}
        </span>
      ))}
      {items.length > 4 ? (
        <span className="text-type-meta text-ink-400">+{items.length - 4}</span>
      ) : null}
    </span>
  )
}

export default function TemplatesView() {
  const getCanvasGraph = useAppStore((s) => s.getCanvasGraph)
  const pushToast = useAppStore((s) => s.pushToast)
  const openData = useAppStore((s) => s.openData)
  const activeProject = useAppStore((s) => s.activeProject)
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const setBuilderDataset = useAppStore((s) => s.setBuilderDataset)
  const [items, setItems] = React.useState<TemplateSummary[] | null>(null)
  const [versionsMap, setVersionsMap] = React.useState<Record<string, string[]>>({})
  const [latestMap, setLatestMap] = React.useState<Record<string, string | null>>({})
  const [selectedVersion, setSelectedVersion] = React.useState<Record<string, string>>({})
  const [saveName, setSaveName] = React.useState('')
  const [saveOpen, setSaveOpen] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [syncBanner, setSyncBanner] = React.useState<{
    written: number
    errors: Array<{ id?: string; error?: string } | string>
  } | null>(null)
  const [syncing, setSyncing] = React.useState(false)
  type TabFilter = 'all' | 'examples' | 'saved' | 'marketplace'
  const tabFromUrl = (): TabFilter => {
    const t = readSearchParams().get('tab')
    return t === 'examples' || t === 'saved' || t === 'marketplace' ? t : 'all'
  }
  /* Tab is URL-addressable (?tab=marketplace) so the Marketplace catalog can be
     linked, bookmarked and restored by the browser back button. */
  const [filter, setFilterState] = React.useState<TabFilter>(tabFromUrl)
  const setFilter = React.useCallback((next: TabFilter) => {
    setFilterState(next)
    replacePathSearch({ tab: next === 'all' ? undefined : next })
  }, [])
  React.useEffect(
    () =>
      onPathChange(() => {
        const t = tabFromUrl()
        setFilterState((cur) => (cur === t ? cur : t))
      }),
    [],
  )
  const [search, setSearch] = React.useState('')
  const [marketplaceTotal, setMarketplaceTotal] = React.useState<number | null>(null)
  const [marketplaceStats, setMarketplaceStats] = React.useState<{
    matched: number
    loaded: number
  } | null>(null)
  /* Facets. Every template declares required_plugins and tags, and the gallery
     used both only as invisible search-blob text — 30 cards in one flat wall
     with no way to narrow to "the ASR ones" short of guessing the right word. */
  const [activePlugins, setActivePlugins] = React.useState<string[]>([])
  const [sortBy, setSortBy] = React.useState<TemplateSort>('name')
  const [runnableOnly, setRunnableOnlyState] = React.useState<boolean>(readRunnableOnly)
  const setRunnableOnly = (v: boolean) => {
    setRunnableOnlyState(v)
    try {
      window.localStorage.setItem(RUNNABLE_ONLY_KEY, v ? '1' : '0')
    } catch {
      /* per-viewer convenience only */
    }
  }
  const togglePlugin = (p: string) =>
    setActivePlugins((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]))
  const [headerMoreOpen, setHeaderMoreOpen] = React.useState(false)
  const [menuUp, setMenuUp] = React.useState(false)
  const headerMoreRef = React.useRef<HTMLDivElement | null>(null)
  const [menuFor, setMenuFor] = React.useState<string | null>(null)
  const menuRef = React.useRef<HTMLDivElement | null>(null)
  const [selectedName, setSelectedName] = React.useState<string | null>(null)
  const [projectGate, setProjectGate] = React.useState<{ template: string } | null>(null)
  const [projectChoices, setProjectChoices] = React.useState<string[]>([])
  const [projectPick, setProjectPick] = React.useState('')
  const [projectCreate, setProjectCreate] = React.useState('')
  const [projectGateBusy, setProjectGateBusy] = React.useState(false)
  const projectCreateError = workspaceNameError(projectCreate)

  /* Node types each template needs vs the loaded catalog (App pages GET /nodes
     into the store). Template summaries strip the `Isolated_` prefix, so the
     catalog side is normalized the same way. Empty catalog (still loading /
     offline) → no warnings rather than "everything is missing". */
  const catalog = useAppStore((s) => s.catalog)
  const catalogTypes = React.useMemo(
    () => new Set(catalog.map((c) => stripIsolatedPrefix(String(c.node_type || '')).toLowerCase())),
    [catalog],
  )
  const missingNodeTypes = React.useCallback(
    (tpl: TemplateSummary | undefined): string[] => {
      if (!tpl || catalogTypes.size === 0) return []
      return (tpl.node_types ?? []).filter(
        (nt) => !catalogTypes.has(stripIsolatedPrefix(nt).toLowerCase()),
      )
    },
    [catalogTypes],
  )

  /** Backend `missing_node_types` when the API sends it, else the catalog diff. */
  const effectiveMissing = React.useCallback(
    (tpl: TemplateSummary | undefined): string[] => (tpl ? templateMissing(tpl, missingNodeTypes) : []),
    [missingNodeTypes],
  )

  /* node_type → plugin name from manifests (installed incl. disabled / failed
     loads, plus the plugin index when it lists node types), so "Needs plugins"
     names plugins — node types no manifest claims are labelled as such. */
  const [nodeTypePlugins, setNodeTypePlugins] = React.useState<Map<string, string>>(() => new Map())
  React.useEffect(() => {
    let cancelled = false
    void Promise.allSettled([
      apiJson<unknown>('/plugins'),
      apiJson<unknown>('/plugins/search', { query: { q: '' } }),
    ]).then((res) => {
      if (cancelled) return
      const rows: PluginManifestLike[] = []
      for (const r of res) {
        if (r.status === 'fulfilled') rows.push(...unwrapList<PluginManifestLike>(r.value))
      }
      setNodeTypePlugins(buildNodeTypePluginMap(rows))
    })
    return () => {
      cancelled = true
    }
  }, [])

  const onMarketplaceStats = React.useCallback(
    (stats: { matched: number; loaded: number; total: number }) => {
      setMarketplaceTotal(stats.total)
      setMarketplaceStats({ matched: stats.matched, loaded: stats.loaded })
    },
    [],
  )

  const load = React.useCallback(async () => {
    setError(null)
    try {
      const list = normalizeList(await apiJson<unknown>('/pipelines/templates'))
      setItems(list)
      const versions: Record<string, string[]> = {}
      const latest: Record<string, string | null> = {}
      await Promise.all(
        list.map(async ({ name }) => {
          try {
            const v = await apiJson<{
              latest_version?: string | null
              versions?: string[]
              storage?: string
            }>(`/pipelines/templates/${encodeURIComponent(name)}/versions`)
            versions[name] = v.versions ?? []
            latest[name] = v.latest_version ?? (v.storage === 'legacy_flat' ? 'unversioned' : null)
          } catch {
            versions[name] = []
            latest[name] = null
          }
        }),
      )
      setVersionsMap(versions)
      setLatestMap(latest)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setItems([])
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  React.useEffect(() => {
    void loadMarketplaceCatalog()
      .then((doc) => setMarketplaceTotal(doc.total_templates))
      .catch(() => {
        /* MarketplaceBrowse will surface the error when that tab opens */
      })
  }, [])

  // Escape / outside click / another menu opening closes these (lib/menus).
  const closeCardMenu = React.useCallback(() => setMenuFor(null), [])
  const closeHeaderMore = React.useCallback(() => setHeaderMoreOpen(false), [])
  useMenuDismiss(Boolean(menuFor), closeCardMenu, menuRef)
  useMenuDismiss(headerMoreOpen, closeHeaderMore, headerMoreRef)

  const importExamples = async () => {
    setSyncing(true)
    setSyncBanner(null)
    try {
      const res = await apiJson<{
        count_written?: number
        errors?: Array<{ id?: string; error?: string } | string>
      }>('/pipelines/templates/sync-examples', { method: 'POST', query: { force: true } })
      const n = res.count_written ?? 0
      const errs = Array.isArray(res.errors) ? res.errors : []
      if (errs.length > 0) {
        setSyncBanner({ written: n, errors: errs })
        pushToast(`Imported ${n} examples — ${errs.length} issue${errs.length === 1 ? '' : 's'}`, 'error')
      } else {
        pushToast(`Imported ${n} example templates`, 'success')
      }
      setFilter('examples')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setSyncing(false)
    }
  }

  const loadIntoBuilderWithProject = async (name: string, project: string) => {
    const raw = selectedVersion[name] || latestMap[name] || undefined
    const version = raw && raw !== 'unversioned' ? raw : undefined
    const data = await apiJson<{ graph?: GraphIR }>(
      `/pipelines/templates/${encodeURIComponent(name)}`,
      { query: { version } },
    )
    if (!data.graph) throw new Error('Template has no graph payload')
    const stamped = stampProjectOnGraph(data.graph, project)
    setActiveProject(project)
    setBuilderDataset({ project })
    // Opening a template must not create/overwrite a saved workspace pipeline —
    // the Editor's Save button does that explicitly.
    useAppStore.getState().loadGraphIntoBuilder(stamped)
    pushToast(
      `Template ready in Editor (not saved yet) — Save to add it to the workspace.`,
      'success',
    )
  }

  const openProjectGate = async (name: string) => {
    if (activeProject) {
      try {
        await loadIntoBuilderWithProject(name, activeProject)
      } catch (err) {
        pushToast(err instanceof Error ? err.message : String(err), 'error')
      }
      return
    }
    setProjectGate({ template: name })
    setProjectPick('')
    setProjectCreate('')
    try {
      const list = unwrapList<{ name: string } | string>(await apiJson('/projects'))
      const names = list
        .map((p) => (typeof p === 'string' ? p : p.name))
        .filter(Boolean)
      setProjectChoices(names)
      if (names[0]) setProjectPick(names[0])
    } catch {
      setProjectChoices([])
    }
  }

  const confirmProjectGate = async () => {
    if (!projectGate) return
    const created = projectCreate.trim()
    const picked = projectPick.trim()
    const project = created || picked
    if (!project) {
      pushToast('Create or select a workspace first', 'error')
      return
    }
    if (created && projectCreateError) {
      pushToast(projectCreateError, 'error')
      return
    }
    setProjectGateBusy(true)
    try {
      if (created && !projectChoices.includes(created)) {
        await apiJson('/projects', { method: 'POST', body: JSON.stringify({ name: created }) })
      }
      await loadIntoBuilderWithProject(projectGate.template, project)
      setProjectGate(null)
    } catch (err) {
      pushToast(workspaceErrorMessage(err instanceof Error ? err.message : String(err)), 'error')
    } finally {
      setProjectGateBusy(false)
    }
  }

  const loadIntoBuilder = async (name: string) => {
    await openProjectGate(name)
  }

  const saveFromCanvas = async () => {
    if (!/^[A-Za-z0-9_-]+$/.test(saveName)) {
      pushToast('Invalid template name', 'error')
      return
    }
    const graph = getCanvasGraph?.()
    if (!graph || typeof graph !== 'object') {
      pushToast('Open Editor and build a graph first', 'error')
      return
    }
    try {
      const res = await apiJson<{ name: string; version?: string }>('/pipelines/templates', {
        method: 'POST',
        body: JSON.stringify({
          name: saveName,
          yaml: JSON.stringify(graph),
          description: 'Saved from Graphyn Editor canvas',
        }),
      })
      pushToast(`Saved ${res.name}${res.version ? ` @ ${res.version}` : ''}`, 'success')
      setSaveOpen(false)
      setHeaderMoreOpen(false)
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const uploadFile = () => {
    if (!/^[A-Za-z0-9_-]+$/.test(saveName)) {
      pushToast('Invalid template name', 'error')
      return
    }
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json,.graph.json'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      try {
        const text = await file.text()
        JSON.parse(text)
        await apiJson('/pipelines/templates', {
          method: 'POST',
          body: JSON.stringify({ name: saveName, yaml: text, description: file.name }),
        })
        pushToast(`Uploaded ${saveName}`, 'success')
        setSaveOpen(false)
        setHeaderMoreOpen(false)
        await load()
      } catch (err) {
        pushToast(err instanceof Error ? err.message : String(err), 'error')
      }
    }
    input.click()
  }

  const starters = new Set([
    'audio-quality-check',
    'audio-classification',
    'podcast-leveling',
    'speech-recognition',
    'basic-wakeword',
  ])
  const isExample = (name: string) => isExampleTemplate(name) || starters.has(name)
  const matchesTabAndSearch = (t: TemplateSummary) => {
    if (filter === 'examples' && !isExample(t.name)) return false
    if (filter === 'saved' && isExample(t.name)) return false
    const q = search.trim().toLowerCase()
    if (!q) return true
    const blob = [
      t.name,
      t.title ?? '',
      humanizeTemplateName(t.name),
      t.description ?? '',
      ...(t.tags ?? []),
      ...(t.node_types ?? []),
      ...(t.required_plugins ?? []),
    ]
      .join(' ')
      .toLowerCase()
    return blob.includes(q)
  }
  /* Facet counts come from the tab+search result, NOT the fully-filtered list —
     otherwise selecting a plugin would rewrite every other chip's count to 0 and
     you could never widen the selection without clearing it first. */
  const facetPool = (items ?? []).filter(matchesTabAndSearch)
  /** Search-only pool (any kind) — counts for the single "Show" filter control. */
  const searchPool = filter === 'all' ? facetPool : (items ?? []).filter((t) => {
    const q = search.trim()
    if (!q) return true
    return [t.name, t.title ?? '', humanizeTemplateName(t.name), t.description ?? '', ...(t.tags ?? []), ...(t.node_types ?? []), ...(t.required_plugins ?? [])]
      .join(' ')
      .toLowerCase()
      .includes(q.toLowerCase())
  })
  const pluginCounts = new Map<string, number>()
  for (const t of searchPool) {
    for (const p of t.required_plugins ?? []) pluginCounts.set(p, (pluginCounts.get(p) ?? 0) + 1)
  }
  const facets = [...pluginCounts.entries()]
    .filter(([p, n]) => n > 1 || activePlugins.includes(p))
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))

  /* "Runnable here": backend `runnable`, else no missing node types vs the
     loaded catalog. Unknown (no backend flag and catalog not loaded yet) never
     hides anything. A guided group stays visible when any of its steps runs. */
  const runnabilityKnown =
    catalogTypes.size > 0 || (items ?? []).some((t) => typeof t.runnable === 'boolean')
  const runnableOf = (t: TemplateSummary) => !runnabilityKnown || isTemplateRunnable(t, effectiveMissing(t))
  const runnableGroups = new Set(
    (items ?? []).filter((t) => t.group && runnableOf(t)).map((t) => String(t.group)),
  )
  const passesRunnable = (t: TemplateSummary) =>
    !runnableOnly || runnableOf(t) || Boolean(t.group && runnableGroups.has(String(t.group)))
  const pluginFiltered = facetPool.filter((t) =>
    /* AND across selected plugins: picking "asr" + "pii" means templates that
       need both, which is how you actually narrow a catalogue. */
    activePlugins.every((p) => (t.required_plugins ?? []).includes(p)),
  )
  const hiddenNotRunnable = pluginFiltered.filter((t) => !passesRunnable(t)).length
  const filtered = pluginFiltered
    .filter(passesRunnable)
    .sort((a, b) => {
      if (sortBy === 'nodes') {
        return (b.node_count ?? 0) - (a.node_count ?? 0) || a.name.localeCompare(b.name)
      }
      if (sortBy === 'plugins') {
        return (
          (b.required_plugins?.length ?? 0) - (a.required_plugins?.length ?? 0) ||
          a.name.localeCompare(b.name)
        )
      }
      return (a.title || humanizeTemplateName(a.name)).localeCompare(b.title || humanizeTemplateName(b.name))
    })
  const exampleCount = searchPool.filter((t) => isExample(t.name)).length
  const savedCount = searchPool.filter((t) => !isExample(t.name)).length
  const workspaceCount = (items ?? []).length
  const marketplaceCount = marketplaceTotal ?? 0
  const runnableCount = searchPool.filter(
    (t) => runnableOf(t) || Boolean(t.group && runnableGroups.has(String(t.group))),
  ).length
  const filterState = { filter: filter === 'marketplace' ? 'all' : filter, runnableOnly, plugins: activePlugins } as const
  const pickFilter = (value: string) => {
    const next = applyTemplateFilter(value, { ...filterState, plugins: activePlugins })
    setFilter(next.filter)
    setActivePlugins(next.plugins)
    if (next.runnableOnly !== runnableOnly) setRunnableOnly(next.runnableOnly)
  }

  const shownLabel = (() => {
    if (filter === 'marketplace') {
      if (marketplaceStats == null || marketplaceTotal == null) return 'Loading marketplace…'
      return `${marketplaceStats.loaded} on page · ${marketplaceStats.matched} matched · ${marketplaceTotal} in catalog`
    }
    if (items == null) return 'Loading…'
    return `${filtered.length} shown`
  })()

  const entries: TemplateEntry<TemplateSummary>[] = groupTemplates(filtered)
  /** List order as rendered (groups expanded in step order). */
  const orderedNames = entries.flatMap((e) => (e.kind === 'single' ? [e.tpl.name] : e.steps.map((st) => st.tpl.name)))
  const firstRunnableName =
    orderedNames.find((n) => {
      const t = filtered.find((x) => x.name === n)
      return t ? runnableOf(t) : false
    }) ?? orderedNames[0] ?? null

  React.useEffect(() => {
    if (filter === 'marketplace') return
    if (!firstRunnableName) {
      setSelectedName(null)
      return
    }
    if (!selectedName || !orderedNames.includes(selectedName)) {
      setSelectedName(firstRunnableName)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, firstRunnableName, orderedNames.join('\n'), selectedName])

  /* Guided series: a later step (e.g. "Train model") reads what Step 1 wrote.
     Probe the step's declared input paths (GET /outputs/file: 200 file /
     400 "directory" = present) and fall back to the Datasets input labels. */
  const [stepReadiness, setStepReadiness] = React.useState<Record<string, StepReadiness>>({})
  const selectedStepInfo = selectedName ? findStep(entries, selectedName) : null
  const readinessTpl = selectedStepInfo && selectedStepInfo.step.step > 1 ? selectedStepInfo.step.tpl : null
  const readinessName = readinessTpl?.name ?? null
  const readinessInputs = (readinessTpl?.inputs ?? []).join('\n')
  React.useEffect(() => {
    if (!readinessName) return
    const inputs = readinessInputs.split('\n').filter((x) => x.trim())
    if (inputs.length === 0) {
      setStepReadiness((m) => ({ ...m, [readinessName]: 'unknown' }))
      return
    }
    let cancelled = false
    setStepReadiness((m) => ({ ...m, [readinessName]: 'checking' }))
    void (async () => {
      const fetchFn = (path: string) => apiFetch('/outputs/file', { query: { path } })
      let ok = true
      for (const path of inputs) {
        if (!(await probePathExists(path, fetchFn))) {
          ok = false
          break
        }
      }
      if (!ok) {
        try {
          const labels = unwrapList<{ label?: string; file_count?: number }>(await apiJson('/data/inputs'))
          ok = inputs.every((path) => {
            const m = /datasets\/input\/([^/]+)/.exec(path)
            return m ? labels.some((l) => l.label === m[1] && (l.file_count ?? 1) > 0) : false
          })
        } catch {
          /* keep "missing" */
        }
      }
      if (!cancelled) setStepReadiness((m) => ({ ...m, [readinessName]: ok ? 'ready' : 'missing' }))
    })()
    return () => {
      cancelled = true
    }
  }, [readinessName, readinessInputs, activeProject])

  const filterToolbar = (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-[12rem] flex-1 sm:max-w-xs">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search templates…"
          aria-label="Search templates"
          className="field-control mt-0 w-full pl-8 text-sm"
        />
      </div>
      {/* Two tabs: this server's starters (default, small) vs the Marketplace catalog. */}
      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Template source">
        <button
          type="button"
          role="tab"
          aria-selected={filter !== 'marketplace'}
          className={filter !== 'marketplace' ? 'catalog-pill catalog-pill-on' : 'catalog-pill'}
          onClick={() => setFilter('all')}
        >
          Starters {items != null ? workspaceCount : '…'}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={filter === 'marketplace'}
          className={filter === 'marketplace' ? 'catalog-pill catalog-pill-on' : 'catalog-pill'}
          onClick={() => setFilter('marketplace')}
          data-testid="templates-tab-marketplace"
        >
          Marketplace {marketplaceTotal != null ? marketplaceCount : '…'}
        </button>
      </div>
    </div>
  )

  const renderTemplateDetail = (tpl: TemplateSummary) => {
    const name = tpl.name
    const versions = versionsMap[name] ?? []
    const latest = latestMap[name]
    const inputLabel = datasetInputLabel(tpl)
    const missing = effectiveMissing(tpl)
    const stepInfo = findStep(entries, name)
    return (
      <article className="flex flex-col gap-3 rounded-lg border border-ink-200/70 bg-white p-4 shadow-sm">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-type-body font-semibold text-ink-950">
                {tpl.title || humanizeTemplateName(name)}
              </h2>
              {isExample(name) && filter !== 'examples' && (
                <span className="shrink-0 rounded-md bg-ink-100 px-1.5 py-px text-type-meta font-medium text-ink-500">
                  Example
                </span>
              )}
              {tpl.difficulty ? (
                <span className="shrink-0 rounded-md bg-accent-50 px-1.5 py-px text-type-meta font-medium capitalize text-accent-800">
                  {tpl.difficulty}
                </span>
              ) : null}
            </div>
            <div className="truncate font-mono text-type-meta text-ink-400" title={name}>
              {name}
            </div>
            <p className="mt-2 text-type-secondary text-ink-600">
              {tpl.description?.trim()
                ? tpl.description
                : 'Open in Editor to inspect nodes and run this pipeline.'}
            </p>
            {stepInfo ? (
              <div
                className="mt-3 rounded-lg border border-accent-200 bg-accent-50/50 p-3 text-[12px] text-ink-700"
                data-testid="template-guided-steps"
              >
                <div className="font-semibold text-ink-900">
                  {stepInfo.entry.title} · Step {stepInfo.step.step} of {stepInfo.entry.steps.length}:{' '}
                  {stepInfo.step.title}
                </div>
                <ol className="mt-2 flex flex-wrap items-center gap-1.5">
                  {stepInfo.entry.steps.map((st, i) => (
                    <li key={st.tpl.name} className="flex items-center gap-1.5">
                      {i > 0 ? <ChevronRight className="h-3 w-3 text-ink-300" aria-hidden /> : null}
                      <button
                        type="button"
                        className={clsx(
                          'rounded-full border px-2 py-0.5 text-[11px]',
                          st.tpl.name === name
                            ? 'border-accent-400 bg-white font-medium text-ink-950'
                            : 'border-ink-200 bg-white/70 text-ink-600 hover:border-accent-300',
                        )}
                        aria-current={st.tpl.name === name ? 'step' : undefined}
                        onClick={() => setSelectedName(st.tpl.name)}
                      >
                        Step {st.step} · {st.title}
                      </button>
                    </li>
                  ))}
                </ol>
                {stepInfo.step.step > 1 ? (
                  (() => {
                    const prev = stepInfo.entry.steps[stepInfo.step.step - 2]
                    const state = stepReadiness[name] ?? 'checking'
                    if (state === 'ready') {
                      return (
                        <p className="mt-2 text-emerald-800">
                          Step {prev.step} output found — the dataset is ready, you can run this step.
                        </p>
                      )
                    }
                    return (
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className={state === 'missing' ? 'text-amber-900' : 'text-ink-600'}>
                          {state === 'checking'
                            ? `Checking whether Step ${prev.step} has been run…`
                            : state === 'missing'
                              ? `Run Step ${prev.step} first — the dataset this step trains on isn’t there yet.`
                              : `Run Step ${prev.step} first if you haven’t already — this step uses its output.`}
                        </span>
                        <button
                          type="button"
                          className="btn-secondary !py-0.5 text-[11px]"
                          onClick={() => setSelectedName(prev.tpl.name)}
                        >
                          Open Step {prev.step}
                        </button>
                      </div>
                    )
                  })()
                ) : stepInfo.entry.steps[stepInfo.step.step] ? (
                  <p className="mt-2 text-ink-600">
                    Run this first. Then continue with{' '}
                    <button
                      type="button"
                      className="font-medium text-accent-800 hover:underline"
                      onClick={() => setSelectedName(stepInfo.entry.steps[stepInfo.step.step].tpl.name)}
                    >
                      Step {stepInfo.step.step + 1} · {stepInfo.entry.steps[stepInfo.step.step].title}
                    </button>
                    .
                  </p>
                ) : null}
              </div>
            ) : null}
            {missing.length > 0 ? (
              <div
                className="mt-2 inline-flex max-w-full items-start gap-1 rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-type-meta text-amber-900"
                title={summarizeMissing(missing, nodeTypePlugins).tooltip}
                data-testid="template-missing-plugins"
              >
                <Puzzle className="mt-px h-3 w-3 shrink-0" />
                <span className="min-w-0 break-words">
                  {summarizeMissing(missing, nodeTypePlugins).label}
                </span>
              </div>
            ) : null}
          </div>
          <div className="relative shrink-0" ref={menuFor === name ? menuRef : undefined}>
            <button
              type="button"
              className="btn-icon"
              aria-label={`More actions for ${tpl.title || humanizeTemplateName(name)}`}
              aria-expanded={menuFor === name}
              aria-haspopup="menu"
              onClick={(e) => {
                if (menuFor === name) {
                  setMenuFor(null)
                  return
                }
                const rect = e.currentTarget.getBoundingClientRect()
                setMenuUp(
                  window.innerHeight - rect.bottom <
                    (versions.length > 0 ? CARD_MENU_HEIGHT_PX : CARD_MENU_HEIGHT_PX / 2),
                )
                setMenuFor(name)
              }}
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
            {menuFor === name && (
              <div
                role="menu"
                className={clsx(
                  'absolute right-0 z-20 w-48 rounded-lg border border-ink-200 bg-white p-1.5 shadow-soft',
                  menuUp ? 'bottom-full mb-1' : 'top-full mt-1',
                )}
              >
                {versions.length > 0 && (
                  <ConfirmButton
                    label="Delete version"
                    confirmLabel="Confirm version"
                    danger
                    onConfirm={() => {
                      const ver = selectedVersion[name] || latest
                      if (!ver || ver === 'unversioned') return
                      void apiJson(`/pipelines/templates/${encodeURIComponent(name)}`, {
                        method: 'DELETE',
                        query: { version: ver },
                      })
                        .then(load)
                        .then(() => {
                          setMenuFor(null)
                          pushToast('Deleted version', 'success')
                        })
                        .catch((err) =>
                          pushToast(err instanceof Error ? err.message : String(err), 'error'),
                        )
                    }}
                  />
                )}
                <div className={versions.length > 0 ? 'mt-1' : ''}>
                  <ConfirmButton
                    label="Delete"
                    confirmLabel={
                      isExample(name) ? 'Confirm delete (Sync examples restores it)' : 'Confirm delete'
                    }
                    danger
                    onConfirm={() =>
                      void apiJson(`/pipelines/templates/${encodeURIComponent(name)}`, {
                        method: 'DELETE',
                      })
                        .then(load)
                        .then(() => {
                          setMenuFor(null)
                          pushToast(`Deleted ${tpl.title || humanizeTemplateName(name)}`, 'success')
                        })
                        .catch((err) =>
                          pushToast(err instanceof Error ? err.message : String(err), 'error'),
                        )
                    }
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        <dl className="grid gap-1.5 text-type-secondary text-ink-600">
          {tpl.inputs?.length ? (
            <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-start gap-2">
              <dt className="text-type-meta font-medium text-ink-400">Inputs</dt>
              <dd>
                {inputLabel ? (
                  <span className="flex flex-wrap gap-1">
                    {(tpl.inputs ?? []).slice(0, 4).map((raw) => (
                      <button
                        key={raw}
                        type="button"
                        className="inline-flex max-w-full items-center gap-1 rounded-md bg-ink-50 px-1.5 py-0.5 text-type-meta text-ink-600 transition hover:bg-accent-50 hover:text-accent-800"
                        title={`${raw} — open “${inputLabel}” in Datasets`}
                        onClick={() => {
                          openData({ mode: 'inputs', label: inputLabel })
                          pushToast(`Datasets — ${inputLabel} inputs`, 'info')
                        }}
                      >
                        <Database className="h-3 w-3 shrink-0" />
                        <span className="truncate">{shortPath(raw)}</span>
                      </button>
                    ))}
                  </span>
                ) : (
                  chipList(tpl.inputs, 'None declared', shortPath)
                )}
              </dd>
            </div>
          ) : null}
          {tpl.outputs?.length ? (
            <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-start gap-2">
              <dt className="text-type-meta font-medium text-ink-400">Outputs</dt>
              <dd>
                {chipList(tpl.outputs, 'None declared', (s) =>
                  s.includes('/') ? shortPath(s) : humanNodeLabel(s),
                )}
              </dd>
            </div>
          ) : null}
          {tpl.required_plugins?.length ? (
            <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-start gap-2">
              <dt className="text-type-meta font-medium text-ink-400">Plugins</dt>
              <dd className="flex flex-wrap gap-1">
                {tpl.required_plugins.map((p) => {
                  const on = activePlugins.includes(p)
                  return (
                    <button
                      key={p}
                      type="button"
                      aria-pressed={on}
                      title={
                        on ? `Stop filtering by ${p}` : `Show only templates that need ${p}`
                      }
                      className={`rounded-md px-1.5 py-0.5 text-type-meta transition ${
                        on
                          ? 'bg-accent-100 font-medium text-accent-900'
                          : 'bg-ink-50 text-ink-600 hover:bg-accent-50 hover:text-accent-800'
                      }`}
                      onClick={() => togglePlugin(p)}
                    >
                      {p}
                    </button>
                  )
                })}
              </dd>
            </div>
          ) : null}
        </dl>

        {tpl.tags?.some((t) => !HIDDEN_TAGS.has(t)) ? (
          <div className="flex flex-wrap gap-1">
            {tpl.tags
              .filter((t) => !HIDDEN_TAGS.has(t))
              .slice(0, 5)
              .map((t) => (
                <button
                  key={t}
                  type="button"
                  className="rounded-full border border-ink-200/80 px-1.5 py-px text-type-meta text-ink-500 transition hover:border-accent-300 hover:text-accent-800"
                  title={`Search for “${t}”`}
                  onClick={() => setSearch(t)}
                >
                  {t}
                </button>
              ))}
          </div>
        ) : null}

        {tpl.node_types?.length ? (
          <div
            className="flex flex-wrap items-center gap-x-1 gap-y-1 rounded-lg bg-ink-50/70 px-2 py-1.5"
            title={tpl.node_types.map(humanNodeLabel).join(' → ')}
          >
            {tpl.node_types.slice(0, 8).map((nt, i) => (
              <React.Fragment key={`${nt}-${i}`}>
                {i > 0 && <ChevronRight className="h-3 w-3 shrink-0 text-ink-300" />}
                <span className="truncate text-type-meta font-medium text-ink-600">
                  {humanNodeLabel(nt)}
                </span>
              </React.Fragment>
            ))}
            {tpl.node_types.length > 8 && (
              <span className="text-type-meta text-ink-400">+{tpl.node_types.length - 8}</span>
            )}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2 border-t border-ink-100 pt-3">
          {versions.length > 0 ? (
            <>
              <span className="text-type-meta text-ink-500">
                Latest {latest && latest !== 'unversioned' ? latest : versions[0]}
              </span>
              <select
                className="rounded-md border border-ink-200 bg-white px-1.5 py-0.5 text-type-meta"
                value={selectedVersion[name] ?? latest ?? ''}
                onChange={(e) => setSelectedVersion((s) => ({ ...s, [name]: e.target.value }))}
                aria-label={`Version for ${tpl.title || humanizeTemplateName(name)}`}
              >
                {versions.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </>
          ) : (tpl.node_count ?? 0) > 0 ? (
            <span className="text-type-meta text-ink-400">
              {tpl.node_count} node{(tpl.node_count ?? 0) === 1 ? '' : 's'}
            </span>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              className="btn-primary"
              title={
                activeProject
                  ? `Copy this graph into ${activeProject} and open it in the Editor`
                  : 'Pick a workspace, then open this graph in the Editor'
              }
              onClick={() => void loadIntoBuilder(name)}
            >
              Open in Editor
            </button>
          </div>
        </div>
      </article>
    )
  }

  const selectedTpl = selectedName ? filtered.find((t) => t.name === selectedName) : undefined

  return (
    <WorkbenchPage
      title="Templates"
      description={
        activeProject
          ? `Starter graphs to copy into a workspace. “Open in Editor” copies one into ${activeProject}; the original template is left untouched.`
          : 'Starter graphs to copy into a workspace. Opening one asks which workspace to copy it into, then loads it in the Editor.'
      }
      actions={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button type="button" className="btn-quiet" onClick={() => void load()} title="Refresh templates">
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
          <div className="relative" ref={headerMoreRef}>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setHeaderMoreOpen((o) => !o)}
              aria-expanded={headerMoreOpen}
              aria-haspopup="menu"
              aria-label="More template actions"
            >
              <MoreHorizontal className="h-3.5 w-3.5" /> More
            </button>
            {headerMoreOpen && (
              <div className="absolute right-0 z-20 mt-1 w-64 rounded-lg border border-ink-200 bg-white p-2 shadow-soft">
                <button
                  type="button"
                  className="btn-quiet w-full justify-start"
                  disabled={syncing}
                  onClick={() => {
                    void importExamples()
                    setHeaderMoreOpen(false)
                  }}
                  title="Copy example graphs into templates"
                >
                  <Download className="h-3.5 w-3.5" />
                  {syncing ? 'Syncing…' : 'Sync examples'}
                </button>
                {!saveOpen ? (
                  <button
                    type="button"
                    className="btn-quiet w-full justify-start"
                    onClick={() => setSaveOpen(true)}
                  >
                    Save from Editor
                  </button>
                ) : (
                  <div className="mt-1 space-y-2 border-t border-ink-100 pt-2">
                    <input
                      value={saveName}
                      onChange={(e) => setSaveName(e.target.value)}
                      placeholder="template-name"
                      className="field-control mt-0 w-full text-sm"
                      autoFocus
                    />
                    <div className="flex flex-wrap gap-1">
                      <button type="button" className="btn-primary" onClick={() => void saveFromCanvas()}>
                        Save
                      </button>
                      <button type="button" className="btn-quiet" onClick={uploadFile}>
                        <Upload className="h-3.5 w-3.5" /> Upload
                      </button>
                      <button
                        type="button"
                        className="btn-quiet"
                        onClick={() => {
                          setSaveOpen(false)
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      }
      toolbar={filterToolbar}
      bodyClassName="flex h-full min-h-0 flex-col overflow-hidden !px-0 !py-0"
    >
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="shrink-0 space-y-2.5 px-4 pt-3 sm:px-6">
          {error && <ErrorBanner message={error} onRetry={() => void load()} />}
          {syncBanner && (
            <ErrorBanner
              title={`Sync finished with ${syncBanner.errors.length} issue${syncBanner.errors.length === 1 ? '' : 's'}`}
              message={`Imported ${syncBanner.written} template${syncBanner.written === 1 ? '' : 's'}. Review the issues below — the list still shows what succeeded.`}
              detail={syncBanner.errors
                .map((e) => (typeof e === 'string' ? e : `${e.id ?? 'item'}: ${e.error ?? 'unknown'}`))
                .join('\n')}
              onDismiss={() => setSyncBanner(null)}
              onRetry={() => void importExamples()}
            />
          )}

          <div className="flex flex-wrap items-center gap-2">
            {filter === 'marketplace' ? (
              <span className="text-[12px] text-ink-400">{shownLabel}</span>
            ) : (
              <>
                <label className="flex items-center gap-1.5 text-[12px] text-ink-500">
                  Sort
                  <select
                    className="rounded-md border border-ink-200 bg-white px-2 py-1 text-[12px] text-ink-800"
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as TemplateSort)}
                  >
                    {(Object.keys(TEMPLATE_SORT_LABEL) as TemplateSort[]).map((k) => (
                      <option key={k} value={k}>
                        {TEMPLATE_SORT_LABEL[k]}
                      </option>
                    ))}
                  </select>
                </label>
                <label
                  className="flex items-center gap-1.5 text-[12px] text-ink-500"
                  title="Runnable here hides templates that use nodes this server doesn't have installed"
                >
                  Show
                  <select
                    className="rounded-md border border-ink-200 bg-white px-2 py-1 text-[12px] text-ink-800"
                    value={templateFilterValue(filterState)}
                    onChange={(e) => pickFilter(e.target.value)}
                    data-testid="templates-runnable-only"
                    aria-label="Show templates"
                  >
                    <option value="runnable">Runnable here ({runnableCount})</option>
                    <option value="all">All starters ({searchPool.length})</option>
                    <option value="examples">Examples ({exampleCount})</option>
                    <option value="saved">Saved ({savedCount})</option>
                    {activePlugins.length > 1 ? (
                      <option value="plugins">Needs {activePlugins.join(' + ')}</option>
                    ) : null}
                    {facets.length > 0 ? (
                      <optgroup label="Needs plugin">
                        {facets.map(([p, n]) => (
                          <option key={p} value={`plugin:${p}`}>
                            {p} ({n})
                          </option>
                        ))}
                      </optgroup>
                    ) : null}
                  </select>
                </label>
                <span className="ml-auto text-[12px] text-ink-400">{shownLabel}</span>
              </>
            )}
          </div>

        </div>

        {filter === 'marketplace' ? (
          <div className="flex min-h-0 flex-1 flex-col px-4 pb-4 sm:px-6">
            <MarketplaceBrowse search={search} onStats={onMarketplaceStats} />
          </div>
        ) : items === null ? (
          <div className="px-4 sm:px-6">
            <LoadingBlock />
          </div>
        ) : filtered.length === 0 ? (
          <div className="px-4 sm:px-6">
            <EmptyState
              icon={EmptyLayoutTemplate}
              title={
                search.trim()
                  ? 'No matching templates'
                  : filter === 'examples'
                    ? 'No example templates'
                    : 'No templates'
              }
              description={
                hiddenNotRunnable > 0
                  ? `${hiddenNotRunnable} template${hiddenNotRunnable === 1 ? '' : 's'} need plugins this server doesn't have. Show “All starters” to see them.`
                  : activePlugins.length > 0
                  ? `Nothing requires ${activePlugins.join(' + ')}${search.trim() ? ` and matches “${search.trim()}”` : ''}.`
                  : search.trim()
                    ? `Nothing matches “${search.trim()}”. Try another term or clear search.`
                    : filter === 'examples'
                      ? 'Sync example graphs from the repo, then open one in Editor.'
                      : 'Sync examples, save from Editor, or upload a graph file.'
              }
              action={
                hiddenNotRunnable > 0 ? (
                  <button type="button" className="btn-secondary" onClick={() => setRunnableOnly(false)}>
                    Show all templates
                  </button>
                ) : activePlugins.length > 0 ? (
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setActivePlugins([])}
                  >
                    Clear plugin filters
                  </button>
                ) : !search.trim() ? (
                  <button type="button" className="btn-secondary" onClick={() => void importExamples()}>
                    Sync examples
                  </button>
                ) : undefined
              }
            />
          </div>
        ) : (
          <MasterDetail
            className="min-h-0 flex-1 px-4 pb-4 sm:px-6"
            listLabel="templates"
            storageKey="graphyn.templates"
            selectedKey={selectedName ?? null}
            collapsible
            defaultSize={300}
            masterClassName="!bg-transparent"
            detailClassName="!pl-4"
            master={
              <ul className="divide-y divide-ink-100 overflow-hidden rounded-lg border border-ink-200 bg-white">
                {entries.map((entry) => {
                  if (entry.kind === 'group') {
                    return (
                      <li key={`group:${entry.group}`} className="bg-accent-50/30 px-1 py-1.5">
                        <div className="px-2 pb-1">
                          <span className="block truncate text-[12px] font-semibold text-ink-950">{entry.title}</span>
                          <span className="text-[11px] text-ink-400">
                            Guided · {entry.steps.length} steps
                          </span>
                        </div>
                        {entry.steps.map((st) => {
                          const active = st.tpl.name === selectedName
                          const runnable = runnableOf(st.tpl)
                          return (
                            <button
                              key={st.tpl.name}
                              type="button"
                              onClick={() => setSelectedName(st.tpl.name)}
                              title={st.tpl.name}
                              className={clsx('ide-row w-full !py-1.5 !px-3', active && 'is-active')}
                            >
                              <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent-100 text-[10px] font-semibold text-accent-900">
                                {st.step}
                              </span>
                              <span className="min-w-0 flex-1 truncate text-ink-900">{st.title}</span>
                              {!runnable ? (
                                <Puzzle className="h-3 w-3 shrink-0 text-amber-700" aria-label="Needs plugins" />
                              ) : null}
                            </button>
                          )
                        })}
                      </li>
                    )
                  }
                  const tpl = entry.tpl
                  const active = tpl.name === selectedName
                  const runnable = runnableOf(tpl)
                  return (
                    <li key={tpl.name}>
                      <button
                        type="button"
                        onClick={() => setSelectedName(tpl.name)}
                        title={tpl.name}
                        className={clsx(
                          'ide-row w-full flex-col items-start gap-0.5 !py-2 !px-3',
                          active && 'is-active',
                        )}
                      >
                        <span className="flex w-full items-center gap-1.5">
                          <span className="min-w-0 flex-1 truncate font-medium text-ink-950">
                            {tpl.title || humanizeTemplateName(tpl.name)}
                          </span>
                          {!runnable ? (
                            <span
                              className="shrink-0 rounded bg-amber-50 px-1 text-[10px] font-medium text-amber-800"
                              title="Uses nodes this server doesn't have installed"
                            >
                              Needs plugins
                            </span>
                          ) : null}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            }
            detail={
              selectedTpl ? (
                <>
                  <MasterDetailToggle className="mb-2" />
                  {renderTemplateDetail(selectedTpl)}
                </>
              ) : (
                <EmptyState
                  compact
                  title="Select a template"
                  description="Choose a template from the list to preview details and open it in the Editor."
                />
              )
            }
          />
        )}
      </div>

      {projectGate && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-ink-950/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="project-gate-title"
          onClick={() => !projectGateBusy && setProjectGate(null)}
        >
          <div
            className="w-full max-w-md rounded-lg border border-ink-200 bg-white p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="project-gate-title" className="text-lg font-semibold text-ink-950">
              Templates stamp into a workspace
            </h2>
            <p className="mt-2 text-sm text-ink-500">
              Create or select a workspace, then open the graph in the Editor.
            </p>
            {(() => {
              const missing = effectiveMissing(items?.find((t) => t.name === projectGate.template))
              if (missing.length === 0) return null
              const summary = summarizeMissing(missing, nodeTypePlugins, 8)
              return (
                <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
                  <Puzzle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span title={summary.tooltip}>
                    {summary.label}. You can open it anyway — those nodes will not run until the
                    plugins are installed (Library → Plugins).
                  </span>
                </div>
              )
            })()}
            <label className="mt-4 block text-sm text-ink-600">
              Existing workspace
              <select
                className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
                value={projectPick}
                onChange={(e) => setProjectPick(e.target.value)}
                disabled={projectChoices.length === 0}
              >
                {projectChoices.length === 0 ? (
                  <option value="">No workspaces yet</option>
                ) : (
                  projectChoices.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))
                )}
              </select>
            </label>
            <label className="mt-3 block text-sm text-ink-600">
              Or create new
              <input
                className={`mt-1 w-full rounded-lg border px-3 py-2 text-sm ${
                  projectCreateError ? 'border-rose-300 bg-rose-50/40' : 'border-ink-200'
                }`}
                placeholder="my-workspace"
                value={projectCreate}
                aria-invalid={projectCreateError ? true : undefined}
                onChange={(e) => setProjectCreate(e.target.value)}
              />
              {projectCreateError ? (
                <span className="mt-1 block text-[12px] text-rose-700" role="alert">
                  {projectCreateError}
                </span>
              ) : null}
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                className="btn-secondary"
                disabled={projectGateBusy}
                onClick={() => setProjectGate(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={projectGateBusy || Boolean(projectCreate.trim() && projectCreateError)}
                onClick={() => void confirmProjectGate()}
              >
                {projectGateBusy ? 'Opening…' : 'Open in Editor'}
              </button>
            </div>
          </div>
        </div>
      )}
    </WorkbenchPage>
  )
}
