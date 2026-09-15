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

interface OutputProject {
  project: string
  versions: string[]
}
interface InputLabel {
  label: string
  file_count: number
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

function parseDataHash(): {
  mode?: DataMode
  project?: string
  version?: string
  label?: string
  manage?: boolean
} {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const qIdx = raw.indexOf('?')
  if (qIdx < 0) return {}
  const params = new URLSearchParams(raw.slice(qIdx + 1))
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
    project: sanitizePathSeg(params.get('project')),
    version: sanitizePathSeg(params.get('version')),
    label: sanitizePathSeg(params.get('label')),
    manage,
  }
}

function isInvalidWorkspacePathError(detail: string): boolean {
  return /path is outside workspace|invalid path segment/i.test(detail)
}

function humanizeDataError(err: unknown): { message: string; detail: string; invalidPath: boolean } {
  const detail = err instanceof Error ? err.message : String(err)
  if (isInvalidWorkspacePathError(detail)) {
    return {
      message:
        'That dataset path is invalid or no longer inside the Graphyn workspace. Selection was cleared — pick a project/version again, or start fresh below.',
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
  const setView = useAppStore((s) => s.setView)
  const activeProject = useAppStore((s) => s.activeProject)
  const dataUnscopeEpoch = useAppStore((s) => s.dataUnscopeEpoch)
  const initialHash = React.useMemo(() => parseDataHash(), [])
  const [outputs, setOutputs] = React.useState<OutputProject[]>([])
  const [inputs, setInputs] = React.useState<InputLabel[]>([])
  const [mode, setMode] = React.useState<DataMode>(initialHash.mode ?? 'inputs')
  const [uxMode, setUxMode] = React.useState<'browse' | 'manage'>(() => {
    if (initialHash.manage === true) return 'manage'
    if (initialHash.manage === false) return 'browse'
    const m = initialHash.mode
    return m === 'ingest' || m === 'merge' ? 'manage' : 'browse'
  })
  const [manageTab, setManageTab] = React.useState<ManageTab>(() =>
    manageTabFromMode(initialHash.mode ?? 'inputs'),
  )
  const [project, setProject] = React.useState(initialHash.project ?? '')
  const [version, setVersion] = React.useState(initialHash.version ?? '')
  const [label, setLabel] = React.useState(initialHash.label ?? '')
  const [rows, setRows] = React.useState<Array<Record<string, unknown>>>([])
  const [stats, setStats] = React.useState<unknown>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [errorDetail, setErrorDetail] = React.useState<string | null>(null)
  const [pathRecovery, setPathRecovery] = React.useState(false)
  const [listFilter, setListFilter] = React.useState('')
  const skippedOutputKey = React.useRef<string | null>(null)
  /** After closeProject: keep outputs dropdown empty; do not revive prior project via loadSources/hash-sync. */
  const libraryClearRef = React.useRef(false)
  /** Omit project from hash while clearing — prevents stale React state from re-writing ?project=. */
  const skipProjectHashRef = React.useRef(false)
  const appliedUnscopeEpochRef = React.useRef<number | null>(null)
  const [loading, setLoading] = React.useState(true)

  // Layout before hash-sync effect: reset selection when workspace project is closed.
  React.useLayoutEffect(() => {
    const first = appliedUnscopeEpochRef.current === null
    const prevEpoch = appliedUnscopeEpochRef.current
    appliedUnscopeEpochRef.current = dataUnscopeEpoch
    if (first) {
      // Mounted after a close into global Data (no ?project=): prevent loadSources from auto-picking
      // the previous workspace project. Honor explicit openData({ project }) / deep links.
      if (dataUnscopeEpoch > 0 && activeProject == null && !initialHash.project) {
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
        if (safe && inp.some((i) => i.label === safe)) return safe
        return inp[0]?.label ?? ''
      })
    } catch (err) {
      const h = humanizeDataError(err)
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
      const h = parseDataHash()
      if (h.mode) {
        setMode(h.mode)
        setManageTab(manageTabFromMode(h.mode))
      }
      if (h.manage === true) setUxMode('manage')
      else if (h.manage === false) setUxMode('browse')
      else if (h.mode === 'ingest' || h.mode === 'merge') setUxMode('manage')
      const raw = window.location.hash
      if (h.project) {
        libraryClearRef.current = false
        setProject(h.project)
      } else if (raw.startsWith('#/data') && !/[?&]project=/.test(raw)) {
        // Close-project stripped ?project= — unscope global library selection.
        libraryClearRef.current = true
        skipProjectHashRef.current = true
        setProject('')
        setVersion('')
      }
      if (h.version) setVersion(h.version)
      if (h.label) setLabel(h.label)
    }
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [])

  // Mirror Projects: write selection into the hash (no hashchange — avoid echo loops).
  React.useEffect(() => {
    const params = new URLSearchParams()
    if (mode) params.set('mode', mode)
    if (uxMode === 'manage' && (mode === 'inputs' || mode === 'outputs')) {
      params.set('manage', '1')
    }
    // When activeProject was cleared, do not re-write stale project into the hash.
    if (skipProjectHashRef.current) {
      if (!project.trim()) {
        skipProjectHashRef.current = false
      }
      // omit project + version while clearing / stale
    } else if (project.trim()) {
      params.set('project', project.trim())
      if (version.trim()) params.set('version', version.trim())
    } else if (version.trim()) {
      params.set('version', version.trim())
    }
    if (label.trim()) params.set('label', label.trim())
    const qs = params.toString()
    const next = qs ? `#/data?${qs}` : '#/data'
    if (window.location.hash !== next) {
      window.history.replaceState(null, '', next)
    }
  }, [mode, uxMode, project, version, label, dataUnscopeEpoch])

  React.useEffect(() => {
    let cancelled = false
    const run = async () => {
      setError(null)
      setErrorDetail(null)
      if (mode === 'outputs') {
        if (!project || !version) {
          setRows([])
          setStats(null)
          return
        }
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
          const h = humanizeDataError(err)
          setError(h.message)
          setErrorDetail(h.detail)
          setRows([])
          setStats(null)
          if (h.invalidPath) {
            skippedOutputKey.current = `${project}/${version}`
            setPathRecovery(true)
            setProject('')
            setVersion('')
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
        try {
          const data = await apiJson<Array<Record<string, unknown>>>(
            `/data/inputs/${encodeURIComponent(label)}`,
          )
          if (cancelled) return
          setRows(data)
          setStats(null)
        } catch (err) {
          if (cancelled) return
          const h = humanizeDataError(err)
          setError(h.message)
          setErrorDetail(h.detail)
          setRows([])
          setStats(null)
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
  }, [mode, project, version, label, loadSources])

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

  const streamJob = async (jobId: string, kind: 'url' | 'huggingface') => {
    const path = `/ingest/${kind}/${jobId}/stream`
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
          setIngestLog((l) => [...l, line.slice(5).trim()].slice(-100))
        }
      }
      return
    }
    await new Promise<void>((resolve, reject) => {
      const es = new EventSource(apiUrl(path))
      es.onmessage = (ev) => {
        setIngestLog((l) => [...l, ev.data].slice(-100))
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
  }

  const startUrlIngest = async () => {
    try {
      const list = urls.split('\n').map((u) => u.trim()).filter(Boolean)
      const res = await apiJson<{ job_id: string }>('/ingest/url', {
        method: 'POST',
        body: JSON.stringify({ urls: list, label: ingestLabel }),
      })
      setIngestLog([`job ${res.job_id} started`])
      await streamJob(res.job_id, 'url')
      pushToast('URL ingest complete', 'success')
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
      await streamJob(res.job_id, 'huggingface')
      pushToast('HF ingest complete', 'success')
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
      pushToast(formatMergeToast(res), 'success')
      await loadSources()
      if (mergeTargetProject.trim()) {
        openProjects({ project: mergeTargetProject.trim() })
      }
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const browseTemplatesForDataPrep = () => {
    setView('templates')
    window.history.replaceState(null, '', '#/templates')
    pushToast('Open a data-prep or ingest template in Editor', 'info')
  }

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
      setMode('inputs')
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
    <div className="h-full overflow-y-auto p-6 space-y-4">
      <PageHeader
        title="Datasets"
        description="Shared Inputs/Outputs under workspace/datasets. Not the same as Runs → Files (per-run downloads)."
        actions={
          <div className="flex gap-2">
            {uxMode === 'manage' && manageTab === 'upload' && (
              <button type="button" className="btn-secondary" onClick={upload}>
                <Upload className="h-3.5 w-3.5" /> Upload
              </button>
            )}
            <button type="button" className="btn-secondary" onClick={() => void loadSources()}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
          </div>
        }
      />
      {error && <ErrorBanner message={error} title={errorDetail ?? undefined} onRetry={() => void loadSources()} />}

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
            {ingestLog.map((line) => formatExecutionLine(line).text).join('\n') || 'No ingest events yet.'}
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
                        onClick={() => {
                          useAppStore.getState().setView('builder')
                          window.history.replaceState(null, '', '#/builder')
                          window.dispatchEvent(new HashChangeEvent('hashchange'))
                        }}
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
                      setMode('inputs')
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
                onChange={(e) => { setError(null); setErrorDetail(null); setLabel(e.target.value) }}
                className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
              >
                {(listFilter.trim() ? filteredInputs : inputs).map((i) => (
                  <option key={i.label} value={i.label}>{i.label} ({i.file_count})</option>
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
          {showEmptyOutputs || showEmptyInputs ? null : filteredRows.length === 0 ? (
            <EmptyState
              title={listFilter.trim() ? 'No matches' : 'No rows'}
              description={
                listFilter.trim()
                  ? 'Nothing matches this filter. Clear it to see the full list.'
                  : mode === 'outputs'
                    ? 'This version has no files yet. Run a pipeline or merge datasets to populate it.'
                    : 'Upload files or ingest URLs to see files here.'
              }
              action={
                listFilter.trim() ? (
                  <button type="button" className="btn-primary" onClick={() => setListFilter('')}>
                    Clear filter
                  </button>
                ) : mode === 'inputs' ? (
                  <button type="button" className="btn-primary" onClick={upload}>
                    Upload a file
                  </button>
                ) : (
                  <button type="button" className="btn-primary" onClick={browseTemplatesForDataPrep}>
                    Browse Templates
                  </button>
                )
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
