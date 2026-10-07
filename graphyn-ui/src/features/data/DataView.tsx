import React from 'react'
import { Database as EmptyDatabase, FolderOpen as EmptyFolderOpen, Tags as EmptyTags, TriangleAlert as EmptyTriangleAlert } from 'lucide-react'
import { ArrowDown, ArrowUp, Check, Download, File as FileGeneric, FileAudio, FileImage, FileJson, FileSpreadsheet, FileText, HelpCircle, Lock, Play, RefreshCw, Search, Upload, X } from 'lucide-react'
import {
  apiFetch,
  apiJson,
  apiUrl,
  getApiToken,
} from '../../api/client'
import { unwrapList } from '../../api/unwrapList'
import { normalizeDatasetRows } from './datasetRows'
import { mostUsedInputLabel, usedInputLabels } from './datasetUsage'
import { UploadPanel } from './UploadPanel'
import {
  DEFAULT_UPLOAD_LIMITS,
  downloadZip,
  isSnapshotProject,
  zipPath,
  type DataCapabilities,
} from './dataApi'
import { outputSelectionKnown } from './outputSelection'
import { useAppStore } from '../../store/appStore'
import {
  ConfirmButton,
  CopyableMono,
  EmptyState,
  ErrorBanner,
  KeyValue,
  LoadingBlock,
  SegmentedTabs,
} from '../../components/ui'
import { MasterDetail, MasterDetailToggle, WorkbenchPage } from '../../layout'
import { FileViewer } from '../../components/FileViewer'
import clsx from 'clsx'
import {
  formatBytes,
  formatExecutionLine,
  formatLocaleDateTime,
  formatMergeToast,
  formatRelativeTime,
} from '../../lib/format'
import { goView, onPathChange, readSearchParams, replacePathSearch } from '../../routes/nav'
import { paths } from '../../routes/paths'
import { safeDecode } from '../../routes/parsePath'
import { naturalCompare } from '../../lib/naturalSort'

interface OutputProject {
  project: string
  versions: string[]
  kind?: 'input_snapshot' | 'artifact_dataset' | string
  fs_path?: string
  label?: string
}
interface InputLabel {
  label: string
  /** Every (non-hidden) file, any type. */
  file_count: number
  /** Audio subset of file_count. */
  audio_count?: number
  /** false when label resolves outside datasets/input (external symlink). */
  accessible?: boolean
}

type DataMode = 'outputs' | 'inputs' | 'ingest' | 'merge'
type ManageTab = 'upload' | 'ingest' | 'merge'

const LIST_CAP = 200
/** First page size for Outputs detail (matches API default `limit`). */
const OUTPUT_PAGE = 200
const OUTPUT_FILE_PREFIX = 'workspace/datasets/output/'

type OutputDetailCache = {
  rows: Array<Record<string, unknown>>
  stats: unknown
  fileCount: number
  truncated: boolean
  nextOffset: number
  datasetFiles: Array<Record<string, unknown>>
  provenance: string | null
}

/** One-line provenance from a version manifest's `source` block. */
function describeOutputSource(source: unknown): string | null {
  if (!source || typeof source !== 'object') return null
  const s = source as Record<string, unknown>
  const kind = String(s.kind ?? '')
  if (kind === 'input_label' && s.label) return `Frozen from input “${String(s.label)}”`
  if (kind === 'artifact_publish') {
    const from = String(s.from ?? '').replace(/\\/g, '/')
    const m = from.match(/artifacts\/[^/]+\/dataset\/(.+)$/)
    return m ? `Published from legacy ${m[1]}` : 'Published from a legacy artifact'
  }
  if (kind === 'merge' && Array.isArray(s.sources)) {
    return `Merged from ${s.sources.length} version${s.sources.length === 1 ? '' : 's'}`
  }
  if (s.run_id) return `Written by run ${String(s.run_id).slice(0, 8)}`
  return null
}

const SPLIT_ORDER = ['train', 'val', 'dev', 'test']
/** Sort rank for split names; rows without a split sort first (they are not samples). */
function splitRank(split: unknown): number {
  if (typeof split !== 'string' || !split) return 0
  return SPLIT_ORDER.indexOf(split) + 1 || 99
}

/** `0.7 s`, `1 s`, `12 s` — keeps sub-second clips distinguishable. */
function formatClipSeconds(s: number): string {
  if (!Number.isFinite(s)) return '?'
  return s < 10 ? String(Number(s.toFixed(2))) : String(Math.round(s))
}

function sanitizePathSeg(value: string | undefined | null): string | undefined {
  const v = (value || '').trim()
  if (!v) return undefined
  // Frozen input labels are addressed as `_inputs/<label>` (one slash, allowed).
  if (isSnapshotProject(v) && !v.includes('\\') && !v.includes('..')) return v
  // Soft-listed legacy artifact datasets use `_artifacts/<slug>/<name>`.
  if (v.startsWith('_artifacts/') && !v.includes('\\') && !v.includes('..')) return v
  // Reject path-like hash/state — never send nested segments to /data/outputs/{project}/{version}.
  if (v.includes('/') || v.includes('\\')) return undefined
  return v
}

/** `/data/outputs/<project>/<version>`; `_inputs/<label>` keeps its slash (each segment encoded). */
function outputVersionPath(project: string, version: string): string {
  return `/data/outputs/${project.split('/').map(encodeURIComponent).join('/')}/${encodeURIComponent(version)}`
}

function rowKindIcon(kind: unknown) {
  switch (kind) {
    case 'table':
      return FileSpreadsheet
    case 'json':
      return FileJson
    case 'text':
    case 'pdf':
      return FileText
    case 'image':
      return FileImage
    case 'audio':
      return FileAudio
    default:
      return FileGeneric
  }
}

interface InputStats {
  label: string
  file_count: number
  total_bytes: number
  by_kind: Record<string, number>
  classes: Array<{ name: string; file_count: number; audio_count: number; bytes: number }>
  audio: {
    count: number
    probed?: number
    sampled?: boolean
    unreadable?: number
    sample_rates?: Record<string, number>
    channels?: Record<string, number>
    duration_s?: { min: number; max: number; mean: number }
    estimated_total_duration_s?: number
  }
}

function parseDataLocation(): {
  mode?: DataMode
  project?: string
  version?: string
  label?: string
  manage?: boolean
  onWorkspaceDatasets?: boolean
  /** Workspace id from `/workspaces/:id/datasets` (shell), may differ from Outputs selection. */
  workspacePathId?: string
} {
  const params = readSearchParams()
  const parts = window.location.pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  let projectFromPath: string | undefined
  if (parts[0] === 'workspaces' && parts[1] && parts[2] === 'datasets') {
    projectFromPath = safeDecode(parts[1])
  }
  const modeRaw = (params.get('mode') || '').trim()
  const mode = (['outputs', 'inputs', 'ingest', 'merge'] as const).includes(modeRaw as DataMode)
    ? (modeRaw as DataMode)
    : undefined
  const manageRaw = (params.get('manage') || '').trim().toLowerCase()
  const manage =
    manageRaw === '1' || manageRaw === 'true' || manageRaw === 'yes'
      ? true
      : manageRaw === '0' || manageRaw === 'false'
        ? false
        : undefined
  const onWorkspaceDatasets = Boolean(projectFromPath)
  const projectParam = sanitizePathSeg(params.get('project'))
  // Outputs: prefer explicit ?project= (shared library pick) over the workspace
  // path id. Path id only seeds when no query project is set — otherwise every
  // replacePathSearch→popstate yanked the selection back to the shell workspace
  // and spammed 404s for missing versions (e.g. e06/v2 while browsing e06/v1).
  return {
    mode,
    project:
      mode === 'inputs'
        ? projectParam
        : projectParam ?? sanitizePathSeg(projectFromPath),
    version: sanitizePathSeg(params.get('version')),
    label: sanitizePathSeg(params.get('label')),
    manage,
    onWorkspaceDatasets,
    workspacePathId: sanitizePathSeg(projectFromPath),
  }
}

function isInvalidWorkspacePathError(detail: string): boolean {
  return /path is outside workspace|invalid path segment|dataset not found/i.test(detail)
}

function humanizeDataError(
  err: unknown,
  kind: 'inputs' | 'outputs' | 'list' = 'list',
): { message: string; detail: string; invalidPath: boolean } {
  const detail = err instanceof Error ? err.message : String(err)
  if (isInvalidWorkspacePathError(detail)) {
    if (kind === 'inputs') {
      return {
        message:
          'This dataset folder links to a location outside the datasets area, so the server blocks it. Pick another folder, or ask an admin to allow external links.',
        detail: `${detail}\n${'Admin: set GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1 on the API to allow folders that link outside the datasets area.'}`,
        invalidPath: true,
      }
    }
    if (kind === 'outputs') {
      return {
        message:
          'That output version no longer exists. The selection was cleared — pick another workspace and version.',
        detail,
        invalidPath: true,
      }
    }
    return {
      message: 'The server rejected that dataset location. Try refreshing the list.',
      detail,
      invalidPath: true,
    }
  }
  return { message: detail, detail, invalidPath: false }
}

function manageTabFromMode(mode: DataMode): ManageTab {
  if (mode === 'ingest') return 'ingest'
  if (mode === 'merge') return 'merge'
  return 'upload'
}

function matchesQuery(haystack: string, q: string): boolean {
  if (!q.trim()) return true
  return haystack.toLowerCase().includes(q.trim().toLowerCase())
}

export default function DataView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const openProjects = useAppStore((s) => s.openProjects)
  const activeProject = useAppStore((s) => s.activeProject)
  const dataUnscopeEpoch = useAppStore((s) => s.dataUnscopeEpoch)
  const initialLoc = React.useMemo(() => parseDataLocation(), [])
  const [outputs, setOutputs] = React.useState<OutputProject[]>([])
  const [inputs, setInputs] = React.useState<InputLabel[]>([])
  const [mode, setMode] = React.useState<DataMode>(initialLoc.mode ?? 'inputs')
  const [uxMode, setUxMode] = React.useState<'browse' | 'manage'>(() => {
    if (initialLoc.manage === true) return 'manage'
    if (initialLoc.manage === false) return 'browse'
    const m = initialLoc.mode
    return m === 'ingest' || m === 'merge' ? 'manage' : 'browse'
  })
  const [manageTab, setManageTab] = React.useState<ManageTab>(() =>
    manageTabFromMode(initialLoc.mode ?? 'inputs'),
  )
  const [project, setProject] = React.useState(initialLoc.project ?? '')
  const [version, setVersion] = React.useState(initialLoc.version ?? '')
  const [label, setLabel] = React.useState(initialLoc.label ?? '')
  const [rows, setRows] = React.useState<Array<Record<string, unknown>>>([])
  const [stats, setStats] = React.useState<unknown>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [errorDetail, setErrorDetail] = React.useState<string | null>(null)
  const [pathRecovery, setPathRecovery] = React.useState(false)
  const [listFilter, setListFilter] = React.useState('')
  const [sortKey, setSortKey] = React.useState<'path' | 'size' | 'modified'>('path')
  const [sortDir, setSortDir] = React.useState<'asc' | 'desc'>('asc')
  /* The cap is a render guard, not a data limit — raising it is the user's call,
     so the footer offers it rather than silently hiding the rest. */
  const [listCap, setListCap] = React.useState(LIST_CAP)
  const toggleSort = (key: 'path' | 'size' | 'modified') => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
      return
    }
    setSortKey(key)
    // Size and date are most useful largest/newest-first; names read A–Z.
    setSortDir(key === 'path' ? 'asc' : 'desc')
  }
  const [detailEpoch, setDetailEpoch] = React.useState(0)
  const [outputFileCount, setOutputFileCount] = React.useState(0)
  const [outputTruncated, setOutputTruncated] = React.useState(false)
  const [outputDatasetFiles, setOutputDatasetFiles] = React.useState<Array<Record<string, unknown>>>([])
  const [outputProvenance, setOutputProvenance] = React.useState<string | null>(null)
  /** Split filter is scoped to the selection it was picked on, so a new
   *  version starts unfiltered in the same render (no filtered-then-unfiltered fetch pair). */
  const splitScope = `${mode}|${project}/${version}`
  const [splitState, setSplitState] = React.useState({ scope: '', value: '' })
  const splitFilter = splitState.scope === splitScope ? splitState.value : ''
  const setSplitFilter = (value: string) => setSplitState({ scope: splitScope, value })
  /** null = follow auto-open (selection elsewhere / filter / no own versions); a user toggle wins. */
  const [libraryOpen, setLibraryOpen] = React.useState<boolean | null>(null)
  const [loadingMoreOutputs, setLoadingMoreOutputs] = React.useState(false)
  const skippedOutputKey = React.useRef<string | null>(null)
  /** Input labels that failed with invalid-path — do not auto-reselect after clear. */
  const skippedInputLabels = React.useRef<Set<string>>(new Set())
  /** After closeProject: keep outputs dropdown empty; do not revive prior project via loadSources/path-sync. */
  const libraryClearRef = React.useRef(false)
  /** Omit project from search while clearing — prevents stale React state from re-writing query. */
  const skipProjectHashRef = React.useRef(false)
  const appliedUnscopeEpochRef = React.useRef<number | null>(null)
  /** Catalogue snapshot for detail effect without re-fetching on every outputs reload. */
  const outputsRef = React.useRef(outputs)
  outputsRef.current = outputs
  const outputsLoaded = outputs.length > 0
  /** In-memory Outputs detail pages keyed by project/version. */
  const outputDetailCacheRef = React.useRef(new Map<string, OutputDetailCache>())
  const lastDetailEpochRef = React.useRef(0)
  /** `key` is `<project>/<version>`; drops every split variant (`…#train`) of it. */
  const invalidateOutputDetail = React.useCallback((key?: string) => {
    const cache = outputDetailCacheRef.current
    if (!key) {
      cache.clear()
      return
    }
    const base = key.split('#')[0]
    for (const k of [...cache.keys()]) if (k.split('#')[0] === base) cache.delete(k)
  }, [])
  // Active ingest stream (EventSource or fetch reader) — closed on unmount so
  // it stops consuming the server stream and never toasts into another view.
  const ingestStreamCancelRef = React.useRef<(() => void) | null>(null)
  const unmountedRef = React.useRef(false)
  React.useEffect(() => {
    unmountedRef.current = false
    return () => {
      unmountedRef.current = true
      ingestStreamCancelRef.current?.()
      ingestStreamCancelRef.current = null
    }
  }, [])
  const [loading, setLoading] = React.useState(true)
  const [previewFile, setPreviewFile] = React.useState<{ path: string; kind: 'files' | 'input-files' } | null>(
    null,
  )

  // Layout before path-sync effect: reset selection when workspace project is closed.
  React.useLayoutEffect(() => {
    const first = appliedUnscopeEpochRef.current === null
    const prevEpoch = appliedUnscopeEpochRef.current
    appliedUnscopeEpochRef.current = dataUnscopeEpoch
    if (first) {
      // Mounted after a close into library Data (unscoped): prevent loadSources from auto-picking
      // the previous workspace project. Honor explicit openData({ project }) / deep links.
      if (dataUnscopeEpoch > 0 && activeProject == null && !initialLoc.project) {
        libraryClearRef.current = true
        skipProjectHashRef.current = true
        setProject('')
        setVersion('')
      }
      return
    }
    if (prevEpoch !== dataUnscopeEpoch) {
      libraryClearRef.current = true
      skipProjectHashRef.current = true
      setProject('')
      setVersion('')
    }
  }, [dataUnscopeEpoch, activeProject])

  // ingest
  const [urls, setUrls] = React.useState('')
  const [ingestLabel, setIngestLabel] = React.useState('uploads')
  const [hfRepo, setHfRepo] = React.useState('')
  const [hfSplit, setHfSplit] = React.useState('train')
  const [hfAudioCol, setHfAudioCol] = React.useState('audio')
  const [hfLabelCol, setHfLabelCol] = React.useState('label')
  const [hfLabelOverride, setHfLabelOverride] = React.useState('')
  const [hfMaxRows, setHfMaxRows] = React.useState(10000)
  const [hfRevision, setHfRevision] = React.useState('')
  const [ingestLog, setIngestLog] = React.useState<string[]>([])

  // Upload limits + which import sources the API host can run (GET /data/capabilities).
  const [caps, setCaps] = React.useState<DataCapabilities | null>(null)
  React.useEffect(() => {
    let cancelled = false
    apiJson<DataCapabilities>('/data/capabilities')
      .then((c) => {
        if (!cancelled) setCaps(c)
      })
      .catch(() => {
        if (!cancelled) setCaps(null)
      })
    return () => {
      cancelled = true
    }
  }, [])
  const [showUpload, setShowUpload] = React.useState(false)
  const [inputStats, setInputStats] = React.useState<InputStats | null>(null)
  const [inputStatsOpen, setInputStatsOpen] = React.useState(false)
  const [mergeOverwrite, setMergeOverwrite] = React.useState(false)

  // merge
  const [mergeSources, setMergeSources] = React.useState('')
  const [mergeTargetProject, setMergeTargetProject] = React.useState('')
  const [mergeTargetVersion, setMergeTargetVersion] = React.useState('v1')

  const loadSources = React.useCallback(async () => {
    setError(null)
    setErrorDetail(null)
    setLoading(true)
    try {
      const [out, inp] = await Promise.all([
        apiJson('/data/outputs').then((r) =>
          unwrapList<OutputProject>(r)
            .filter((o) => o && typeof o.project === 'string')
            .map((o) => ({ ...o, versions: Array.isArray(o.versions) ? o.versions : [] })),
        ),
        apiJson('/data/inputs').then((r) =>
          unwrapList<InputLabel>(r).filter((i) => i && typeof i.label === 'string'),
        ),
      ])
      setOutputs(out)
      setInputs(inp)
      setProject((prev) => {
        const safe = sanitizePathSeg(prev) ?? ''
        const skip = skippedOutputKey.current
        const usable = out.flatMap((o) =>
          o.versions
            .filter((v) => `${o.project}/${v}` !== skip)
            .map((v) => ({ project: o.project, version: v })),
        )
        if (skip) {
          // After an invalid-path recovery, do not auto-pick the failing combo (or any).
          // Leave empty so EmptyState CTAs / manual select drive next steps.
          setVersion('')
          skippedOutputKey.current = null
          return ''
        }
        // Global library after closeProject: do not prefer previous project from local state.
        if (libraryClearRef.current || (useAppStore.getState().activeProject == null && skipProjectHashRef.current)) {
          setVersion('')
          return ''
        }
        // Default selection matches the list order: the open workspace's versions
        // lead the list, so they should be the default too — not the
        // alphabetically-first catalogue entry.
        const home = (useAppStore.getState().activeProject || '').trim()
        const homePick =
          home && !out.find((o) => o.project === home)?.kind
            ? usable.find((u) => u.project === home)
            : undefined
        const proj =
          safe && out.some((o) => o.project === safe)
            ? safe
            : (homePick?.project ?? usable[0]?.project ?? '')
        const vers = out.find((o) => o.project === proj)?.versions ?? []
        setVersion((vPrev) => {
          const vSafe = sanitizePathSeg(vPrev) ?? ''
          if (vSafe && vers.includes(vSafe)) return vSafe
          return vers[0] ?? ''
        })
        return proj
      })
      setLabel((prev) => {
        const safe = sanitizePathSeg(prev) ?? ''
        const skip = skippedInputLabels.current
        const usable = inp.filter((i) => i.accessible !== false && !skip.has(i.label))
        if (safe && usable.some((i) => i.label === safe)) return safe
        // Prefer accessible labels; seed skip set from API so we never auto-pick blocked ones.
        for (const i of inp) {
          if (i.accessible === false) skip.add(i.label)
        }
        return usable[0]?.label ?? ''
      })
    } catch (err) {
      const h = humanizeDataError(err, 'list')
      setError(h.message)
      setErrorDetail(h.detail)
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    void loadSources()
  }, [loadSources])

  React.useEffect(() => {
    const apply = () => {
      const h = parseDataLocation()
      if (h.mode) {
        setMode(h.mode)
        setManageTab(manageTabFromMode(h.mode))
      }
      if (h.manage === true) setUxMode('manage')
      else if (h.manage === false) setUxMode('browse')
      else if (h.mode === 'ingest' || h.mode === 'merge') setUxMode('manage')
      const onDatasetsPath =
        window.location.pathname.includes('/datasets') ||
        window.location.pathname.startsWith('/library/datasets')
      // Workspace path id only seeds Outputs selection — never Inputs labels.
      const modeNow = h.mode ?? mode
      if (modeNow === 'outputs' || !h.mode) {
        if (h.project && !skipProjectHashRef.current) {
          libraryClearRef.current = false
          setProject(h.project)
        } else if (onDatasetsPath && !readSearchParams().has('project') && !h.project) {
          libraryClearRef.current = true
          skipProjectHashRef.current = true
          setProject('')
          setVersion('')
        }
      }
      if (h.version && !skipProjectHashRef.current) setVersion(h.version)
      if (h.label) setLabel(h.label)
    }
    return onPathChange(apply)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Write selection into pathname search. replacePathSearch → navigatePath dispatches
  // popstate, so Outputs selection must be round-trippable via ?project= (not only the
  // /workspaces/:id path shell) or the shell id overwrites a shared-library pick.
  React.useEffect(() => {
    const parts = window.location.pathname.replace(/\/+$/, '').split('/').filter(Boolean)
    const onWorkspaceDatasets =
      parts[0] === 'workspaces' && Boolean(parts[1]) && parts[2] === 'datasets'
    const params: Record<string, string | undefined> = {}
    if (mode) params.mode = mode
    if (uxMode === 'manage' && (mode === 'inputs' || mode === 'outputs')) {
      params.manage = '1'
    }
    // When activeProject was cleared, do not re-write stale project into the search.
    if (skipProjectHashRef.current) {
      if (!project.trim()) {
        skipProjectHashRef.current = false
      }
      // omit project + version while clearing / stale
    } else if (mode === 'outputs' && project.trim()) {
      params.project = project.trim()
      if (version.trim()) params.version = version.trim()
    } else if (onWorkspaceDatasets) {
      // Inputs (and other modes) on a workspace page: keep label; do not force Outputs project.
      if (version.trim() && mode === 'outputs') params.version = version.trim()
    } else if (project.trim()) {
      params.project = project.trim()
      if (version.trim()) params.version = version.trim()
    } else if (version.trim()) {
      params.version = version.trim()
    }
    if (label.trim()) params.label = label.trim()
    replacePathSearch(params)
  }, [mode, uxMode, project, version, label, dataUnscopeEpoch])

  React.useEffect(() => {
    let cancelled = false
    const run = async () => {
      setOutputDatasetFiles([])
      setOutputProvenance(null)
      // Do not clear a banner from list-load while a detail retry is in flight for the same selection.
      if (mode === 'outputs') {
        if (!project || !version) {
          setRows([])
          setStats(null)
          setOutputFileCount(0)
          setOutputTruncated(false)
          return
        }
        const outs = outputsRef.current
        // Avoid requesting phantom pairs (e.g. shell workspace + leftover ?version=v2)
        // once the catalogue is known — stops /stats 404 storms in the console.
        if (outs.length > 0 && !outputSelectionKnown(outs, project, version)) {
          const vers = outs.find((o) => o.project === project)?.versions ?? []
          if (vers.length > 0) {
            setVersion(vers[0] ?? '')
            return
          }
          setRows([])
          setStats(null)
          setOutputFileCount(0)
          setOutputTruncated(false)
          return
        }
        const meta = outs.find((o) => o.project === project)
        if (meta?.kind === 'artifact_dataset') {
          // Soft-listed legacy trees are not browsable via /data/outputs — show publish CTA.
          setRows([])
          setStats({
            project,
            version,
            kind: 'artifact_dataset',
            fs_path: meta.fs_path,
            note: 'Legacy artifact dataset — publish into this workspace to browse and reuse from Outputs.',
          })
          setPathRecovery(false)
          setError(null)
          setErrorDetail(null)
          setOutputFileCount(0)
          setOutputTruncated(false)
          return
        }
        const cacheKey = `${project}/${version}#${splitFilter}`
        if (detailEpoch !== lastDetailEpochRef.current) {
          lastDetailEpochRef.current = detailEpoch
          invalidateOutputDetail(cacheKey)
        }
        const cached = outputDetailCacheRef.current.get(cacheKey)
        if (cached) {
          setPathRecovery(false)
          setError(null)
          setErrorDetail(null)
          setRows(cached.rows)
          setStats(cached.stats)
          setOutputFileCount(cached.fileCount)
          setOutputTruncated(cached.truncated)
          setOutputDatasetFiles(cached.datasetFiles)
          setOutputProvenance(cached.provenance)
          return
        }
        setError(null)
        setErrorDetail(null)
        // Never show (or "Load more" against) the previous selection's rows.
        setRows([])
        setStats(null)
        setOutputFileCount(0)
        setOutputTruncated(false)
        try {
          const path = outputVersionPath(project, version)
          const [data, st] = await Promise.all([
            apiJson<Record<string, unknown>>(path, {
              query: { limit: OUTPUT_PAGE, offset: 0, ...(splitFilter ? { split: splitFilter } : {}) },
            }),
            apiJson(`${path}/stats`).catch(() => null),
          ])
          if (cancelled) return
          const pageRows = normalizeDatasetRows(data, { project, version })
          const fileCount = typeof data.file_count === 'number' ? data.file_count : pageRows.length
          const truncated = Boolean(data.truncated)
          const datasetFiles = normalizeDatasetRows(
            { files: Array.isArray(data.dataset_files) ? data.dataset_files : [] },
            { project, version },
          )
          const provenance = describeOutputSource(data.source)
          const entry: OutputDetailCache = {
            rows: pageRows,
            stats: st,
            fileCount,
            truncated,
            nextOffset: pageRows.length,
            datasetFiles,
            provenance,
          }
          outputDetailCacheRef.current.set(cacheKey, entry)
          setPathRecovery(false)
          setRows(pageRows)
          setStats(st)
          setOutputFileCount(fileCount)
          setOutputTruncated(truncated)
          setOutputDatasetFiles(datasetFiles)
          setOutputProvenance(provenance)
        } catch (err) {
          if (cancelled) return
          const h = humanizeDataError(err, 'outputs')
          setError(h.message)
          setErrorDetail(h.detail)
          setRows([])
          setStats(null)
          setOutputFileCount(0)
          setOutputTruncated(false)
          if (h.invalidPath) {
            skippedOutputKey.current = `${project}/${version}`
            setPathRecovery(true)
            skipProjectHashRef.current = true
            setProject('')
            setVersion('')
            // Stay on workspace datasets URL; skipProjectHashRef omits ?project= so path id
            // does not immediately re-seed Outputs. User can Browse shared library separately.
            const parts = window.location.pathname.replace(/\/+$/, '').split('/').filter(Boolean)
            if (parts[0] === 'workspaces' && parts[2] === 'datasets') {
              replacePathSearch({ mode: 'outputs' })
            }
            void loadSources()
          }
        }
        return
      }
      if (mode === 'inputs') {
        if (!label) {
          setRows([])
          setStats(null)
          return
        }
        setError(null)
        setErrorDetail(null)
        try {
          const data = await apiJson<unknown>(`/data/inputs/${encodeURIComponent(label)}`)
          if (cancelled) return
          setRows(normalizeDatasetRows(data))
          setStats(null)
        } catch (err) {
          if (cancelled) return
          const h = humanizeDataError(err, 'inputs')
          setError(h.message)
          setErrorDetail(h.detail)
          setRows([])
          setStats(null)
          if (h.invalidPath) {
            // Clear the lying selection so the dropdown matches the empty/error state.
            skippedInputLabels.current.add(label)
            setLabel('')
          }
        }
        return
      }
      setRows([])
      setStats(null)
    }
    void run()
    return () => {
      cancelled = true
    }
    // outputsLoaded: re-check the selection once the catalogue arrives (outputsRef is read, not subscribed).
  }, [mode, project, version, label, splitFilter, loadSources, detailEpoch, invalidateOutputDetail, outputsLoaded])

  const selectionKeyRef = React.useRef('')
  selectionKeyRef.current = `${project}/${version}#${splitFilter}`
  const loadMoreOutputs = async () => {
    if (!project || !version || loadingMoreOutputs) return
    const cacheKey = `${project}/${version}#${splitFilter}`
    // Only page a selection whose first page is loaded (cache entry = its rows).
    const cached = outputDetailCacheRef.current.get(cacheKey)
    if (!cached) return
    const offset = cached.nextOffset
    if (!cached.truncated && offset >= cached.fileCount) return
    setLoadingMoreOutputs(true)
    try {
      const data = await apiJson<Record<string, unknown>>(outputVersionPath(project, version), {
        query: { limit: OUTPUT_PAGE, offset, ...(splitFilter ? { split: splitFilter } : {}) },
      })
      const pageRows = normalizeDatasetRows(data, { project, version })
      const fileCount = typeof data.file_count === 'number' ? data.file_count : offset + pageRows.length
      const truncated = Boolean(data.truncated)
      const nextRows = [...cached.rows, ...pageRows]
      const entry: OutputDetailCache = {
        ...cached,
        rows: nextRows,
        fileCount,
        truncated,
        nextOffset: offset + pageRows.length,
      }
      outputDetailCacheRef.current.set(cacheKey, entry)
      // Selection changed while the page was in flight: cache it, don't paint it.
      if (selectionKeyRef.current !== cacheKey) return
      setRows(nextRows)
      setOutputFileCount(fileCount)
      setOutputTruncated(truncated)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setLoadingMoreOutputs(false)
    }
  }
  // Preview inline via FileViewer (audio player, image, JSON tree, text — with Download)
  // instead of the previous window.open(blobUrl) into a bare, unbranded new tab, which was
  // the only place in the app that punted a file preview like that (Runs → Run outputs
  // already used FileViewer for the equivalent action).
  const openFile = (path: string, kind: 'files' | 'input-files') => {
    // Output rows are `<project>/<version>/…`; /outputs/file resolves against the
    // workspace root, so it needs the datasets/output prefix to find them.
    const resolved =
      kind === 'files' && !path.startsWith('workspace/') ? `${OUTPUT_FILE_PREFIX}${path.replace(/^\/+/, '')}` : path
    setPreviewFile({ path: resolved, kind })
  }

  /** Open the upload panel (multi-file / folder / archive, any allowlisted type). */
  const upload = () => {
    setShowUpload(true)
    setUxMode('manage')
    setManageTab('upload')
    setMode('inputs')
  }

  const onUploadDone = async (touched: string[]) => {
    await loadSources()
    if (touched.length) setLabel(touched[0])
    setDetailEpoch((n) => n + 1)
  }

  const freezeInput = async () => {
    if (!label) return
    try {
      const snap = await apiJson<{ project: string; version: string; file_count: number }>(
        `/data/inputs/${encodeURIComponent(label)}/snapshot`,
        { method: 'POST', timeoutMs: 30 * 60 * 1000 },
      )
      pushToast(`Frozen “${label}” as ${snap.project}/${snap.version} (${snap.file_count} files) — see Outputs`, 'success')
      await loadSources()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const downloadInputZip = async () => {
    if (!label) return
    try {
      await downloadZip(zipPath({ label }), `${label}.zip`)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const downloadOutputZip = async () => {
    if (!project || !version) return
    try {
      await downloadZip(zipPath({ project, version }), `${project.replace('/', '_')}_${version}.zip`)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  // Input stats (file types, classes, audio summary) — loaded with the label.
  React.useEffect(() => {
    setInputStats(null)
    if (mode !== 'inputs' || !label) return
    let cancelled = false
    apiJson<InputStats>(`/data/inputs/${encodeURIComponent(label)}/stats`, { timeoutMs: 120000 })
      .then((st) => {
        if (!cancelled) setInputStats(st)
      })
      .catch(() => {
        if (!cancelled) setInputStats(null)
      })
    return () => {
      cancelled = true
    }
  }, [mode, label, detailEpoch])

  /** Result of one ingest job's SSE stream — the job "completing" only means
   * it finished running, not that every URL/file succeeded. */
  type IngestStreamResult = { totalFiles: number; errorCount: number; fatalError?: string }

  const trackIngestEvent = (raw: string, acc: IngestStreamResult) => {
    try {
      const data = JSON.parse(raw) as { type?: string; status?: string; total_files?: number; message?: string }
      if (data.type === 'summary' && typeof data.total_files === 'number') {
        acc.totalFiles = data.total_files
      }
      // type=error is job-fatal: the backend closes the stream without a summary.
      if (data.type === 'error') {
        acc.fatalError = typeof data.message === 'string' && data.message ? data.message : 'Ingest job failed'
      }
      if (data.status === 'error' || data.type === 'error') {
        acc.errorCount += 1
      }
    } catch {
      /* not JSON — ignore for counting, still shown in the raw log */
    }
  }

  const streamJob = async (jobId: string, kind: 'url' | 'huggingface'): Promise<IngestStreamResult> => {
    const path = `/ingest/${kind}/${jobId}/stream`
    const acc: IngestStreamResult = { totalFiles: 0, errorCount: 0 }
    // EventSource can't send Authorization — fall back to fetch stream if token set
    if (getApiToken()) {
      const res = await apiFetch(path, { timeoutMs: 600000 })
      if (!res.ok || !res.body) throw new Error(`Stream failed: ${res.status}`)
      const reader = res.body.getReader()
      ingestStreamCancelRef.current = () => {
        void reader.cancel().catch(() => {})
      }
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''
        for (const part of parts) {
          const line = part.split('\n').find((l) => l.startsWith('data:'))
          if (!line) continue
          const data = line.slice(5).trim()
          setIngestLog((l) => [...l, data].slice(-100))
          trackIngestEvent(data, acc)
        }
      }
      ingestStreamCancelRef.current = null
      if (unmountedRef.current) throw new Error('unmounted')
      return acc
    }
    await new Promise<void>((resolve, reject) => {
      const es = new EventSource(apiUrl(path))
      ingestStreamCancelRef.current = () => {
        es.close()
        reject(new Error('unmounted'))
      }
      const finish = (err?: Error) => {
        es.close()
        ingestStreamCancelRef.current = null
        if (err) reject(err)
        else resolve()
      }
      es.onmessage = (ev) => {
        setIngestLog((l) => [...l, ev.data].slice(-100))
        trackIngestEvent(ev.data, acc)
        try {
          const data = JSON.parse(ev.data) as { type?: string }
          // summary = normal end; error = job-fatal, stream closes with no summary.
          if (data.type === 'summary' || data.type === 'error') finish()
        } catch {
          /* ignore */
        }
      }
      es.onerror = () => {
        // A close right after a fatal type=error event is expected, not a transport error.
        if (acc.fatalError) finish()
        else finish(new Error('Ingest stream error'))
      }
    })
    return acc
  }

  /** Turn a stream result into the right toast — never claim success when
   * every URL errored or nothing was actually ingested. */
  const pushIngestResultToast = (label: string, result: IngestStreamResult) => {
    if (result.fatalError) {
      pushToast(`${label} failed: ${result.fatalError}`, 'error')
    } else if (result.errorCount > 0 && result.totalFiles === 0) {
      pushToast(`${label} failed — 0 files ingested, ${result.errorCount} error(s). See log.`, 'error')
    } else if (result.errorCount > 0) {
      pushToast(`${label}: ${result.totalFiles} file(s) ingested, ${result.errorCount} error(s). See log.`, 'error')
    } else {
      pushToast(`${label} complete — ${result.totalFiles} file(s) ingested`, 'success')
    }
  }

  const startUrlIngest = async () => {
    try {
      const list = urls.split('\n').map((u) => u.trim()).filter(Boolean)
      const res = await apiJson<{ job_id: string }>('/ingest/url', {
        method: 'POST',
        body: JSON.stringify({ urls: list, label: ingestLabel }),
      })
      setIngestLog([`job ${res.job_id} started`])
      const result = await streamJob(res.job_id, 'url')
      pushIngestResultToast('URL ingest', result)
      await loadSources()
    } catch (err) {
      if (unmountedRef.current) return
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const startHfIngest = async () => {
    try {
      const res = await apiJson<{ job_id: string }>('/ingest/huggingface', {
        method: 'POST',
        body: JSON.stringify({
          repo_id: hfRepo.trim(),
          split: hfSplit.trim() || 'train',
          audio_col: hfAudioCol.trim() || 'audio',
          // Only when set: the label column (ClassLabel names) decides otherwise.
          label_col: hfLabelCol.trim() || undefined,
          label_override: hfLabelOverride.trim() || undefined,
          max_rows: hfMaxRows,
          revision: hfRevision.trim() || undefined,
        }),
      })
      setIngestLog([`job ${res.job_id} started`])
      const result = await streamJob(res.job_id, 'huggingface')
      pushIngestResultToast('HF ingest', result)
      await loadSources()
    } catch (err) {
      if (unmountedRef.current) return
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const deleteInput = async () => {
    if (!label) return
    try {
      await apiJson(`/data/inputs/${encodeURIComponent(label)}`, { method: 'DELETE' })
      pushToast(`Deleted input ${label}`, 'success')
      setLabel('')
      setRows([])
      await loadSources()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const deleteOutput = async () => {
    if (!project || !version) return
    try {
      await apiJson(
        outputVersionPath(project, version),
        { method: 'DELETE' },
      )
      pushToast(`Deleted ${project}/${version}`, 'success')
      invalidateOutputDetail(`${project}/${version}`)
      setVersion('')
      setRows([])
      setStats(null)
      await loadSources()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const publishArtifact = async () => {
    const fsPath = selectedOutputMeta?.fs_path
    const target = (activeProject || '').trim()
    if (!fsPath || !target || !version) {
      pushToast('Open a workspace, then publish this legacy artifact into it', 'info')
      return
    }
    try {
      const out = await apiJson<{ project: string; version: string; file_count?: number }>(
        '/data/outputs/publish-artifact',
        {
          method: 'POST',
          body: JSON.stringify({
            fs_path: fsPath,
            source_version: version,
            target_project: target,
          }),
        },
      )
      pushToast(
        `Published to ${out.project}/${out.version}` +
          (out.file_count != null ? ` (${out.file_count} files)` : ''),
        'success',
      )
      invalidateOutputDetail(`${out.project}/${out.version}`)
      await loadSources()
      pickOutputSource(out.project, out.version)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const doMerge = async () => {
    try {
      const sources = mergeSources
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
        .map((s) => {
          const [projectName, ver] = s.split(':')
          return { project: projectName, version: ver }
        })
      const res = await apiJson('/data/merge', {
        method: 'POST',
        body: JSON.stringify({
          sources,
          target_project: mergeTargetProject,
          target_version: mergeTargetVersion,
          overwrite: mergeOverwrite,
        }),
      })
      const mergeResult = formatMergeToast(res)
      pushToast(mergeResult.message, mergeResult.tone)
      if (mergeTargetProject.trim() && mergeTargetVersion.trim()) {
        invalidateOutputDetail(`${mergeTargetProject.trim()}/${mergeTargetVersion.trim()}`)
      }
      await loadSources()
      if (mergeTargetProject.trim()) {
        openProjects({ project: mergeTargetProject.trim() })
      }
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const browseTemplatesForDataPrep = () => {
    goView('templates')
    pushToast('Open a data-prep or ingest template in Editor', 'info')
  }

  const blockedInputs = React.useMemo(
    () => inputs.filter((i) => i.accessible === false),
    [inputs],
  )
  const accessibleInputs = React.useMemo(
    () => inputs.filter((i) => i.accessible !== false),
    [inputs],
  )

  const showBrowseError = Boolean(
    error &&
      ((mode === 'inputs' && label.trim()) ||
        (mode === 'outputs' && project.trim() && version.trim()) ||
        (mode !== 'inputs' && mode !== 'outputs')),
  )

  const versions = outputs.find((o) => o.project === project)?.versions ?? []

  /* Compare two output versions of the selected workspace (GET /projects/{p}/diff:
     added / removed / relabelled samples by labels.csv). Moved here from the old
     Home "Spec & metadata → Diff" tab — it belongs next to the versions. */
  const [compareOpen, setCompareOpen] = React.useState(false)
  const [cmpA, setCmpA] = React.useState('')
  const [cmpB, setCmpB] = React.useState('')
  const [cmpResult, setCmpResult] = React.useState<unknown>(null)
  React.useEffect(() => {
    setCompareOpen(false)
    setCmpResult(null)
  }, [project])
  const openCompare = () => {
    const others = versions.filter((v) => v !== version)
    setCmpA(version || versions[0] || '')
    setCmpB(others[0] || versions[1] || '')
    setCmpResult(null)
    setCompareOpen(true)
  }
  const runCompare = async () => {
    if (!project || !cmpA || !cmpB || cmpA === cmpB) return
    try {
      setCmpResult(
        await apiJson(`/projects/${encodeURIComponent(project)}/diff`, {
          query: { version_a: cmpA, version_b: cmpB },
        }),
      )
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  /* Workspace Datasets lists the datasets this workspace actually uses first:
     labels pinned on Home plus the dataset folders its runs read (run rows'
     `summary.dataset` paths). Everything else is one toggle away under
     "All shared datasets". With nothing used yet, all labels are listed. */
  const onWorkspaceDatasets =
    typeof window !== 'undefined' &&
    window.location.pathname.startsWith('/workspaces/') &&
    window.location.pathname.includes('/datasets')
  /** Labels pinned to the active workspace (null = unknown / no workspace). */
  const [linkedInputs, setLinkedInputs] = React.useState<string[] | null>(null)
  const [workspaceRuns, setWorkspaceRuns] = React.useState<unknown[]>([])
  const [showAllInputs, setShowAllInputs] = React.useState(false)
  React.useEffect(() => {
    if (!activeProject) {
      setLinkedInputs(null)
      setWorkspaceRuns([])
      return
    }
    let cancelled = false
    apiJson<{ inputs?: string[] }>(`/projects/${encodeURIComponent(activeProject)}/links`)
      .then((d) => {
        if (!cancelled) setLinkedInputs(Array.isArray(d?.inputs) ? d.inputs.map(String) : [])
      })
      .catch(() => {
        if (!cancelled) setLinkedInputs(null)
      })
    if (onWorkspaceDatasets) {
      apiJson<unknown>('/runs', { query: { project: activeProject, limit: 50, offset: 0 } })
        .then((d) => {
          if (!cancelled) setWorkspaceRuns(unwrapList<unknown>(d))
        })
        .catch(() => {
          if (!cancelled) setWorkspaceRuns([])
        })
    }
    return () => {
      cancelled = true
    }
  }, [onWorkspaceDatasets, activeProject])
  /** Pin / unpin a label for the active workspace (was: go to Home and pin there). */
  const toggleLinkedInput = async (target: string, use: boolean) => {
    if (!activeProject || !target) return
    try {
      const next = await apiJson<{ inputs?: string[] }>(`/projects/${encodeURIComponent(activeProject)}/links`, {
        method: use ? 'POST' : 'DELETE',
        body: JSON.stringify({ inputs: [target] }),
      })
      setLinkedInputs(Array.isArray(next?.inputs) ? next.inputs.map(String) : [])
      pushToast(
        use
          ? `“${target}” pinned for ${activeProject} — open Editor and pick it under Linked on the ingest path field`
          : `Removed “${target}” from ${activeProject}`,
        'success',
      )
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }
  const usedLabels = React.useMemo(
    () =>
      onWorkspaceDatasets && activeProject
        ? usedInputLabels(
            inputs.map((i) => i.label),
            workspaceRuns,
            linkedInputs ?? [],
          )
        : [],
    [onWorkspaceDatasets, activeProject, inputs, workspaceRuns, linkedInputs],
  )
  const scopeToLinked = usedLabels.length > 0 && !showAllInputs
  const visibleInputs = React.useMemo(() => {
    const base = scopeToLinked ? inputs.filter((i) => usedLabels.includes(i.label)) : inputs
    return [...base].sort((a, b) => naturalCompare(a.label, b.label))
  }, [inputs, usedLabels, scopeToLinked])
  React.useEffect(() => {
    // Keep the selected label inside the visible set when scoping to used datasets.
    if (!scopeToLinked || visibleInputs.length === 0) return
    if (!visibleInputs.some((i) => i.label === label)) {
      const accessible = visibleInputs.filter((i) => i.accessible !== false)
      const preferred = mostUsedInputLabel(accessible.map((i) => i.label), workspaceRuns)
      const next = accessible.find((i) => i.label === preferred) ?? accessible[0] ?? visibleInputs[0]
      setLabel(next.label)
    }
  }, [scopeToLinked, visibleInputs, label, workspaceRuns])
  const filteredInputs = React.useMemo(
    () => visibleInputs.filter((i) => matchesQuery(`${i.label} ${i.file_count}`, listFilter)),
    [visibleInputs, listFilter],
  )
  const filteredOutputs = React.useMemo(
    () =>
      outputs.filter(
        (o) =>
          matchesQuery(o.project, listFilter) ||
          o.versions.some((v) => matchesQuery(`${o.project}/${v}`, listFilter)),
      ),
    [outputs, listFilter],
  )
  /** Whole-version split sizes from /stats (the loaded page may be partial). */
  const outputSummary = React.useMemo(() => {
    if (mode !== 'outputs' || !stats || typeof stats !== 'object') return null
    const s = stats as Record<string, unknown>
    if (s.kind === 'artifact_dataset') return null
    const splits = s.splits && typeof s.splits === 'object' ? (s.splits as Record<string, Record<string, number>>) : {}
    const totals = new Map<string, number>()
    const classes = new Set<string>()
    for (const [split, byLabel] of Object.entries(splits)) {
      let n = 0
      for (const [lab, c] of Object.entries(byLabel ?? {})) {
        n += typeof c === 'number' ? c : 0
        classes.add(lab)
      }
      totals.set(split, n)
    }
    const total = typeof s.total === 'number' ? s.total : null
    return { totals, classes: classes.size, total }
  }, [mode, stats])
  /** Whole-version file count — `outputFileCount` narrows to the chosen split, so
   *  under a filter use the unfiltered listing's count (same unit), else /stats. */
  const versionFileCount: number | null = splitFilter
    ? (outputDetailCacheRef.current.get(`${project}/${version}#`)?.fileCount ?? outputSummary?.total ?? null)
    : outputFileCount
  const splitTotals = outputSummary?.totals ?? new Map<string, number>()
  /** Split chips: whole-version splits from /stats, else those seen in loaded rows. */
  const splitOptions = React.useMemo(() => {
    const names = new Set<string>(splitTotals.keys())
    for (const r of rows) if (typeof r.split === 'string' && r.split) names.add(r.split)
    // Unfiltered first page (cached) knows every split even when /stats failed.
    for (const r of outputDetailCacheRef.current.get(`${project}/${version}#`)?.rows ?? []) {
      if (typeof r.split === 'string' && r.split) names.add(r.split)
    }
    if (splitFilter) names.add(splitFilter)
    return [...names].sort((a, b) => splitRank(a) - splitRank(b) || a.localeCompare(b))
  }, [rows, splitTotals, project, version, splitFilter])
  const filteredRows = React.useMemo(
    () =>
      rows.filter((r) =>
        matchesQuery(`${String(r.path ?? '')} ${String(r.split ?? '')} ${String(r.label ?? '')}`, listFilter),
      ),
    [rows, listFilter],
  )
  /* The listing was unsorted (filesystem walk order) with no way to reorder it,
     so finding the biggest file or the most recent one in 186 rows meant reading
     every row. Size and mtime only became sortable once the API started
     returning them — it previously sent nothing but the path and the label the
     caller already knew. */
  const sortedRows = React.useMemo(() => {
    const dir = sortDir === 'asc' ? 1 : -1
    const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : -1)
    const time = (v: unknown) => {
      const t = typeof v === 'string' ? Date.parse(v) : NaN
      return Number.isNaN(t) ? -1 : t
    }
    return [...filteredRows].sort((a, b) => {
      if (sortKey === 'size') {
        return (num(a.size_bytes) - num(b.size_bytes)) * dir
      }
      if (sortKey === 'modified') {
        return (time(a.modified_at) - time(b.modified_at)) * dir
      }
      // train → val → test before names; natural order: nohash_2 before nohash_10.
      const bySplit = splitRank(a.split) - splitRank(b.split)
      if (bySplit) return bySplit * dir
      return naturalCompare(String(a.path ?? ''), String(b.path ?? '')) * dir
    })
  }, [filteredRows, sortKey, sortDir])
  const displayRows = sortedRows.slice(0, listCap)
  const listTruncated = sortedRows.length > listCap
  /* Totals describe the whole filtered set, not just the rendered page — a
     footer that counted only the visible 200 would quietly understate a
     1200-file label. */
  const totalBytes = React.useMemo(
    () =>
      filteredRows.reduce(
        (sum, r) => sum + (typeof r.size_bytes === 'number' ? r.size_bytes : 0),
        0,
      ),
    [filteredRows],
  )
  const anySizes = filteredRows.some((r) => typeof r.size_bytes === 'number')
  const versionPrefix = project && version ? `${project}/${version}/` : ''
  const relativeToVersion = (path: string) =>
    versionPrefix && path.startsWith(versionPrefix) ? path.slice(versionPrefix.length) : path

  const switchUxMode = (next: 'browse' | 'manage') => {
    setError(null)
    setErrorDetail(null)
    setPathRecovery(false)
    setListFilter('')
    setUxMode(next)
    if (next === 'browse') {
      setMode(mode === 'inputs' || mode === 'outputs' ? mode : 'inputs')
    } else if (mode === 'ingest') {
      setManageTab('ingest')
    } else if (mode === 'merge') {
      setManageTab('merge')
    } else {
      setManageTab('upload')
      // Preserve outputs — Manage's Upload tab renders the delete-output-
      // version view when mode is 'outputs' (see the mode === 'outputs'
      // branch below), so forcing 'inputs' here would silently drop out of
      // Outputs browsing the moment a user clicked the Manage tab.
      setMode(mode === 'outputs' ? 'outputs' : 'inputs')
    }
  }

  const setManage = (tab: ManageTab) => {
    setError(null)
    setErrorDetail(null)
    setPathRecovery(false)
    setListFilter('')
    setManageTab(tab)
    setUxMode('manage')
    if (tab === 'upload') setMode('inputs')
    else if (tab === 'ingest') setMode('ingest')
    else setMode('merge')
  }

  /** Single tab row value: Import / Merge forms, else the browsed side. */
  const flatTab: 'inputs' | 'outputs' | 'ingest' | 'merge' =
    uxMode === 'manage' && manageTab !== 'upload' ? manageTab : mode === 'outputs' ? 'outputs' : 'inputs'
  const pickFlatTab = (tab: 'inputs' | 'outputs' | 'ingest' | 'merge') => {
    if (tab === 'ingest' || tab === 'merge') {
      setManage(tab)
      return
    }
    setError(null)
    setErrorDetail(null)
    setPathRecovery(false)
    setListFilter('')
    // Leaving Import / Merge returns to browsing; an open Manage (upload) stays.
    if (uxMode === 'manage' && manageTab !== 'upload') setUxMode('browse')
    setManageTab('upload')
    setMode(tab)
  }

  const showFileBrowser = uxMode === 'browse' || (uxMode === 'manage' && manageTab === 'upload')
  const showEmptyOutputs = mode === 'outputs' && (outputs.length === 0 || pathRecovery)
  const showEmptyInputs = mode === 'inputs' && inputs.length === 0

  const outputSourceRows = React.useMemo(() => {
    const src = listFilter.trim() ? filteredOutputs : outputs
    return src.flatMap((o) =>
      o.versions
        .filter((v) => {
          const title =
            o.kind === 'input_snapshot'
              ? `Frozen · ${o.label || o.project}/${v}`
              : o.kind === 'artifact_dataset'
                ? `Legacy · ${o.label || o.project}/${v}`
                : `${o.project}/${v}`
          return !listFilter.trim() || matchesQuery(title, listFilter) || matchesQuery(`${o.project}/${v}`, listFilter)
        })
        .map((v) => ({
          project: o.project,
          version: v,
          kind: o.kind,
          label: o.label,
          fs_path: o.fs_path,
        })),
    )
  }, [outputs, filteredOutputs, listFilter])

  const selectedOutputMeta = React.useMemo(
    () => outputs.find((o) => o.project === project) ?? null,
    [outputs, project],
  )
  const isArtifactSelection = selectedOutputMeta?.kind === 'artifact_dataset'
  const isFreezeSelection = selectedOutputMeta?.kind === 'input_snapshot' || isSnapshotProject(project)

  const searchField = (
    <label className="relative block w-full">
      <span className="sr-only">Filter lists</span>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
      <input
        value={listFilter}
        onChange={(e) => setListFilter(e.target.value)}
        placeholder={mode === 'inputs' ? 'Filter labels or files…' : 'Filter workspaces or files…'}
        className="field-control mt-0 w-full pl-8 text-sm"
      />
    </label>
  )

  const pickOutputSource = (nextProject: string, nextVersion: string) => {
    setError(null)
    setErrorDetail(null)
    libraryClearRef.current = false
    skipProjectHashRef.current = false
    setProject(nextProject)
    setVersion(nextVersion)
  }

  const pickInputLabel = (next: string) => {
    if (next) skippedInputLabels.current.delete(next)
    setError(null)
    setErrorDetail(null)
    setLabel(next)
  }

  const detailToolbarOutputs =
    !showEmptyOutputs && mode === 'outputs' ? (
      <>
      <div className="flex flex-wrap items-center gap-2">
        {project && !isSnapshotProject(project) ? (
          activeProject ? (
            <>
              <button
                type="button"
                className="btn-primary"
                onClick={() => goView('builder')}
                title="Open Editor with current workspace"
              >
                Open Editor
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn-primary"
              onClick={() => openProjects({ project })}
              title="Open this dataset as a workspace"
            >
              Use in workspace
            </button>
          )
        ) : null}
        {project && version ? (
          <button
            type="button"
            className="btn-secondary text-[12px]"
            title="Download this version (all files + manifest.json with sha256) as a zip"
            onClick={() => void downloadOutputZip()}
          >
            <Download className="h-3.5 w-3.5" /> Download zip
          </button>
        ) : null}
        {uxMode === 'manage' && project && version ? (
          <ConfirmButton
            label="Delete"
            confirmLabel={`Delete ${project}/${version}?`}
            danger
            onConfirm={() => void deleteOutput()}
          />
        ) : null}
        {uxMode === 'browse' && project ? (
          <button
            type="button"
            className="btn-secondary text-[12px]"
            onClick={() => {
              setUxMode('manage')
              setManageTab('upload')
              setMode('outputs')
            }}
          >
            Manage…
          </button>
        ) : uxMode === 'manage' ? (
          <button type="button" className="btn-quiet text-[12px]" onClick={() => switchUxMode('browse')}>
            Done
          </button>
        ) : null}
        {project && versions.length >= 2 ? (
          <button
            type="button"
            className="btn-secondary text-[12px]"
            aria-expanded={compareOpen}
            onClick={() => (compareOpen ? setCompareOpen(false) : openCompare())}
          >
            Compare versions
          </button>
        ) : null}
      </div>
      {compareOpen && project && versions.length >= 2 ? (
        <div className="mt-2 space-y-2 rounded-xl border border-ink-200/80 bg-ink-50/50 p-3">
          <div className="flex flex-wrap items-center gap-2 text-[12px]">
            <select
              aria-label="First version"
              value={cmpA}
              onChange={(e) => {
                setCmpA(e.target.value)
                setCmpResult(null)
              }}
              className="rounded-md border border-ink-200 bg-white px-2 py-1"
            >
              {versions.map((v) => (
                <option key={`a-${v}`} value={v}>
                  {v}
                </option>
              ))}
            </select>
            <span className="text-ink-400">vs</span>
            <select
              aria-label="Second version"
              value={cmpB}
              onChange={(e) => {
                setCmpB(e.target.value)
                setCmpResult(null)
              }}
              className="rounded-md border border-ink-200 bg-white px-2 py-1"
            >
              {versions.map((v) => (
                <option key={`b-${v}`} value={v}>
                  {v}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn-secondary text-[12px]"
              disabled={!cmpA || !cmpB || cmpA === cmpB}
              title={cmpA === cmpB ? 'Pick two different versions' : undefined}
              onClick={() => void runCompare()}
            >
              Compare
            </button>
          </div>
          {cmpResult != null ? (
            <KeyValue data={cmpResult} />
          ) : (
            <p className="text-[11px] text-ink-500">
              Counts samples added, removed and relabelled between the two versions (from each version’s labels.csv).
            </p>
          )}
        </div>
      ) : null}
      </>
    ) : null

  const detailToolbarInputs =
    !showEmptyInputs && mode === 'inputs' ? (
      <div className="flex flex-wrap items-center gap-2">
        {uxMode === 'manage' && label ? (
          <ConfirmButton
            label="Delete"
            confirmLabel={`Delete input ${label}?`}
            danger
            onConfirm={() => void deleteInput()}
          />
        ) : null}
        {activeProject && label ? (
          linkedInputs?.includes(label) ? (
            <button
              type="button"
              className="btn-secondary"
              title={`“${label}” is in ${activeProject}’s datasets in use (Home) — click to remove it`}
              onClick={() => void toggleLinkedInput(label, false)}
            >
              <Check className="h-3.5 w-3.5" /> Used by {activeProject}
            </button>
          ) : (
            <button
              type="button"
              className="btn-primary"
              title={`Add “${label}” to ${activeProject}’s datasets in use (Home bookmark). Set the ingest path in the Editor to use it in a run — pinning alone does not rewrite the graph.`}
              onClick={() => void toggleLinkedInput(label, true)}
            >
              Use in {activeProject}
            </button>
          )
        ) : label && !activeProject ? (
          <button
            type="button"
            className="btn-primary"
            title={`Pick a workspace, then pin “${label}” under its Home → Linked inputs`}
            onClick={() => {
              pushToast(`Pick a workspace, then pin “${label}” under Home → Linked inputs`, 'info')
              openProjects()
            }}
          >
            Pick a workspace…
          </button>
        ) : null}
        {label ? (
          <>
            <button
              type="button"
              className="btn-secondary text-[12px]"
              title="Copy this label into an immutable version (Outputs → _inputs/…) with a sha256 manifest, so runs can cite exactly this data"
              onClick={() => void freezeInput()}
            >
              <Lock className="h-3.5 w-3.5" /> Freeze as version
            </button>
            <button
              type="button"
              className="btn-secondary text-[12px]"
              title="Download every file of this label plus a manifest.json (sha256) as a zip"
              onClick={() => void downloadInputZip()}
            >
              <Download className="h-3.5 w-3.5" /> Download zip
            </button>
          </>
        ) : null}
        {uxMode === 'manage' ? (
          <>
            <button type="button" className="btn-secondary" onClick={upload}>
              <Upload className="h-3.5 w-3.5" /> Upload
            </button>
            <button type="button" className="btn-quiet text-[12px]" onClick={() => switchUxMode('browse')}>
              Done
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn-quiet text-[12px]"
            onClick={() => {
              setUxMode('manage')
              setManageTab('upload')
            }}
          >
            Manage…
          </button>
        )}
      </div>
    ) : null

  
  const workspaceDatasetsPath =
    typeof window !== 'undefined' &&
    window.location.pathname.startsWith('/workspaces/') &&
    window.location.pathname.includes('/datasets')

  const showSourcePicker = showFileBrowser

  return (
    <WorkbenchPage
      title={workspaceDatasetsPath ? 'Workspace datasets' : 'Datasets'}
      description={
        workspaceDatasetsPath
          ? usedLabels.length > 0
            ? `Datasets ${activeProject ?? 'this workspace'} uses, plus shared outputs.`
            : 'Shared datasets — none used by this workspace yet.'
          : 'Shared inputs and outputs for pipelines.'
      }
      toolbar={
        /* One level of tabs: Inputs · Outputs · Import · Merge. Upload / delete
           live behind the detail toolbar's "Manage…" toggle. */
        <SegmentedTabs
          value={flatTab}
          options={[
            { id: 'inputs', label: 'Inputs' },
            { id: 'outputs', label: 'Outputs' },
            { id: 'ingest', label: 'Import' },
            { id: 'merge', label: 'Merge' },
          ]}
          onChange={pickFlatTab}
          aria-label="Datasets"
        />
      }
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <span
            className="inline-flex cursor-help items-center text-ink-400 hover:text-ink-700"
            role="img"
            aria-label="About datasets"
            title={
              'Datasets are shared folders: Inputs are what pipelines read, Outputs are dataset versions pipelines write.\n' +
              'One run’s downloadable files live under Runs → Run outputs; Lineage is the audit trail.\n' +
              'Labeling: use output versions plus the datasets chosen on Home (no full labeling studio).'
            }
          >
            <HelpCircle className="h-4 w-4" />
          </span>
          {workspaceDatasetsPath ? (
            <button
              type="button"
              className="btn-quiet text-[12px]"
              title="Browse shared Inputs/Outputs catalog (not Models/Ship)"
              onClick={() => {
                skipProjectHashRef.current = true
                libraryClearRef.current = true
                setProject('')
                setVersion('')
                replacePathSearch({ mode: mode === 'inputs' ? 'inputs' : 'outputs' }, paths.libraryDatasets())
              }}
            >
              Browse shared library
            </button>
          ) : null}
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              if (project && version) invalidateOutputDetail(`${project}/${version}`)
              setDetailEpoch((n) => n + 1)
              void loadSources()
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        </div>
      }
      bodyClassName="flex h-full min-h-0 flex-col overflow-hidden !px-0 !py-0"
    >
      {showBrowseError ? (
        <div className="shrink-0 px-4 pt-3 sm:px-6">
          <ErrorBanner
            message={error!}
            title={errorDetail ?? undefined}
            onRetry={() => {
              setDetailEpoch((n) => n + 1)
              void loadSources()
            }}
            onDismiss={() => {
              setError(null)
              setErrorDetail(null)
            }}
          />
        </div>
      ) : null}
      {mode === 'inputs' && blockedInputs.length > 0 && !showBrowseError ? (
        <div
          role="note"
          className="shrink-0 border-b border-amber-100 bg-amber-50/70 px-4 py-2 text-[12px] leading-relaxed text-amber-950 sm:px-6"
        >
          <span className="font-medium">
            {blockedInputs.length} external label
            {blockedInputs.length === 1 ? '' : 's'}
          </span>{' '}
          <span title={'Admin: set GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1 on the API to allow folders that link outside the datasets area.'}>(link outside the datasets area)</span> — hidden from Browse.
          {accessibleInputs.length === 0
            ? ' Ask an admin to allow external links on the server, then Refresh.'
            : ' Pick another folder below.'}
        </div>
      ) : null}

      {loading ? (
        <LoadingBlock />
      ) : (
        <MasterDetail
          listLabel="datasets"
          storageKey="graphyn.datasets"
          collapsible
          className="min-h-0 flex-1"
          masterClassName="!pr-8"
          master={
            <div className="space-y-3">
              {uxMode === 'manage' && manageTab === 'upload' ? (
                <p className="rounded-md bg-amber-50 px-2 py-1 text-[11px] text-amber-900">
                  Managing — upload or delete files.{' '}
                  <button type="button" className="font-medium underline" onClick={() => switchUxMode('browse')}>
                    Done
                  </button>
                </p>
              ) : null}

              {showSourcePicker && mode === 'outputs' && !showEmptyOutputs ? (
                <div className="space-y-2">
                  {searchField}
                  <select
                    value={project}
                    onChange={(e) => {
                      const next = e.target.value
                      pickOutputSource(next, outputs.find((o) => o.project === next)?.versions[0] ?? '')
                    }}
                    className="field-control w-full text-sm"
                  >
                    <option value="">Select workspace…</option>
                    {(listFilter.trim() ? filteredOutputs : outputs).map((o) => (
                      <option key={o.project} value={o.project}>
                        {o.project}
                      </option>
                    ))}
                  </select>
                  <select
                    value={version}
                    onChange={(e) => {
                      setError(null)
                      setErrorDetail(null)
                      setVersion(e.target.value)
                    }}
                    className="field-control w-full text-sm"
                  >
                    {versions.length === 0 ? (
                      <option value="">No prepared versions yet</option>
                    ) : (
                      versions.map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))
                    )}
                  </select>
                  {project && versions.length === 0 && !isArtifactSelection ? (
                    <p className="text-[11px] leading-snug text-ink-500">
                      No prepared versions for this workspace yet — run a prepare pipeline (or Merge) so
                      files land under Datasets → Outputs.
                    </p>
                  ) : null}
                  {(() => {
                    const home = (activeProject || '').trim()
                    const isHome = (r: (typeof outputSourceRows)[number]) =>
                      !!home && r.project === home && !r.kind
                    const mine = home ? outputSourceRows.filter(isHome) : outputSourceRows
                    const others = home ? outputSourceRows.filter((r) => !isHome(r)) : []
                    const selectedElsewhere = others.some((r) => r.project === project && r.version === version)
                    const renderRows = (list: typeof outputSourceRows) => (
                      <ul className="divide-y divide-ink-100 overflow-hidden rounded-lg border border-ink-200/70">
                        {list.slice(0, LIST_CAP).map(({ project: p, version: v, kind, label }) => {
                          const name =
                            kind === 'input_snapshot'
                              ? label || p.replace(/^_inputs\//, '')
                              : kind === 'artifact_dataset'
                                ? (label || p).split('/').pop() || p
                                : p
                          const tag = kind === 'input_snapshot' ? 'Frozen' : kind === 'artifact_dataset' ? 'Legacy' : null
                          return (
                            <li key={`${p}/${v}`}>
                              <button
                                type="button"
                                className={clsx(
                                  'ide-row w-full px-3 py-2',
                                  p === project && v === version && 'is-active font-medium',
                                )}
                                title={`${tag ? `${tag} · ` : ''}${label || p}/${v}`}
                                onClick={() => pickOutputSource(p, v)}
                              >
                                <EmptyDatabase className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                                {tag ? (
                                  <span className="shrink-0 rounded bg-ink-100 px-1 text-[10px] font-medium uppercase tracking-wide text-ink-500">
                                    {tag}
                                  </span>
                                ) : null}
                                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink-800">
                                  {name}
                                </span>
                                <span className="shrink-0 font-mono text-[12px] text-ink-600">{v}</span>
                              </button>
                            </li>
                          )
                        })}
                      </ul>
                    )
                    return (
                      <>
                        {mine.length > 0 ? (
                          renderRows(mine)
                        ) : home ? (
                          <p className="text-[11px] text-ink-500">No prepared versions in {home} yet.</p>
                        ) : null}
                        {others.length > 0 ? (
                          <details
                            open={libraryOpen ?? (selectedElsewhere || !!listFilter.trim() || mine.length === 0)}
                            onToggle={(e) => {
                              const next = (e.currentTarget as HTMLDetailsElement).open
                              const auto = libraryOpen ?? (selectedElsewhere || !!listFilter.trim() || mine.length === 0)
                              // Ignore toggle events echoing the controlled `open` prop.
                              if (next !== auto) setLibraryOpen(next)
                            }}
                          >
                            <summary className="cursor-pointer select-none py-1 text-[12px] font-medium text-ink-600 hover:text-ink-900">
                              Also in the library ({others.length})
                            </summary>
                            <div className="mt-1">{renderRows(others)}</div>
                          </details>
                        ) : null}
                      </>
                    )
                  })()}
                </div>
              ) : null}

              {showSourcePicker && mode === 'inputs' && !showEmptyInputs ? (
                <div className="space-y-2">
                  {searchField}
                  <select
                    value={label}
                    onChange={(e) => pickInputLabel(e.target.value)}
                    className="field-control w-full text-sm"
                  >
                    {!label ? <option value="">Select a label…</option> : null}
                    {filteredInputs.map((i) => (
                      <option key={i.label} value={i.label}>
                        {i.label} ({i.file_count}{typeof i.audio_count === 'number' && i.audio_count !== i.file_count ? `, ${i.audio_count} audio` : ''})
                        {i.accessible === false ? ' — external (blocked)' : ''}
                      </option>
                    ))}
                  </select>
                  {usedLabels.length > 0 ? (
                    <button
                      type="button"
                      className="text-[12px] text-ink-500 hover:text-accent-800 hover:underline"
                      aria-pressed={showAllInputs}
                      title={`${usedLabels.length} dataset${usedLabels.length === 1 ? '' : 's'} used by ${activeProject} (chosen on Home or read by its runs)`}
                      onClick={() => setShowAllInputs((v) => !v)}
                    >
                      {showAllInputs
                        ? `Only datasets ${activeProject} uses (${usedLabels.length})`
                        : `All shared datasets (${inputs.length})`}
                    </button>
                  ) : null}
                  <ul className="divide-y divide-ink-100 overflow-hidden rounded-lg border border-ink-200/70">
                    {filteredInputs.slice(0, LIST_CAP).map((i) => (
                      <li key={i.label}>
                        <button
                          type="button"
                          className={clsx(
                            'ide-row w-full px-3 py-2',
                            label === i.label && 'is-active font-medium',
                          )}
                          onClick={() => pickInputLabel(i.label)}
                        >
                          <EmptyTags className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                          <span className="min-w-0 flex-1 truncate text-[12px] text-ink-800">{i.label}</span>
                          <span
                            className="shrink-0 text-[11px] tabular-nums text-ink-400"
                            title={`${i.file_count} files${typeof i.audio_count === 'number' ? ` · ${i.audio_count} audio` : ''}`}
                          >
                            {i.file_count}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          }
          detail={
            <div className="space-y-3">
              <MasterDetailToggle />
              {uxMode === 'manage' && manageTab === 'ingest' ? (
                <div className="space-y-3">
                  <section className="surface-card space-y-2 p-3">
                    <h3 className="text-sm font-semibold">URL ingest</h3>
                    <label className="block space-y-1">
                      <span className="text-[12px] font-medium text-ink-600">URLs to download</span>
                      <textarea
                        value={urls}
                        onChange={(e) => setUrls(e.target.value)}
                        rows={4}
                        className="field-control w-full text-sm"
                        placeholder="one URL per line"
                        aria-label="URLs to download, one per line"
                      />
                    </label>
                    <label className="block space-y-1">
                      <span className="text-[12px] font-medium text-ink-600">Target input label</span>
                      <input
                        value={ingestLabel}
                        onChange={(e) => setIngestLabel(e.target.value)}
                        className="field-control w-full text-sm"
                        aria-label="Target input label"
                      />
                    </label>
                    <button type="button" className="btn-primary" onClick={() => void startUrlIngest()}>
                      Start URL ingest
                    </button>
                  </section>
                  {caps && !caps.ingest.huggingface ? (
                    <section className="surface-card space-y-1 p-3">
                      <h3 className="text-sm font-semibold">HuggingFace ingest</h3>
                      <p className="text-[12px] text-ink-500" title={caps.ingest.huggingface_reason ?? undefined}>
                        Not available on this server — the HuggingFace “datasets” package is not installed on the API
                        host. Ask an admin to install the <code>hf</code> extra, or upload a zip instead.
                      </p>
                    </section>
                  ) : (
                    <section className="surface-card space-y-2 p-3">
                      <h3 className="text-sm font-semibold">HuggingFace ingest</h3>
                      <input
                        value={hfRepo}
                        onChange={(e) => setHfRepo(e.target.value)}
                        placeholder="org/dataset"
                        aria-label="HuggingFace dataset id"
                        className="field-control w-full text-sm"
                      />
                      <div className="grid grid-cols-2 gap-2 text-[12px] sm:grid-cols-3">
                        <label className="flex flex-col gap-1">
                          <span className="text-ink-500">Split</span>
                          <input value={hfSplit} onChange={(e) => setHfSplit(e.target.value)} className="field-control text-sm" />
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className="text-ink-500">Audio column</span>
                          <input value={hfAudioCol} onChange={(e) => setHfAudioCol(e.target.value)} className="field-control text-sm" />
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className="text-ink-500">Label column</span>
                          <input
                            value={hfLabelCol}
                            onChange={(e) => setHfLabelCol(e.target.value)}
                            placeholder="(none)"
                            className="field-control text-sm"
                          />
                        </label>
                        <label className="flex flex-col gap-1" title="Optional: put every row into this one label instead of using the label column">
                          <span className="text-ink-500">Single label (optional)</span>
                          <input
                            value={hfLabelOverride}
                            onChange={(e) => setHfLabelOverride(e.target.value)}
                            placeholder="use label column"
                            className="field-control text-sm"
                          />
                        </label>
                        <label className="flex flex-col gap-1">
                          <span className="text-ink-500">Max rows</span>
                          <input
                            type="number"
                            min={1}
                            max={1000000}
                            value={hfMaxRows}
                            onChange={(e) => setHfMaxRows(Math.max(1, Number(e.target.value) || 1))}
                            className="field-control text-sm"
                          />
                        </label>
                        <label className="flex flex-col gap-1" title="Branch, tag or commit; the resolved commit is recorded in the audit log">
                          <span className="text-ink-500">Revision (optional)</span>
                          <input
                            value={hfRevision}
                            onChange={(e) => setHfRevision(e.target.value)}
                            placeholder="main"
                            className="field-control text-sm"
                          />
                        </label>
                      </div>
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={!hfRepo.trim()}
                        onClick={() => void startHfIngest()}
                      >
                        Start HF ingest
                      </button>
                    </section>
                  )}
                  <pre className="max-h-48 overflow-auto rounded-xl bg-ink-950 p-3 font-mono text-[11px] text-ink-100">
                    {ingestLog.map((line) => formatExecutionLine(line).text).join('\n') ||
                      'No import progress yet — start an import above and its progress appears here.'}
                  </pre>
                </div>
              ) : uxMode === 'manage' && manageTab === 'merge' ? (
                <section className="surface-card space-y-2 p-3">
                  <h3 className="text-sm font-semibold">Merge datasets</h3>
                  <p className="text-sm text-ink-500">
                    Comma-separated workspace:version pairs combined into a new version of the target workspace.
                  </p>
                  <label className="block space-y-1">
                    <span className="text-[12px] font-medium text-ink-600">Source versions</span>
                    <input
                      value={mergeSources}
                      onChange={(e) => setMergeSources(e.target.value)}
                      className="field-control w-full text-sm"
                      placeholder="workspace:version, other:v2"
                      aria-label="Source versions (comma-separated workspace:version pairs)"
                    />
                  </label>
                  <label className="block space-y-1">
                    <span className="text-[12px] font-medium text-ink-600">Target workspace</span>
                    <input
                      value={mergeTargetProject}
                      onChange={(e) => setMergeTargetProject(e.target.value)}
                      className="field-control w-full text-sm"
                      placeholder="target workspace"
                      aria-label="Target workspace"
                    />
                  </label>
                  <label className="block space-y-1">
                    <span className="text-[12px] font-medium text-ink-600">Target version</span>
                    <input
                      value={mergeTargetVersion}
                      onChange={(e) => setMergeTargetVersion(e.target.value)}
                      className="field-control w-full text-sm"
                      placeholder="target version"
                      aria-label="Target version (for example v1)"
                    />
                  </label>
                  <label
                    className="flex items-center gap-1.5 text-[12px] text-ink-600"
                    title="Versions are immutable: merging into an existing version is refused unless this is on, and never allowed when runs or packages reference it"
                  >
                    <input type="checkbox" checked={mergeOverwrite} onChange={(e) => setMergeOverwrite(e.target.checked)} />
                    Replace the target version if it already exists
                  </label>
                  <button type="button" className="btn-primary" onClick={() => void doMerge()}>
                    Merge
                  </button>
                </section>
              ) : showFileBrowser ? (
                <>
                  {detailToolbarOutputs}
                  {detailToolbarInputs}
                  {showUpload ? (
                    <UploadPanel
                      labels={inputs.filter((i) => i.accessible !== false).map((i) => i.label)}
                      initialLabel={label || undefined}
                      limits={caps?.upload ?? DEFAULT_UPLOAD_LIMITS}
                      onDone={(touched) => void onUploadDone(touched)}
                      onClose={() => setShowUpload(false)}
                    />
                  ) : null}
                  {mode === 'outputs' && showEmptyOutputs ? (
              <EmptyState
                compact
                icon={EmptyDatabase}
                title={pathRecovery ? 'Dataset path reset' : 'No output datasets yet'}
                description={
                  pathRecovery
                    ? 'The selected path was invalid or outside the workspace, so selection was cleared.'
                    : uxMode === 'manage'
                      ? 'Upload files or ingest URLs, then run a template to populate Outputs.'
                      : 'Outputs appear after a template or export writes version folders. Link a workspace, or browse templates to produce data.'
                }
                action={
                  pathRecovery && outputs.length > 0 ? (
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => {
                        setPathRecovery(false)
                        setError(null)
                        setErrorDetail(null)
                        skippedOutputKey.current = null
                        const first = outputs.find((o) => o.versions.length > 0)
                        setProject(first?.project ?? '')
                        setVersion(first?.versions[0] ?? '')
                      }}
                    >
                      Browse existing outputs
                    </button>
                  ) : uxMode === 'manage' ? (
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => {
                        setPathRecovery(false)
                        setManage('upload')
                        setMode('inputs')
                        upload()
                      }}
                    >
                      Upload files or ingest URLs…
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => {
                        setPathRecovery(false)
                        openProjects()
                      }}
                    >
                      Open Workspaces
                    </button>
                  )
                }
              />
                  ) : null}
                  {mode === 'inputs' && showEmptyInputs ? (
                    <EmptyState
                      compact
                      icon={EmptyTags}
                      title="No input labels"
                      description="Upload files or ingest URLs to create a label folder under workspace/datasets/input."
                      action={
                        <button
                          type="button"
                          className="btn-primary"
                          onClick={() => {
                            setUxMode('manage')
                            setManageTab('upload')
                            upload()
                          }}
                        >
                          Upload files
                        </button>
                      }
                    />
                  ) : null}

                  {showEmptyOutputs || showEmptyInputs ? null : (
                    <>
                      {uxMode === 'manage' && manageTab === 'upload' ? (
                        <details className="surface-card">
                          <summary className="cursor-pointer select-none px-3 py-2 text-[12px] font-medium text-ink-600">
                            Delete an output version
                          </summary>
                          <div className="flex flex-wrap items-center gap-2 border-t border-ink-100 px-3 py-2">
                            <select
                              value={project}
                              onChange={(e) => {
                                const next = e.target.value
                                setProject(next)
                                setVersion(outputs.find((o) => o.project === next)?.versions[0] ?? '')
                              }}
                              className="field-control text-sm"
                            >
                              <option value="">Select workspace…</option>
                              {outputs.map((o) => (
                                <option key={o.project} value={o.project}>
                                  {o.project}
                                </option>
                              ))}
                            </select>
                            <select
                              value={version}
                              onChange={(e) => setVersion(e.target.value)}
                              className="field-control text-sm"
                            >
                              {versions.map((v) => (
                                <option key={v} value={v}>
                                  {v}
                                </option>
                              ))}
                            </select>
                            {project && version ? (
                              <ConfirmButton
                                label="Delete"
                                confirmLabel={`Delete ${project}/${version}?`}
                                danger
                                onConfirm={() => void deleteOutput()}
                              />
                            ) : null}
                          </div>
                        </details>
                      ) : null}

                      {mode === 'outputs' && outputSummary && !isArtifactSelection ? (
                        <section
                          className="surface-card flex flex-wrap items-baseline gap-x-4 gap-y-1 p-3 text-[12px]"
                          aria-label="Version summary"
                        >
                          <span>
                            <span className="font-medium text-ink-800">{(versionFileCount ?? outputFileCount).toLocaleString()}</span>
                            {` file${(versionFileCount ?? outputFileCount) === 1 ? '' : 's'}`}
                            {outputSummary.classes > 0 ? (
                              <>
                                {' · '}
                                <span className="font-medium text-ink-800">{outputSummary.classes}</span>
                                {` class${outputSummary.classes === 1 ? '' : 'es'}`}
                              </>
                            ) : null}
                          </span>
                          {splitTotals.size > 0 ? (
                            <span className="text-ink-500">
                              {splitOptions
                                .filter((s) => splitTotals.has(s))
                                .map((s) => `${s} ${(splitTotals.get(s) ?? 0).toLocaleString()}`)
                                .join(' · ')}
                            </span>
                          ) : null}
                          {outputProvenance ? <span className="text-ink-500">{outputProvenance}</span> : null}
                        </section>
                      ) : null}
                      {isArtifactSelection && mode === 'outputs' ? (
                        <div className="surface-card flex flex-wrap items-center gap-2 px-3 py-2 text-[12px] text-ink-700">
                          <span className="min-w-0 flex-1">
                            Legacy artifact tree (template hand-off). Publish into{' '}
                            <span className="font-mono">{activeProject || 'a workspace'}</span> so it
                            appears as a normal Outputs version.
                          </span>
                          <button
                            type="button"
                            className="btn-primary"
                            disabled={!activeProject}
                            title={
                              activeProject
                                ? `Copy into datasets/output/${activeProject}/`
                                : 'Open a workspace first'
                            }
                            onClick={() => void publishArtifact()}
                          >
                            Publish to workspace
                          </button>
                        </div>
                      ) : null}
                      {isFreezeSelection && mode === 'outputs' && !isArtifactSelection ? (
                        <p className="text-[11px] text-ink-500">
                          Frozen input snapshot — immutable copy of an Inputs label (not a workspace
                          export).
                        </p>
                      ) : null}
                      {mode === 'inputs' && inputStats && label ? (
                        <InputStatsCard stats={inputStats} open={inputStatsOpen} onToggle={() => setInputStatsOpen((v) => !v)} />
                      ) : null}
                      {showBrowseError && filteredRows.length === 0 ? (
            <EmptyState
              compact
              icon={EmptyTriangleAlert}
              title="Couldn’t load files"
              description="This selection isn’t browseable. Clear it and pick an accessible label or version."
              action={
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => {
                    if (mode === 'inputs') setLabel('')
                    else {
                      setProject('')
                      setVersion('')
                    }
                    setError(null)
                    setErrorDetail(null)
                  }}
                >
                  Clear selection
                </button>
              }
            />
          ) : filteredRows.length === 0 ? (
            <EmptyState
              compact
              icon={EmptyFolderOpen}
              title={
                listFilter.trim() || splitFilter
                  ? 'No matches'
                  : mode === 'inputs' && !label
                    ? accessibleInputs.length
                      ? 'Pick an input label'
                      : blockedInputs.length
                        ? 'No browseable labels'
                        : 'Pick an input label'
                    : mode === 'outputs' && !version
                      ? 'No version selected'
                      : 'No rows'
              }
              description={
                listFilter.trim() || splitFilter
                  ? outputTruncated
                    ? 'Nothing matches in the files loaded so far. Clear the filter, or load more files.'
                    : 'Nothing matches this filter. Clear it to see the full list.'
                  : mode === 'outputs'
                    ? !version
                      ? 'This workspace has no prepared versions yet — run a prepare pipeline (or Merge), or pick a version from “Also in the library”.'
                      : 'This version has no files yet. Run a pipeline or merge datasets to populate it.'
                    : !label
                      ? accessibleInputs.length
                        ? 'Choose a label from the list to browse shared input files.'
                        : blockedInputs.length
                          ? 'Every folder links outside the datasets area and is blocked. Ask an admin to allow external links on the server, then Refresh.'
                          : 'Choose a label from the list to browse shared input files.'
                      : 'This label has no files yet. Upload or ingest to add some.'
              }
              action={
                listFilter.trim() || splitFilter ? (
                  <div className="flex flex-wrap justify-center gap-2">
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => {
                        setListFilter('')
                        setSplitFilter('')
                      }}
                    >
                      Clear filter
                    </button>
                    {mode === 'outputs' && outputTruncated ? (
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={loadingMoreOutputs}
                        onClick={() => void loadMoreOutputs()}
                      >
                        {loadingMoreOutputs ? 'Loading…' : `Load more (${OUTPUT_PAGE})`}
                      </button>
                    ) : null}
                  </div>
                ) : mode === 'inputs' && label ? (
                  <button type="button" className="btn-primary" onClick={upload}>
                    Upload files
                  </button>
                ) : mode === 'outputs' ? (
                  <button type="button" className="btn-primary" onClick={browseTemplatesForDataPrep}>
                    Browse Templates
                  </button>
                ) : undefined
              }
            />
          ) : (
            <div className="space-y-2">
              {mode === 'outputs' && (splitOptions.length > 1 || splitFilter || outputDatasetFiles.length > 0) ? (
                <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                  {/* Keep chips while filtered: the "All" chip is the only way back. */}
                  {splitOptions.length > 1 || splitFilter ? (
                    <>
                      {[['', 'All'] as const, ...splitOptions.map((s) => [s, s] as const)].map(([value, text]) => {
                        const n = value ? splitTotals.get(value) : versionFileCount
                        return (
                          <button
                            key={value || 'all'}
                            type="button"
                            aria-pressed={splitFilter === value}
                            className={clsx(
                              'rounded-full px-2.5 py-0.5 ring-1',
                              splitFilter === value
                                ? 'bg-accent-50 font-medium text-accent-900 ring-accent-200'
                                : 'text-ink-600 ring-ink-200 hover:bg-ink-50',
                            )}
                            onClick={() => setSplitFilter(value)}
                          >
                            {text}
                            {n != null ? <span className="ml-1 tabular-nums text-ink-400">{n.toLocaleString()}</span> : null}
                          </button>
                        )
                      })}
                    </>
                  ) : null}
                  {outputDatasetFiles.length > 0 ? (
                    <details className="ml-auto text-ink-500">
                      <summary className="cursor-pointer select-none hover:text-ink-800">
                        Dataset files ({outputDatasetFiles.length})
                      </summary>
                      <ul className="mt-1 flex flex-wrap gap-1.5">
                        {outputDatasetFiles.map((f) => {
                          const p = String(f.path ?? '')
                          return (
                            <li key={p}>
                              <button
                                type="button"
                                className="rounded bg-ink-50 px-1.5 py-0.5 font-mono text-[11px] text-ink-700 ring-1 ring-ink-100 hover:text-accent-800"
                                title={`${p} — click to preview`}
                                onClick={() => openFile(p, 'files')}
                              >
                                {relativeToVersion(p)}
                              </button>
                            </li>
                          )
                        })}
                      </ul>
                    </details>
                  ) : null}
                </div>
              ) : null}
              {/* Summary of the whole filtered set. The page previously said nothing
                  about how much data a label holds — you got a wall of filenames. */}
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-[12px] text-ink-500">
                <span>
                  <span className="font-medium text-ink-800">{filteredRows.length.toLocaleString()}</span>
                  {` file${filteredRows.length === 1 ? '' : 's'}`}
                  {mode === 'outputs' && outputFileCount > filteredRows.length && !listFilter.trim()
                    ? ` of ${outputFileCount.toLocaleString()}`
                    : ''}
                  {splitFilter ? ` in ${splitFilter}` : ''}
                  {listFilter.trim() ? ` matching “${listFilter.trim()}”` : ''}
                  {anySizes ? (
                    <>
                      {' · '}
                      <span className="font-medium text-ink-800">{formatBytes(totalBytes)}</span>
                      {' total'}
                    </>
                  ) : null}
                </span>
                <span className="flex flex-wrap items-center gap-2">
                  {mode === 'outputs' && outputTruncated && !listFilter.trim() ? (
                    <button
                      type="button"
                      className="font-medium text-accent-800 hover:underline disabled:opacity-50"
                      disabled={loadingMoreOutputs}
                      onClick={() => void loadMoreOutputs()}
                    >
                      {loadingMoreOutputs ? 'Loading…' : `Load more (${OUTPUT_PAGE})`}
                    </button>
                  ) : null}
                  {listTruncated ? (
                    <span>
                      Showing {displayRows.length} of {sortedRows.length} —{' '}
                      <button
                        type="button"
                        className="font-medium text-accent-800 hover:underline"
                        onClick={() => setListCap(sortedRows.length)}
                      >
                        show all
                      </button>
                    </span>
                  ) : null}
                </span>
              </div>
              {/* No `overflow-hidden` here, however tempting for clipping the table
                  to the rounded corners: an ancestor with overflow hidden/clip
                  becomes the sticky header's scroll container, so the header would
                  stick inside a box that never scrolls — i.e. not stick at all
                  (measured: it scrolled 279px past the top). The header rounds its
                  own outer corners instead. */}
              <div className="rounded-lg border border-ink-200 bg-white">
                <table className="w-full text-left text-sm">
                  {/* Sticky header: 200 rows is several screens, and the column
                      labels used to scroll away with them. `top-0` is safe here
                      because this page's scroll container no longer carries top
                      padding (see the container comment above). */}
                  <thead className="sticky top-0 z-10 bg-ink-50/95 text-[12px] text-ink-500 shadow-[inset_0_-1px_0_rgb(0_0_0/0.06)]">
                    <tr>
                      {(
                        [
                          ['path', 'Name', 'text-left'],
                          ['size', 'Size', 'text-right'],
                          ['modified', 'Modified', 'text-right'],
                        ] as const
                      ).map(([key, labelText, align], idx) => (
                        <th
                          key={key}
                          className={clsx(
                            'px-3 py-2 font-medium',
                            align,
                            idx === 0 && 'rounded-tl-2xl',
                            key === 'modified' && 'hidden sm:table-cell',
                          )}
                        >
                          <button
                            type="button"
                            className={clsx(
                              'inline-flex items-center gap-1 hover:text-ink-900',
                              sortKey === key && 'text-ink-900',
                            )}
                            aria-sort={
                              sortKey === key
                                ? sortDir === 'asc'
                                  ? 'ascending'
                                  : 'descending'
                                : 'none'
                            }
                            onClick={() => toggleSort(key)}
                          >
                            {labelText}
                            {sortKey === key ? (
                              sortDir === 'asc' ? (
                                <ArrowUp className="h-3 w-3" />
                              ) : (
                                <ArrowDown className="h-3 w-3" />
                              )
                            ) : null}
                          </button>
                        </th>
                      ))}
                      <th className="rounded-tr-2xl px-3 py-2 text-right font-medium">
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayRows.map((r, i) => {
                      const path = String(r.path ?? '')
                      /* Every row repeated the label as a folder prefix AND in a
                         Meta column, while the label picker above already says
                         which label you're in — three copies of one constant.
                         Show the part that differs; the full path stays on the
                         copy button and the tooltip. */
                      const rowLabel = String(r.label ?? '')
                      const display =
                        mode === 'outputs'
                          ? relativeToVersion(path)
                          : rowLabel && path.startsWith(`${rowLabel}/`)
                            ? path.slice(rowLabel.length + 1)
                            : path
                      const size = typeof r.size_bytes === 'number' ? r.size_bytes : null
                      const modified = typeof r.modified_at === 'string' ? r.modified_at : null
                      const kind = mode === 'outputs' ? 'files' : 'input-files'
                      return (
                        <tr key={i} className="group border-b border-ink-50 last:border-b-0 hover:bg-ink-50/60">
                          {/* w-full + max-w-0: the name cell takes the free width and
                              truncates instead of widening the table on narrow screens. */}
                          <td className="w-full max-w-0 px-3 py-1.5">
                            <div className="flex min-w-0 items-center gap-2">
                              {React.createElement(rowKindIcon(r.kind ?? 'audio'), {
                                className: 'h-3.5 w-3.5 shrink-0 text-ink-300',
                                'aria-hidden': true,
                              })}
                              <button
                                type="button"
                                className="min-w-0 flex-1 truncate text-left font-mono text-[11px] text-ink-800 hover:text-accent-800"
                                title={`${path} — click to preview`}
                                onClick={() => openFile(path, kind)}
                              >
                                {display || '—'}
                              </button>
                            </div>
                          </td>
                          <td className="whitespace-nowrap px-3 py-1.5 text-right text-[11px] tabular-nums text-ink-500">
                            {formatBytes(size)}
                          </td>
                          <td
                            className="hidden whitespace-nowrap px-3 py-1.5 text-right text-[11px] text-ink-500 sm:table-cell"
                            title={modified ? formatLocaleDateTime(modified) : undefined}
                          >
                            {modified ? formatRelativeTime(modified) : '—'}
                          </td>
                          <td className="px-3 py-1.5">
                            <div className="flex items-center justify-end gap-1">
                              {/* Actions stay visible on hover/focus only so 200 rows
                                  aren't 400 competing buttons, but never hide from
                                  keyboard users. */}
                              <span className="opacity-0 transition group-focus-within:opacity-100 group-hover:opacity-100">
                                {path ? <CopyableMono value={path} copyOnly /> : null}
                              </span>
                              <button
                                type="button"
                                className="btn-icon"
                                aria-label={`Preview ${display || path}`}
                                onClick={() => openFile(path, kind)}
                              >
                                <Play className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
                      )}
                    </>
                  )}
                </>
              ) : null}
            </div>
          }
        />
      )}
      {previewFile ? (
        <div
          className="fixed inset-0 z-[110] flex items-center justify-center bg-ink-950/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="File preview"
          onClick={() => setPreviewFile(null)}
        >
          <div
            className="max-h-[85vh] w-full max-w-2xl overflow-hidden rounded-2xl shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="relative">
              <button
                type="button"
                className="btn-icon absolute right-2 top-2 z-10 bg-white/90"
                aria-label="Close preview"
                onClick={() => setPreviewFile(null)}
              >
                <X className="h-4 w-4" />
              </button>
              <FileViewer
                path={previewFile.path}
                source={previewFile.kind === 'input-files' ? 'inputs' : 'outputs'}
                className="max-h-[85vh]"
              />
            </div>
          </div>
        </div>
      ) : null}
    </WorkbenchPage>
  )
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds)) return '—'
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 2 : 1)} s`
  const m = Math.floor(seconds / 60)
  if (m < 60) return `${m} min ${Math.round(seconds % 60)} s`
  return `${Math.floor(m / 60)} h ${m % 60} min`
}

/** Input label summary before training: file types, per-class counts, audio duration / sample rates. */
function InputStatsCard({ stats, open, onToggle }: { stats: InputStats; open: boolean; onToggle: () => void }) {
  const kinds = Object.entries(stats.by_kind).sort((a, b) => b[1] - a[1])
  const a = stats.audio
  const rates = Object.entries(a.sample_rates ?? {}).sort((x, y) => y[1] - x[1])
  const classes = stats.classes.filter((c) => c.name !== '(root)' || stats.classes.length === 1)
  const maxCount = Math.max(1, ...classes.map((c) => c.file_count))
  return (
    <section className="surface-card p-3 text-[12px]" aria-label="Dataset statistics">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span>
          <span className="font-medium text-ink-800">{stats.file_count}</span> files ·{' '}
          <span className="font-medium text-ink-800">{formatBytes(stats.total_bytes)}</span>
        </span>
        <span className="text-ink-500">{kinds.map(([k, n]) => `${n} ${k}`).join(' · ')}</span>
        {a.duration_s ? (
          <span className="text-ink-500" title={a.sampled ? `Estimated from ${a.probed} of ${a.count} audio files` : undefined}>
            ≈ {formatDuration(a.estimated_total_duration_s ?? 0)} audio · clips{' '}
            {a.duration_s.min === a.duration_s.max
              ? `${formatClipSeconds(a.duration_s.min)} s each`
              : `${formatClipSeconds(a.duration_s.min)}–${formatClipSeconds(a.duration_s.max)} s`}
          </span>
        ) : null}
        {rates.length ? (
          <span className={clsx(rates.length > 1 ? 'text-amber-800' : 'text-ink-500')} title={rates.length > 1 ? 'Mixed sample rates — resample before training' : undefined}>
            {rates.map(([sr, n]) => `${Number(sr) / 1000} kHz${rates.length > 1 ? ` ×${n}` : ''}`).join(', ')}
          </span>
        ) : null}
        {classes.length > 1 ? (
          <button type="button" className="text-accent-800 hover:underline" aria-expanded={open} onClick={onToggle}>
            {open ? 'Hide' : 'Show'} {classes.length} classes
          </button>
        ) : null}
      </div>
      {open && classes.length > 1 ? (
        <ul className="mt-2 space-y-1">
          {classes.slice(0, 50).map((c) => (
            <li key={c.name} className="flex items-center gap-2">
              <span className="w-32 shrink-0 truncate font-mono text-[11px]" title={c.name}>
                {c.name}
              </span>
              <span className="h-1.5 flex-1 overflow-hidden rounded bg-ink-100">
                <span className="block h-full bg-accent-600/70" style={{ width: `${(100 * c.file_count) / maxCount}%` }} />
              </span>
              <span className="w-24 shrink-0 text-right tabular-nums text-ink-500">
                {c.file_count}
                {c.audio_count !== c.file_count ? ` (${c.audio_count} audio)` : ''}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
