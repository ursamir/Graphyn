import React from 'react'
import { Box, CheckCircle2, GitBranch, RefreshCw, Shield } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { EmptyState, ErrorBanner, LoadingBlock, StatusBadge } from '../../components/ui'
import { MasterDetail, ViewShell } from '../../layout'
import { paths } from '../../routes/paths'
import { navigatePath } from '../../routes/parsePath'

type ModelRow = {
  name: string
  description?: string
  stages?: Record<string, { run_id?: string; slug?: string }>
  // Sibling of `stages`, not nested under it (app/core/model_registry.py:
  // request_prod() writes `cur["pending_prod"] = {...}` at the record's top level).
  pending_prod?: { run_id?: string; slug?: string; requested_at?: string; requested_by?: string } | null
  updated_at?: string
  created_at?: string
}

export default function ModelsView() {
  const activeProject = useAppStore((s) => s.activeProject)
  const openRun = useAppStore((s) => s.openRun)
  const openTrace = useAppStore((s) => s.openTrace)
  const openData = useAppStore((s) => s.openData)
  const openProjects = useAppStore((s) => s.openProjects)
  const pushToast = useAppStore((s) => s.pushToast)
  const setView = useAppStore((s) => s.setView)
  const [rows, setRows] = React.useState<ModelRow[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [selected, setSelected] = React.useState<string | null>(null)
  const [detail, setDetail] = React.useState<ModelRow | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [registerOpen, setRegisterOpen] = React.useState(false)
  const [regName, setRegName] = React.useState('')
  const [regRunId, setRegRunId] = React.useState('')
  const [regSlug, setRegSlug] = React.useState('model')
  const [scopeMode, setScopeMode] = React.useState<'workspace' | 'all'>(
    () => (useAppStore.getState().activeProject ? 'workspace' : 'all'),
  )
  const [projectRunIds, setProjectRunIds] = React.useState<Set<string>>(() => new Set())
  const [projectRuns, setProjectRuns] = React.useState<
    Array<{ run_id: string; status?: string; graph_name?: string }>
  >([])


  React.useEffect(() => {
    setScopeMode(activeProject ? 'workspace' : 'all')
  }, [activeProject])

  React.useEffect(() => {
    let cancelled = false
    if (!activeProject) {
      setProjectRunIds(new Set())
      setProjectRuns([])
      return
    }
    void (async () => {
      try {
        const runs = await apiJson<Array<{ run_id: string; status?: string; graph_name?: string }>>(
          '/runs',
          { query: { project: activeProject, limit: 100, offset: 0 } },
        )
        if (cancelled) return
        const list = Array.isArray(runs) ? runs : []
        setProjectRuns(list)
        setProjectRunIds(new Set(list.map((r) => r.run_id).filter(Boolean)))
      } catch {
        if (!cancelled) {
          setProjectRuns([])
          setProjectRunIds(new Set())
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [activeProject])

  const load = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiJson<{ models?: ModelRow[] }>('/models')
      const list = Array.isArray(res?.models) ? res.models : []
      setRows(list)
      if (selected && !list.some((m) => m.name === selected)) setSelected(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setRows([])
      // Rows are empty — selected/detail no longer exist in the list.
      setSelected(null)
      setDetail(null)
    } finally {
      setLoading(false)
    }
  }, [selected])

  React.useEffect(() => {
    void load()
  }, [load])

  React.useEffect(() => {
    if (!selected) {
      setDetail(null)
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const d = await apiJson<ModelRow>(`/models/${encodeURIComponent(selected)}`)
        if (!cancelled) setDetail(d)
      } catch {
        if (!cancelled) setDetail(rows.find((r) => r.name === selected) || null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selected, rows])

  const requestProd = async (name: string) => {
    setBusy(true)
    try {
      await apiJson(`/models/${encodeURIComponent(name)}/request-prod`, {
        method: 'POST',
        body: JSON.stringify({}),
      })
      pushToast(`Prod approval requested for ${name}`, 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  const approveProd = async (name: string) => {
    setBusy(true)
    try {
      await apiJson(`/models/${encodeURIComponent(name)}/approve-prod`, { method: 'POST' })
      pushToast(`${name} approved for production`, 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  const register = async () => {
    const name = regName.trim()
    const run_id = regRunId.trim()
    const slug = regSlug.trim() || 'model'
    if (!name || !run_id) {
      pushToast('Name and run id are required', 'error')
      return
    }
    setBusy(true)
    try {
      await apiJson('/models', {
        method: 'POST',
        body: JSON.stringify({ name, run_id, slug, stage: 'staging' }),
      })
      pushToast(`Registered ${name}`, 'success')
      setRegisterOpen(false)
      setRegName('')
      setRegRunId('')
      await load()
      setSelected(name)
      if (activeProject) navigatePath(paths.model(activeProject, name), true)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(false)
    }
  }


  const modelRunIds = (row: ModelRow): string[] => {
    const stages = row.stages || {}
    const ids = [stages.prod?.run_id, stages.staging?.run_id, stages.latest?.run_id, row.pending_prod?.run_id]
    return ids.filter((x): x is string => Boolean(x))
  }

  const inWorkspace = (row: ModelRow) => {
    if (projectRunIds.size === 0) return false
    return modelRunIds(row).some((id) => projectRunIds.has(id))
  }

  const filteredRows =
    activeProject && scopeMode === 'workspace' ? rows.filter(inWorkspace) : rows

  const openWorkspaceRuns = () => {
    if (!activeProject) return
    setView('runs')
    navigatePath(paths.runs(activeProject))
  }

  const stages = detail?.stages || {}
  const primaryRunId =
    stages.prod?.run_id || stages.staging?.run_id || stages.latest?.run_id || undefined

  return (
    <ViewShell
      title="Models"
      description="Registry of promoted run artifacts — stages, request/approve prod, link back to training runs."
      actions={
        <>
          <button type="button" className="btn-secondary" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
          <button type="button" className="btn-primary" onClick={() => setRegisterOpen((v) => !v)}>
            Register model
          </button>
        </>
      }
      contentClassName="overflow-y-auto"
    >
      <div className="space-y-4 p-5 h-full min-h-0 flex flex-col">
      {activeProject ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-ink-100 bg-ink-50/80 px-3 py-2 text-[12px] text-ink-600">
          <p>
            {scopeMode === 'workspace' ? (
              <>
                <span className="font-medium text-ink-800">Models for this workspace</span>
                {' '}
                — showing registries whose staging/prod/latest run belongs to {activeProject}.
              </>
            ) : (
              <>
                Showing <span className="font-medium text-ink-800">all registries</span>
                {' '}
                (not filtered to {activeProject}).
              </>
            )}
          </p>
          <div className="inline-flex shrink-0 overflow-hidden rounded-lg border border-ink-200 bg-white text-[11px] font-medium">
            <button
              type="button"
              className={
                scopeMode === 'workspace'
                  ? 'bg-accent-50 px-2.5 py-1 text-accent-900'
                  : 'px-2.5 py-1 text-ink-500 hover:bg-ink-50'
              }
              onClick={() => setScopeMode('workspace')}
            >
              This workspace
            </button>
            <button
              type="button"
              className={
                scopeMode === 'all'
                  ? 'bg-accent-50 px-2.5 py-1 text-accent-900'
                  : 'px-2.5 py-1 text-ink-500 hover:bg-ink-50'
              }
              onClick={() => setScopeMode('all')}
            >
              All registries
            </button>
          </div>
        </div>
      ) : null}
      {registerOpen && (
        <div className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3 shadow-sm">
          <h3 className="text-sm font-semibold text-ink-950">Register from a run</h3>
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="text-[12px] text-ink-600">
              Name
              <input className="field-control mt-1" value={regName} onChange={(e) => setRegName(e.target.value)} />
            </label>
            <label className="text-[12px] text-ink-600">
              Run id
              {activeProject && projectRuns.length > 0 ? (
                <select
                  className="field-control mt-1 font-mono"
                  value={regRunId}
                  onChange={(e) => setRegRunId(e.target.value)}
                >
                  <option value="">Select a recent workspace run…</option>
                  {projectRuns.map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {r.run_id.slice(0, 12)}… {r.status || ''} {r.graph_name || ''}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className="field-control mt-1 font-mono"
                  value={regRunId}
                  onChange={(e) => setRegRunId(e.target.value)}
                  placeholder={activeProject ? `run id from ${activeProject}` : 'run id'}
                />
              )}
              {activeProject && projectRuns.length > 0 ? (
                <input
                  className="field-control mt-1 font-mono"
                  value={regRunId}
                  onChange={(e) => setRegRunId(e.target.value)}
                  placeholder="or paste run id"
                />
              ) : null}
            </label>
            <label className="text-[12px] text-ink-600">
              Slug
              <input className="field-control mt-1" value={regSlug} onChange={(e) => setRegSlug(e.target.value)} />
            </label>
          </div>
          <button type="button" className="btn-primary" disabled={busy} onClick={() => void register()}>
            Register to staging
          </button>
        </div>
      )}

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {loading ? (
        <LoadingBlock label="Loading models…" />
      ) : filteredRows.length === 0 ? (
        <EmptyState
          title={activeProject && scopeMode === 'workspace' ? 'No models for this workspace' : 'No registered models'}
          description={
            activeProject && scopeMode === 'workspace'
              ? 'Run a train pipeline, then register a model from a workspace run — or switch to All registries.'
              : 'Promote a run alias or register a model from Run outputs to populate the registry.'
          }
          action={
            activeProject && scopeMode === 'workspace' ? (
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn-primary" onClick={openWorkspaceRuns}>
                  Open Runs
                </button>
                <button type="button" className="btn-secondary" onClick={() => setScopeMode('all')}>
                  All registries
                </button>
                <button type="button" className="btn-secondary" onClick={() => setRegisterOpen(true)}>
                  Register model
                </button>
              </div>
            ) : (
              <button type="button" className="btn-primary" onClick={() => setRegisterOpen(true)}>
                Register model
              </button>
            )
          }
        />
      ) : (
        <MasterDetail
          className="min-h-0 flex-1"
          masterClassName="!p-0 !bg-transparent"
          detailClassName="!p-0"
          master={
          <ul className="divide-y divide-ink-100 overflow-hidden rounded-2xl border border-ink-200 bg-white">
            {filteredRows.map((m) => (
              <li key={m.name}>
                <button
                  type="button"
                  className={
                    selected === m.name
                      ? 'flex w-full items-center gap-2 bg-accent-50 px-4 py-3 text-left'
                      : 'flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-ink-50'
                  }
                  onClick={() => {
                    setSelected(m.name)
                    if (activeProject) navigatePath(paths.model(activeProject, m.name), true)
                  }}
                >
                  <Box className="h-4 w-4 text-ink-400" />
                  <span className="flex-1 truncate font-medium text-ink-900">{m.name}</span>
                  {m.stages?.prod ? (
                    <StatusBadge status="prod" />
                  ) : m.stages?.staging ? (
                    <StatusBadge status="staging" />
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
          }
          detail={
          <div className="rounded-2xl border border-ink-200 bg-white p-4 space-y-4">
            {!selected || !detail ? (
              <p className="text-sm text-ink-500">Select a model to manage stages.</p>
            ) : (
              <>
                <div>
                  <h2 className="text-base font-semibold text-ink-950">{detail.name}</h2>
                  {detail.description ? (
                    <p className="mt-1 text-sm text-ink-500">{detail.description}</p>
                  ) : null}
                </div>
                <div className="space-y-2">
                  {(['staging', 'prod', 'latest'] as const).map((stage) => {
                    const entry = stages[stage]
                    if (!entry && stage === 'latest') return null
                    return (
                      <div
                        key={stage}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-2"
                      >
                        <div>
                          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                            {stage}
                          </div>
                          {entry?.run_id ? (
                            <button
                              type="button"
                              className="font-mono text-[12px] text-accent-800 hover:underline"
                              onClick={() => openRun(entry.run_id!)}
                            >
                              {entry.run_id.slice(0, 12)}…
                            </button>
                          ) : (
                            <span className="text-[12px] text-ink-400">—</span>
                          )}
                        </div>
                        {stage === 'staging' && entry ? (
                          entry.run_id === stages.prod?.run_id ? (
                            <span className="text-[11px] text-ink-400">Already in prod</span>
                          ) : entry.run_id === detail.pending_prod?.run_id ? (
                            <span className="text-[11px] text-ink-400">Prod approval pending</span>
                          ) : (
                            <button
                              type="button"
                              className="btn-secondary"
                              disabled={busy}
                              onClick={() => void requestProd(detail.name)}
                            >
                              <Shield className="h-3.5 w-3.5" /> Request prod
                            </button>
                          )
                        ) : null}
                        {stage === 'prod' && detail.pending_prod?.run_id ? (
                          <button
                            type="button"
                            className="btn-primary"
                            disabled={busy}
                            onClick={() => void approveProd(detail.name)}
                            title={`Pending since ${detail.pending_prod.requested_at ?? 'unknown'}${detail.pending_prod.requested_by ? ` by ${detail.pending_prod.requested_by}` : ''}`}
                          >
                            <CheckCircle2 className="h-3.5 w-3.5" /> Approve prod
                          </button>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
                <div className="flex flex-wrap gap-2">
                  {primaryRunId ? (
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => openTrace({ runId: primaryRunId, project: activeProject || undefined })}
                    >
                      <GitBranch className="h-3.5 w-3.5" /> Open run Trace / Lineage
                    </button>
                  ) : null}
                  {activeProject ? (
                    <>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => openData({ mode: 'outputs', project: activeProject })}
                      >
                        Dataset pins
                      </button>
                      <button
                        type="button"
                        className="btn-quiet"
                        onClick={() => openProjects({ project: activeProject })}
                      >
                        Open Home
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() =>
                          navigatePath(
                            primaryRunId
                              ? `${paths.ship(activeProject)}?run_id=${encodeURIComponent(primaryRunId)}`
                              : paths.ship(activeProject),
                          )
                        }
                      >
                        Use in Ship
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="btn-quiet"
                      onClick={() => openProjects()}
                    >
                      Open a project for dataset pins
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
          }
        />
      )}
      </div>
    </ViewShell>
  )
}
