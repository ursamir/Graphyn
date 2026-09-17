import React from 'react'
import { RefreshCw, Search, Upload } from 'lucide-react'
import {
  apiFetch,
  apiJson,
  apiUrl,
  fetchAuthenticatedBlobUrl,
  fetchInputBlobUrl,
  getApiToken,
} from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { ConfirmButton, CopyableMono, EmptyState, ErrorBanner, KeyValue, LoadingBlock, PageHeader } from '../../components/ui'
import clsx from 'clsx'
import { formatExecutionLine, formatMergeToast } from '../../lib/format'
import { goView, onPathChange, readSearchParams, replacePathSearch } from '../../routes/nav'
import { paths } from '../../routes/paths'

interface OutputProject {
  project: string
  versions: string[]
}
interface InputLabel {
  label: string
  file_count: number
  /** false when label resolves outside datasets/input (external symlink). */
  accessible?: boolean
}

type DataMode = 'outputs' | 'inputs' | 'ingest' | 'merge'
type ManageTab = 'upload' | 'ingest' | 'merge'

const LIST_CAP = 200

function sanitizePathSeg(value: string | undefined | null): string | undefined {
  const v = (value || '').trim()
  if (!v) return undefined
  // Reject path-like hash/state — never send nested segments to /data/outputs/{project}/{version}.
  if (v.includes('/') || v.includes('\\')) return undefined
  return v
}

function parseDataLocation(): {
  mode?: DataMode
  project?: string
  version?: string
  label?: string
  manage?: boolean
} {
  const params = readSearchParams()
  const parts = window.location.pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  let projectFromPath: string | undefined
  if (parts[0] === 'workspaces' && parts[1] && parts[2] === 'datasets') {
    projectFromPath = decodeURIComponent(parts[1])
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
  return {
    mode,
    // Workspace path id seeds Outputs only; Inputs use ?label= / list pick.
    project:
      mode === 'inputs'
        ? sanitizePathSeg(params.get('project'))
        : sanitizePathSeg(params.get('project')) ?? sanitizePathSeg(projectFromPath),
    version: sanitizePathSeg(params.get('version')),
    label: sanitizePathSeg(params.get('label')),
    manage,
  }
}

function isInvalidWorkspacePathError(detail: string): boolean {
  return /path is outside workspace|invalid path segment/i.test(detail)
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
          'This input label points outside the Graphyn datasets tree (often an external symlink). Pick another label, or set GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1 on the API.',
        detail,
        invalidPath: true,
      }
    }
    if (kind === 'outputs') {
      return {
        message:
          'That output path is invalid or no longer inside the Graphyn workspace. Selection was cleared — pick a project/version again.',
        detail,
        invalidPath: true,
      }
    }
    return {
      message: 'A dataset path was rejected by the API. Try refreshing the list.',
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
  const [detailEpoch, setDetailEpoch] = React.useState(0)
  const skippedOutputKey = React.useRef<string | null>(null)
  /** Input labels that failed with invalid-path — do not auto-reselect after clear. */
  const skippedInputLabels = React.useRef<Set<string>>(new Set())
  /** After closeProject: keep outputs dropdown empty; do not revive prior project via loadSources/path-sync. */
  const libraryClearRef = React.useRef(false)
  /** Omit project from search while clearing — prevents stale React state from re-writing ?project=. */
  const skipProjectHashRef = React.useRef(false)
  const appliedUnscopeEpochRef = React.useRef<number | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [storageHintDismissed, setStorageHintDismissed] = React.useState(() => {
    try {
      return localStorage.getItem('graphyn.datasets.storageHint') === '1'
    } catch {
      return false
    }
  })

  // Layout before path-sync effect: reset selection when workspace project is closed.
  React.useLayoutEffect(() => {
    const first = appliedUnscopeEpochRef.current === null
    const prevEpoch = appliedUnscopeEpochRef.current
    appliedUnscopeEpochRef.current = dataUnscopeEpoch
    if (first) {
      // Mounted after a close into global Data (no ?project=): prevent loadSources from auto-picking
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
  const [ingestLog, setIngestLog] = React.useState<string[]>([])

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
        apiJson<OutputProject[]>('/data/outputs'),
        apiJson<InputLabel[]>('/data/inputs'),
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
        const proj =
          safe && out.some((o) => o.project === safe) ? safe : (usable[0]?.project ?? '')
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

  // Mirror Projects: write selection into pathname search (no popstate — avoid echo loops via replacePathSearch).
  React.useEffect(() => {
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
      // Do not clear a banner from list-load while a detail retry is in flight for the same selection.
      if (mode === 'outputs') {
        if (!project || !version) {
          setRows([])
          setStats(null)
          return
        }
        setError(null)
        setErrorDetail(null)
        try {
          const [data, st] = await Promise.all([
            apiJson<Array<Record<string, unknown>>>(
              `/data/outputs/${encodeURIComponent(project)}/${encodeURIComponent(version)}`,
            ),
            apiJson(
              `/data/outputs/${encodeURIComponent(project)}/${encodeURIComponent(version)}/stats`,
            ).catch(() => null),
          ])
          if (cancelled) return
          setPathRecovery(false)
          setRows(data)
          setStats(st)
        } catch (err) {
          if (cancelled) return
          const h = humanizeDataError(err, 'outputs')
          setError(h.message)
          setErrorDetail(h.detail)
          setRows([])
          setStats(null)
          if (h.invalidPath) {
            skippedOutputKey.current = `${project}/${version}`
            setPathRecovery(true)
            skipProjectHashRef.current = true
            setProject('')
            setVersion('')
            // Leave workspace datasets URL without re-seeding Outputs from path id.
            const parts = window.location.pathname.replace(/\/+$/, '').split('/').filter(Boolean)
            if (parts[0] === 'workspaces' && parts[2] === 'datasets') {
              replacePathSearch({ mode: 'outputs' }, paths.libraryDatasets())
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
          const data = await apiJson<Array<Record<string, unknown>>>(
            `/data/inputs/${encodeURIComponent(label)}`,
          )
          if (cancelled) return
          setRows(data)
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
  }, [mode, project, version, label, loadSources, detailEpoch])

  const openFile = async (path: string, kind: 'files' | 'input-files') => {
    try {
      // Input trees often nest via directory symlinks (environmental-sounds/*, speech-commands/*).
      // Use the jailed /data/inputs/file API instead of StaticFiles (/input-files), which 404s
      // when follow_symlink is false.
      const objUrl =
        kind === 'input-files'
          ? await fetchInputBlobUrl(path)
          : await fetchAuthenticatedBlobUrl(
              `/${kind}/${path.split('/').map(encodeURIComponent).join('/')}`,
            )
      window.open(objUrl, '_blank', 'noopener,noreferrer')
      setTimeout(() => URL.revokeObjectURL(objUrl), 60_000)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const upload = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.wav,.mp3,.m4a,.ogg,.webm,.flac'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const fd = new FormData()
      fd.append('file', file)
      try {
        const res = await apiFetch('/data/inputs/upload', { method: 'POST', body: fd })
        if (!res.ok) throw new Error(`Upload failed: HTTP ${res.status}`)
        const body = await res.json()
        pushToast(`Uploaded ${body.filename ?? file.name}`, 'success')
        await loadSources()
        setUxMode('manage')
        setManageTab('upload')
        setMode('inputs')
        setLabel('uploads')
      } catch (err) {
        pushToast(err instanceof Error ? err.message : String(err), 'error')
      }
    }
    input.click()
  }

  /** Result of one ingest job's SSE stream — the job "completing" only means
   * it finished running, not that every URL/file succeeded. */
  type IngestStreamResult = { totalFiles: number; errorCount: number }

  const trackIngestEvent = (raw: string, acc: IngestStreamResult) => {
    try {
      const data = JSON.parse(raw) as { type?: string; status?: string; total_files?: number }
      if (data.type === 'summary' && typeof data.total_files === 'number') {
        acc.totalFiles = data.total_files
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
      return acc
    }
    await new Promise<void>((resolve, reject) => {
      const es = new EventSource(apiUrl(path))
      es.onmessage = (ev) => {
        setIngestLog((l) => [...l, ev.data].slice(-100))
        trackIngestEvent(ev.data, acc)
        try {
          const data = JSON.parse(ev.data) as { type?: string }
          if (data.type === 'summary') {
            es.close()
            resolve()
          }
        } catch {
          /* ignore */
        }
      }
      es.onerror = () => {
        es.close()
        reject(new Error('Ingest stream error'))
      }
    })
    return acc
  }

  /** Turn a stream result into the right toast — never claim success when
   * every URL errored or nothing was actually ingested. */
  const pushIngestResultToast = (label: string, result: IngestStreamResult) => {
    if (result.errorCount > 0 && result.totalFiles === 0) {
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
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const startHfIngest = async () => {
    try {
      const res = await apiJson<{ job_id: string }>('/ingest/huggingface', {
        method: 'POST',
        body: JSON.stringify({
          repo_id: hfRepo,
          split: 'train',
          audio_col: 'audio',
          label_override: ingestLabel.trim() || undefined,
        }),
      })
      setIngestLog([`job ${res.job_id} started`])
      const result = await streamJob(res.job_id, 'huggingface')
      pushIngestResultToast('HF ingest', result)
      await loadSources()
    } catch (err) {
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
        `/data/outputs/${encodeURIComponent(project)}/${encodeURIComponent(version)}`,
        { method: 'DELETE' },
      )
      pushToast(`Deleted ${project}/${version}`, 'success')
      setVersion('')
      setRows([])
      setStats(null)
      await loadSources()
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
        }),
      })
      const mergeResult = formatMergeToast(res)
      pushToast(mergeResult.message, mergeResult.tone)
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

  const filteredInputs = React.useMemo(
    () => inputs.filter((i) => matchesQuery(`${i.label} ${i.file_count}`, listFilter)),
    [inputs, listFilter],
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
  const filteredRows = React.useMemo(
    () =>
      rows.filter((r) =>
        matchesQuery(`${String(r.path ?? '')} ${String(r.split ?? r.label ?? '')}`, listFilter),
      ),
    [rows, listFilter],
  )
  const displayRows = filteredRows.slice(0, LIST_CAP)
  const listTruncated = filteredRows.length > LIST_CAP

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

  const showFileBrowser = uxMode === 'browse' || (uxMode === 'manage' && manageTab === 'upload')
  const showEmptyOutputs = mode === 'outputs' && (outputs.length === 0 || pathRecovery)
  const showEmptyInputs = mode === 'inputs' && inputs.length === 0

  const searchField = (
    <label className="relative block min-w-[12rem] flex-1 max-w-sm">
      <span className="sr-only">Filter lists</span>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
      <input
        value={listFilter}
        onChange={(e) => setListFilter(e.target.value)}
        placeholder={mode === 'inputs' ? 'Filter labels or files…' : 'Filter projects or files…'}
        className="w-full rounded-lg border border-ink-200 py-1.5 pl-8 pr-2 text-sm"
      />
    </label>
  )

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6 space-y-4">
      <PageHeader
        title="Datasets"
        description="Shared Inputs and Outputs for pipelines — not the same as per-run downloads under Runs."
        actions={
          <div className="flex gap-2">
            {/* Not duplicated here — the Manage toolbar already has its own
                Upload button (same handler) scoped to the selected label,
                which used to render alongside this one whenever
                uxMode==='manage' && manageTab==='upload', showing the exact
                same action twice at once. */}
            <button type="button" className="btn-secondary" onClick={() => void loadSources()}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
          </div>
        }
      />
      {!storageHintDismissed ? (
        <div
          role="note"
          className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-ink-200 bg-ink-50/80 px-3 py-2 text-[12px] leading-relaxed text-ink-700"
        >
          <p>
            <strong className="font-medium text-ink-900">Which storage?</strong> Datasets = shared
            folders · Runs → Run outputs = one run · Artifacts = cross-run registry.
          </p>
          <button
            type="button"
            className="shrink-0 text-[11px] font-semibold text-ink-500 hover:text-ink-800"
            onClick={() => {
              try {
                localStorage.setItem('graphyn.datasets.storageHint', '1')
              } catch {
                /* ignore */
              }
              setStorageHintDismissed(true)
            }}
          >
            Got it
          </button>
        </div>
      ) : null}
      {uxMode === 'manage' ? (
      <div
        role="note"
        className="rounded-xl border border-dashed border-ink-200 bg-white/80 px-3 py-2 text-[12px] leading-relaxed text-ink-700"
      >
        <span className="font-medium text-ink-900">Label lite:</span> use Outputs versions + Home pins;
        full labeling studio is not available yet.{' '}
        <button
          type="button"
          className="font-medium text-accent-800 hover:underline"
          onClick={() => {
            if (activeProject) openProjects({ project: activeProject })
            else openProjects()
          }}
        >
          Open Home
        </button>
      </div>
      ) : null}
      {showBrowseError ? (
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
      ) : null}
      {mode === 'inputs' && blockedInputs.length > 0 && !showBrowseError ? (
        <div
          role="note"
          className="rounded-xl border border-amber-100 bg-amber-50/70 px-3 py-2 text-[12px] leading-relaxed text-amber-950"
        >
          <span className="font-medium">{blockedInputs.length} external label
          {blockedInputs.length === 1 ? '' : 's'}</span>{' '}
          (symlink outside datasets/input) — skipped in Browse.
          {accessibleInputs.length === 0
            ? ' Set GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1 on the API (Compose default is on) and Refresh.'
            : ' Pick an in-tree label below, or enable external symlinks on the API.'}
        </div>
      ) : null}

      <div
        className="inline-flex rounded-xl border border-ink-200 bg-ink-50/80 p-0.5"
        role="tablist"
        aria-label="Data mode"
      >
        {(
          [
            ['browse', 'Browse'],
            ['manage', 'Manage'],
          ] as const
        ).map(([m, tabLabel]) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={uxMode === m}
            className={clsx(
              'rounded-[10px] px-3.5 py-1.5 text-[13px] font-medium transition',
              uxMode === m
                ? 'bg-white text-ink-950 shadow-sm ring-1 ring-ink-200/80'
                : 'text-ink-500 hover:text-ink-800',
            )}
            onClick={() => switchUxMode(m)}
          >
            {tabLabel}
          </button>
        ))}
      </div>

      {uxMode === 'browse' ? (
        <div className="flex flex-wrap gap-2">
          {(
            [
              ['inputs', 'Inputs'],
              ['outputs', 'Outputs'],
            ] as const
          ).map(([m, tabLabel]) => (
            <button
              key={m}
              type="button"
              className={mode === m ? 'btn-primary' : 'btn-secondary'}
              onClick={() => {
                setError(null)
                setErrorDetail(null)
                setPathRecovery(false)
                setListFilter('')
                setMode(m)
              }}
            >
              {tabLabel}
            </button>
          ))}
          <span className="self-center text-[11px] text-ink-400">Read-only — open / play files</span>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {(
            [
              ['upload', 'Upload'],
              ['ingest', 'Ingest'],
              ['merge', 'Merge'],
            ] as const
          ).map(([tab, tabLabel]) => (
            <button
              key={tab}
              type="button"
              className={manageTab === tab ? 'btn-primary' : 'btn-secondary'}
              onClick={() => setManage(tab)}
            >
              {tabLabel}
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <LoadingBlock />
      ) : uxMode === 'manage' && manageTab === 'ingest' ? (
        <div className="space-y-4">
          <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-2">
            <h3 className="text-sm font-semibold">URL ingest</h3>
            <textarea value={urls} onChange={(e) => setUrls(e.target.value)} rows={4} className="w-full rounded-lg border border-ink-200 p-2 text-sm" placeholder="one URL per line" />
            <input value={ingestLabel} onChange={(e) => setIngestLabel(e.target.value)} className="rounded-lg border border-ink-200 px-2 py-1 text-sm" />
            <button type="button" className="btn-primary" onClick={() => void startUrlIngest()}>Start URL ingest</button>
          </section>
          <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-2">
            <h3 className="text-sm font-semibold">HuggingFace ingest</h3>
            <input value={hfRepo} onChange={(e) => setHfRepo(e.target.value)} placeholder="org/dataset" className="w-full rounded-lg border border-ink-200 px-2 py-1 text-sm" />
            <button type="button" className="btn-secondary" onClick={() => void startHfIngest()}>Start HF ingest</button>
          </section>
          <pre className="max-h-48 overflow-auto rounded-xl bg-ink-950 p-3 font-mono text-[11px] text-ink-100">
            {ingestLog.map((line) => formatExecutionLine(line).text).join('\n') || 'No ingest events yet — start a job to stream GET /ingest/url/{job_id}/stream progress here.'}
          </pre>
        </div>
      ) : uxMode === 'manage' && manageTab === 'merge' ? (
        <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-2">
          <h3 className="text-sm font-semibold">Merge datasets</h3>
          <p className="text-sm text-ink-500">Comma-separated project:version pairs combined into the target project version.</p>
          <input value={mergeSources} onChange={(e) => setMergeSources(e.target.value)} className="w-full rounded-lg border border-ink-200 px-2 py-1 text-sm" placeholder="project:version, other:v2" />
          <input value={mergeTargetProject} onChange={(e) => setMergeTargetProject(e.target.value)} className="w-full rounded-lg border border-ink-200 px-2 py-1 text-sm" placeholder="target project" />
          <input value={mergeTargetVersion} onChange={(e) => setMergeTargetVersion(e.target.value)} className="w-full rounded-lg border border-ink-200 px-2 py-1 text-sm" placeholder="target version" />
          <button type="button" className="btn-primary" onClick={() => void doMerge()}>Merge</button>
        </section>
      ) : showFileBrowser ? (
        <>
          {mode === 'outputs' ? (
            showEmptyOutputs ? (
              <EmptyState
                title={pathRecovery ? 'Dataset path reset' : 'No output datasets yet'}
                description={
                  pathRecovery
                    ? 'The selected path was invalid or outside the workspace, so selection was cleared.'
                    : uxMode === 'manage'
                      ? 'Upload files or ingest URLs, then run a template to populate Outputs.'
                      : 'Outputs appear after a template or export writes version folders. Link a project workspace, or browse templates to produce data.'
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
                      Open Projects
                    </button>
                  )
                }
              />
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                {searchField}
                <select
                  value={project}
                  onChange={(e) => {
                    setError(null)
                    setErrorDetail(null)
                    libraryClearRef.current = false
                    skipProjectHashRef.current = false
                    const next = e.target.value
                    setProject(next)
                    setVersion(outputs.find((o) => o.project === next)?.versions[0] ?? '')
                  }}
                  className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
                >
                  <option value="">Select project…</option>
                  {(listFilter.trim() ? filteredOutputs : outputs).map((o) => (
                    <option key={o.project} value={o.project}>{o.project}</option>
                  ))}
                </select>
                <select value={version} onChange={(e) => { setError(null); setErrorDetail(null); setVersion(e.target.value) }} className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm">
                  {versions.map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
                {project ? (
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
                      <button
                        type="button"
                        className="btn-quiet text-[12px]"
                        onClick={() => openProjects({ project: activeProject })}
                      >
                        Open Home
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
                      // Stay on outputs — this button lives in the outputs
                      // toolbar, so forcing 'inputs' here (as the Manage tab
                      // used to) would drop the project/version the user was
                      // just browsing and land them on the unrelated Upload
                      // panel instead of the delete-output-version view.
                      setMode('outputs')
                    }}
                  >
                    Manage…
                  </button>
                ) : null}
              </div>
            )
          ) : showEmptyInputs ? (
            <EmptyState
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
                  Upload a file
                </button>
              }
            />
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              {searchField}
              <select
                value={label}
                onChange={(e) => {
                  const next = e.target.value
                  if (next) skippedInputLabels.current.delete(next)
                  setError(null)
                  setErrorDetail(null)
                  setLabel(next)
                }}
                className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
              >
                {!label ? <option value="">Select a label…</option> : null}
                {(listFilter.trim() ? filteredInputs : inputs).map((i) => (
                  <option key={i.label} value={i.label}>
                    {i.label} ({i.file_count})
                    {i.accessible === false ? ' — external (blocked)' : ''}
                  </option>
                ))}
              </select>
              {uxMode === 'manage' && label ? (
                <ConfirmButton
                  label="Delete"
                  confirmLabel={`Delete input ${label}?`}
                  danger
                  onConfirm={() => void deleteInput()}
                />
              ) : null}
              {activeProject ? (
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => {
                    useAppStore.getState().openProject(activeProject)
                  }}
                >
                  Open Home
                </button>
              ) : label ? (
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => openProjects()}
                >
                  Use in workspace
                </button>
              ) : null}
              {uxMode === 'manage' ? (
                <button type="button" className="btn-secondary" onClick={upload}>
                  <Upload className="h-3.5 w-3.5" /> Upload
                </button>
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
          )}

          {uxMode === 'manage' && manageTab === 'upload' ? (
            <details className="rounded-xl border border-ink-100 bg-ink-50/60">
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
                  className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
                >
                  <option value="">Select project…</option>
                  {outputs.map((o) => (
                    <option key={o.project} value={o.project}>{o.project}</option>
                  ))}
                </select>
                <select
                  value={version}
                  onChange={(e) => setVersion(e.target.value)}
                  className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
                >
                  {versions.map((v) => (
                    <option key={v} value={v}>{v}</option>
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

          {showEmptyOutputs || showEmptyInputs ? null : stats != null && <KeyValue data={stats} />}
          {showEmptyOutputs || showEmptyInputs ? null : showBrowseError && filteredRows.length === 0 ? (
            <EmptyState
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
              title={
                listFilter.trim()
                  ? 'No matches'
                  : mode === 'inputs' && !label
                    ? accessibleInputs.length
                      ? 'Pick an input label'
                      : blockedInputs.length
                        ? 'No browseable labels'
                        : 'Pick an input label'
                    : 'No rows'
              }
              description={
                listFilter.trim()
                  ? 'Nothing matches this filter. Clear it to see the full list.'
                  : mode === 'outputs'
                    ? 'This version has no files yet. Run a pipeline or merge datasets to populate it.'
                    : !label
                      ? accessibleInputs.length
                        ? 'Choose a label from the dropdown to browse shared input files.'
                        : blockedInputs.length
                          ? 'All labels are external symlinks. Enable GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1 on the API (Compose defaults to on), then Refresh.'
                          : 'Choose a label from the dropdown to browse shared input files.'
                      : 'This label has no files yet. Upload or ingest to add some.'
              }
              action={
                listFilter.trim() ? (
                  <button type="button" className="btn-primary" onClick={() => setListFilter('')}>
                    Clear filter
                  </button>
                ) : mode === 'inputs' && label ? (
                  <button type="button" className="btn-primary" onClick={upload}>
                    Upload a file
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
              {listTruncated ? (
                <p className="text-[12px] text-ink-500">
                  Showing first {LIST_CAP} of {filteredRows.length} files
                  {listFilter.trim() ? ' matching this filter' : ''}. Refine the filter to narrow results.
                </p>
              ) : null}
              <div className="rounded-2xl border border-ink-200 bg-white">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-ink-100 text-[11px] uppercase text-ink-500">
                    <tr><th className="px-3 py-2">Path</th><th className="px-3 py-2">Meta</th><th className="px-3 py-2">Open</th></tr>
                  </thead>
                  <tbody>
                    {displayRows.map((r, i) => {
                      const path = String(r.path ?? '')
                      return (
                        <tr key={i} className="border-b border-ink-50">
                          <td className="px-3 py-2 font-mono text-[11px]">
                            {path ? <CopyableMono value={path} /> : '—'}
                          </td>
                          <td className="px-3 py-2 text-[11px] text-ink-500">{String(r.split ?? r.label ?? '')}</td>
                          <td className="px-3 py-2">
                            <button type="button" className="text-accent-700 underline" onClick={() => void openFile(path, mode === 'outputs' ? 'files' : 'input-files')}>
                              open
                            </button>
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
      ) : null}
    </div>
  )
}
