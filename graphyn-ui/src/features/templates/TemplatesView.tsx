import React from 'react'
import { RefreshCw, Download, MoreHorizontal, Upload } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import type { GraphIR } from '../../types/graph'
import { ConfirmButton, EmptyState, ErrorBanner, LoadingBlock, PageHeader } from '../../components/ui'
import { humanizeTemplateName, humanNodeLabel } from '../../lib/format'

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
}

function normalizeList(raw: unknown): TemplateSummary[] {
  if (!Array.isArray(raw)) return []
  return raw.map((item) => {
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
  const [filter, setFilter] = React.useState<'all' | 'examples' | 'saved'>('all')
  const [menuFor, setMenuFor] = React.useState<string | null>(null)
  const menuRef = React.useRef<HTMLDivElement | null>(null)

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
    if (!menuFor) return
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuFor(null)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [menuFor])

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
  const filtered = (items ?? []).filter((t) => {
    if (filter === 'examples') return isExample(t.name)
    if (filter === 'saved') return !isExample(t.name)
    return true
  })
  const exampleCount = (items ?? []).filter((t) => isExample(t.name)).length

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
      {syncBanner && (
        <ErrorBanner
          title={`Sync finished with ${syncBanner.errors.length} issue${syncBanner.errors.length === 1 ? '' : 's'}`}
          message={`Imported ${syncBanner.written} template${syncBanner.written === 1 ? '' : 's'}. Review the issues below — cards still list what succeeded.`}
          detail={syncBanner.errors
            .map((e) => (typeof e === 'string' ? e : `${e.id ?? 'item'}: ${e.error ?? 'unknown'}`))
            .join('\n')}
          onDismiss={() => setSyncBanner(null)}
          onRetry={() => void importExamples()}
        />
      )}

      <div className="flex flex-wrap gap-1.5">
        {(
          [
            ['all', 'All', items?.length ?? 0],
            ['examples', 'Examples', exampleCount],
            ['saved', 'Saved', Math.max(0, (items?.length ?? 0) - exampleCount)],
          ] as const
        ).map(([id, label, count]) => (
          <button
            key={id}
            type="button"
            className={filter === id ? 'catalog-pill catalog-pill-on' : 'catalog-pill'}
            onClick={() => setFilter(id)}
          >
            {label}
            {items ? ` ${count}` : ''}
          </button>
        ))}
      </div>

      {items === null ? (
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
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((tpl) => {
            const name = tpl.name
            const versions = versionsMap[name] ?? []
            const latest = latestMap[name]
            return (
              <li
                key={name}
                className="group flex flex-col gap-2 rounded-xl border border-ink-200/70 bg-white px-3.5 py-3 shadow-sm transition hover:shadow-soft"
              >
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="truncate text-type-body font-semibold text-ink-950">
                        {humanizeTemplateName(name)}
                      </div>
                      {isExample(name) && (
                        <span className="shrink-0 rounded-md bg-ink-100 px-1.5 py-px text-type-meta font-medium uppercase tracking-wide text-ink-500">
                          Example
                        </span>
                      )}
                      {tpl.difficulty ? (
                        <span className="shrink-0 rounded-md bg-accent-50 px-1.5 py-px text-type-meta font-medium capitalize text-accent-800">
                          {tpl.difficulty}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 line-clamp-2 text-type-secondary text-ink-600">
                      {tpl.description?.trim()
                        ? tpl.description
                        : 'Open in Builder to inspect nodes and run this pipeline.'}
                    </p>
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
                </div>

                <dl className="grid gap-1.5 text-type-secondary text-ink-600">
                  <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-start gap-2">
                    <dt className="text-type-meta font-medium uppercase tracking-wide text-ink-400">Inputs</dt>
                    <dd>{chipList(tpl.inputs, 'None declared')}</dd>
                  </div>
                  <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-start gap-2">
                    <dt className="text-type-meta font-medium uppercase tracking-wide text-ink-400">Outputs</dt>
                    <dd>{chipList(tpl.outputs, 'None declared', (s) => (s.includes('/') ? s : humanNodeLabel(s)))}</dd>
                  </div>
                  <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-start gap-2">
                    <dt className="text-type-meta font-medium uppercase tracking-wide text-ink-400">Plugins</dt>
                    <dd>{chipList(tpl.required_plugins, '—')}</dd>
                  </div>
                  {(tpl.node_count ?? 0) > 0 && (
                    <div className="text-type-meta text-ink-400">
                      {tpl.node_count} node{(tpl.node_count ?? 0) === 1 ? '' : 's'}
                      {tpl.node_types?.length
                        ? ` · ${tpl.node_types.slice(0, 3).map(humanNodeLabel).join(', ')}${tpl.node_types.length > 3 ? '…' : ''}`
                        : ''}
                    </div>
                  )}
                </dl>

                <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-ink-100 pt-2">
                  {versions.length > 0 ? (
                    <>
                      <span className="text-type-meta text-ink-500">
                        Latest {latest && latest !== 'unversioned' ? latest : versions[0]}
                      </span>
                      <select
                        className="rounded-md border border-ink-200 bg-white px-1.5 py-0.5 text-type-meta"
                        value={selectedVersion[name] ?? latest ?? ''}
                        onChange={(e) =>
                          setSelectedVersion((s) => ({ ...s, [name]: e.target.value }))
                        }
                        aria-label={`Version for ${humanizeTemplateName(name)}`}
                      >
                        {versions.map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </>
                  ) : (
                    <span className="text-type-meta text-ink-300">Unversioned</span>
                  )}
                  <button
                    type="button"
                    className="btn-primary ml-auto"
                    onClick={() => void loadIntoBuilder(name)}
                  >
                    Open in Builder
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
