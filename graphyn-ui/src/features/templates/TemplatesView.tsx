import React from 'react'
import { RefreshCw, Download, MoreHorizontal, Upload } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import type { GraphIR } from '../../types/graph'
import { ConfirmButton, EmptyState, ErrorBanner, LoadingBlock, PageHeader } from '../../components/ui'
import { humanizeTemplateName } from '../../lib/format'

function isExampleTemplate(name: string): boolean {
  return name.startsWith('ex-')
}

export default function TemplatesView() {
  const getCanvasGraph = useAppStore((s) => s.getCanvasGraph)
  const pushToast = useAppStore((s) => s.pushToast)
  const [names, setNames] = React.useState<string[] | null>(null)
  const [versionsMap, setVersionsMap] = React.useState<Record<string, string[]>>({})
  const [latestMap, setLatestMap] = React.useState<Record<string, string | null>>({})
  const [selectedVersion, setSelectedVersion] = React.useState<Record<string, string>>({})
  const [saveName, setSaveName] = React.useState('')
  const [saveOpen, setSaveOpen] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [syncing, setSyncing] = React.useState(false)
  const [filter, setFilter] = React.useState<'all' | 'examples' | 'saved'>('all')
  const [menuFor, setMenuFor] = React.useState<string | null>(null)
  const menuRef = React.useRef<HTMLDivElement | null>(null)

  const load = React.useCallback(async () => {
    setError(null)
    try {
      const list = await apiJson<string[]>('/pipelines/templates')
      setNames(list)
      const versions: Record<string, string[]> = {}
      const latest: Record<string, string | null> = {}
      await Promise.all(
        list.map(async (name) => {
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
      setNames([])
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  React.useEffect(() => {
    if (!menuFor) return
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuFor(null)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [menuFor])

  const importExamples = async () => {
    setSyncing(true)
    try {
      const res = await apiJson<{ count_written?: number; errors?: unknown[] }>(
        '/pipelines/templates/sync-examples',
        { method: 'POST', query: { force: true } },
      )
      const n = res.count_written ?? 0
      const errs = Array.isArray(res.errors) ? res.errors.length : 0
      pushToast(
        errs ? `Imported ${n} examples (${errs} errors)` : `Imported ${n} example templates`,
        errs ? 'error' : 'success',
      )
      setFilter('examples')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setSyncing(false)
    }
  }

  const loadIntoBuilder = async (name: string) => {
    try {
      const raw = selectedVersion[name] || latestMap[name] || undefined
      const version = raw && raw !== 'unversioned' ? raw : undefined
      const data = await apiJson<{ graph?: GraphIR }>(
        `/pipelines/templates/${encodeURIComponent(name)}`,
        { query: { version } },
      )
      if (!data.graph) throw new Error('Template has no graph payload')
      useAppStore.getState().loadGraphIntoBuilder(data.graph)
      pushToast(`Loaded ${humanizeTemplateName(name)}${version ? ` @ ${version}` : ''}`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const saveFromCanvas = async () => {
    if (!/^[A-Za-z0-9_-]+$/.test(saveName)) {
      pushToast('Invalid template name', 'error')
      return
    }
    const graph = getCanvasGraph?.()
    if (!graph || typeof graph !== 'object') {
      pushToast('Open Builder and build a graph first', 'error')
      return
    }
    try {
      const res = await apiJson<{ name: string; version?: string }>('/pipelines/templates', {
        method: 'POST',
        body: JSON.stringify({
          name: saveName,
          yaml: JSON.stringify(graph),
          description: 'Saved from Graphyn Builder canvas',
        }),
      })
      pushToast(`Saved ${res.name}${res.version ? ` @ ${res.version}` : ''}`, 'success')
      setSaveOpen(false)
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
  const filtered = (names ?? []).filter((name) => {
    if (filter === 'examples') return isExample(name)
    if (filter === 'saved') return !isExample(name)
    return true
  })
  const exampleCount = (names ?? []).filter(isExample).length

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <PageHeader
        title="Templates"
        description="Starter graphs and saved pipelines. Open one in Builder to run it."
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
            <button
              type="button"
              className="btn-secondary"
              disabled={syncing}
              onClick={() => void importExamples()}
              title="Copy example graphs into templates"
            >
              <Download className="h-3.5 w-3.5" />
              {syncing ? 'Syncing…' : 'Sync examples'}
            </button>
            {!saveOpen ? (
              <button type="button" className="btn-primary" onClick={() => setSaveOpen(true)}>
                Save from Builder
              </button>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                  placeholder="template-name"
                  className="field-control mt-0 w-44 text-sm"
                  autoFocus
                />
                <button type="button" className="btn-primary" onClick={() => void saveFromCanvas()}>
                  Save
                </button>
                <button type="button" className="btn-quiet" onClick={uploadFile}>
                  <Upload className="h-3.5 w-3.5" /> Upload
                </button>
                <button type="button" className="btn-quiet" onClick={() => setSaveOpen(false)}>
                  Cancel
                </button>
              </div>
            )}
          </div>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="flex flex-wrap gap-1.5">
        {(
          [
            ['all', 'All', names?.length ?? 0],
            ['examples', 'Examples', exampleCount],
            ['saved', 'Saved', Math.max(0, (names?.length ?? 0) - exampleCount)],
          ] as const
        ).map(([id, label, count]) => (
          <button
            key={id}
            type="button"
            className={filter === id ? 'catalog-pill catalog-pill-on' : 'catalog-pill'}
            onClick={() => setFilter(id)}
          >
            {label}
            {names ? ` ${count}` : ''}
          </button>
        ))}
      </div>

      {names === null ? (
        <LoadingBlock />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={filter === 'examples' ? 'No example templates' : 'No templates'}
          description={
            filter === 'examples'
              ? 'Sync example graphs from the repo, then open one in Builder.'
              : 'Sync examples, save from Builder, or upload a graph file.'
          }
          action={
            <button type="button" className="btn-secondary" onClick={() => void importExamples()}>
              Sync examples
            </button>
          }
        />
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((name) => {
            const versions = versionsMap[name] ?? []
            const latest = latestMap[name]
            return (
              <li
                key={name}
                className="group flex items-start gap-3 rounded-xl border border-ink-200/70 bg-white px-3 py-2.5 shadow-sm transition hover:shadow-soft"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <div className="truncate text-sm font-semibold text-ink-950">
                      {humanizeTemplateName(name)}
                    </div>
                    {isExample(name) && (
                      <span className="shrink-0 rounded-md bg-ink-100 px-1.5 py-px text-[10px] font-medium uppercase tracking-wide text-ink-500">
                        Example
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-ink-500">
                    {versions.length > 0 ? (
                      <>
                        <span>Latest {latest && latest !== 'unversioned' ? latest : versions[0]}</span>
                        <select
                          className="rounded-md border border-ink-200 bg-white px-1.5 py-0.5 text-[11px]"
                          value={selectedVersion[name] ?? latest ?? ''}
                          onChange={(e) =>
                            setSelectedVersion((s) => ({ ...s, [name]: e.target.value }))
                          }
                        >
                          {versions.map((v) => (
                            <option key={v} value={v}>
                              {v}
                            </option>
                          ))}
                        </select>
                      </>
                    ) : (
                      <span className="text-ink-300">—</span>
                    )}
                  </div>
                  <button
                    type="button"
                    className="btn-primary mt-2"
                    onClick={() => void loadIntoBuilder(name)}
                  >
                    Open in Builder
                  </button>
                </div>
                <div className="relative shrink-0" ref={menuFor === name ? menuRef : undefined}>
                  <button
                    type="button"
                    className="btn-icon"
                    aria-label={`More actions for ${humanizeTemplateName(name)}`}
                    onClick={() => setMenuFor((cur) => (cur === name ? null : name))}
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </button>
                  {menuFor === name && (
                    <div className="absolute right-0 z-20 mt-1 w-48 rounded-xl border border-ink-200 bg-white p-1.5 shadow-soft">
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
                          confirmLabel="Confirm delete"
                          danger
                          onConfirm={() =>
                            void apiJson(`/pipelines/templates/${encodeURIComponent(name)}`, {
                              method: 'DELETE',
                            })
                              .then(load)
                              .then(() => {
                                setMenuFor(null)
                                pushToast(`Deleted ${humanizeTemplateName(name)}`, 'success')
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
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
