import React from 'react'
import { Boxes as EmptyBoxes } from 'lucide-react'
import { Box, CheckCircle2, GitBranch, RefreshCw, Shield } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { EmptyState, ErrorBanner, LoadingBlock, SegmentedTabs, StatusBadge } from '../../components/ui'
import { MasterDetail, ViewShell } from '../../layout'
import { paths } from '../../routes/paths'
import { navigatePath, parsePathname } from '../../routes/parsePath'
import { onPathChange } from '../../routes/nav'
import { unwrapList } from '../../api/unwrapList'
import { formatLocaleDateTime, formatRelativeTime, humanNodeLabel } from '../../lib/format'
import { runDisplayName } from '../../lib/runDisplay'
import {
  isShippableSource,
  normalizeRunModels,
  pickDefaultRunModel,
  runModelKindLabel,
  runModelSummary,
  runModelTitle,
  type RunModel,
} from '../edge/runModels'
import { apiErrorCode } from '../../api/errorCode'
import {
  MODEL_STAGE_HELP,
  REQUEST_PROD_HELP,
  disambiguatedModelTitles,
  findModelForRoute,
  modelDisplayName,
  modelPrimaryMetricText,
  preferredStageKey,
  stageFacts,
  stageRunId,
  type ModelStage,
} from './modelDisplay'

type ProjectRun = {
  run_id: string
  status?: string
  graph_name?: string
  display_name?: string
  created_at?: string
}

type ModelRow = {
  name: string
  display_name?: string
  description?: string
  stages?: Record<string, ModelStage>
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
  const [regSlugTouched, setRegSlugTouched] = React.useState(false)
  /** Models the chosen run produced (UX API) — register picks one by path. */
  const [regModels, setRegModels] = React.useState<RunModel[]>([])
  const [regModelPath, setRegModelPath] = React.useState('')
  const [regNameTouched, setRegNameTouched] = React.useState(false)
  const [scopeMode, setScopeMode] = React.useState<'workspace' | 'all'>(
    () => (useAppStore.getState().activeProject ? 'workspace' : 'all'),
  )
  const [projectRunIds, setProjectRunIds] = React.useState<Set<string>>(() => new Set())
  const [projectRuns, setProjectRuns] = React.useState<ProjectRun[]>([])
  /** Models per source run (GET /runs/{id}/models) — path labels for stage cards. */
  const [stageRunModels, setStageRunModels] = React.useState<Record<string, RunModel[]>>({})
  const [projectRunsLoaded, setProjectRunsLoaded] = React.useState(false)
  /** `/workspaces/<W>/models/<name>` param waiting for the list to load, then selected. */
  const [routeModel, setRouteModel] = React.useState<string | null>(() => {
    const p = parsePathname(window.location.pathname, window.location.search)
    return p.view === 'models' ? p.modelName ?? null : null
  })
  /** Selected row to scroll into view once it is rendered in the master list. */
  const [revealModel, setRevealModel] = React.useState<string | null>(null)
  const listRef = React.useRef<HTMLUListElement | null>(null)

  // Back / forward (and in-app links) between model URLs.
  React.useEffect(
    () =>
      onPathChange(() => {
        const p = parsePathname(window.location.pathname, window.location.search)
        if (p.view === 'models' && p.modelName) setRouteModel(p.modelName)
      }),
    [],
  )


  React.useEffect(() => {
    setScopeMode(activeProject ? 'workspace' : 'all')
  }, [activeProject])

  React.useEffect(() => {
    let cancelled = false
    setProjectRunsLoaded(false)
    if (!activeProject) {
      setProjectRunIds(new Set())
      setProjectRuns([])
      setProjectRunsLoaded(true)
      return
    }
    void (async () => {
      try {
        const list = unwrapList<ProjectRun>(
          await apiJson('/runs', { query: { project: activeProject, limit: 100, offset: 0 } }),
        ).filter((r) => r && typeof r.run_id === 'string')
        if (cancelled) return
        setProjectRuns(list)
        setProjectRunIds(new Set(list.map((r) => r.run_id).filter(Boolean)))
        setProjectRunsLoaded(true)
      } catch {
        if (!cancelled) {
          setProjectRuns([])
          setProjectRunIds(new Set())
          setProjectRunsLoaded(true)
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

  // Path labels / kinds for the stages' source runs (new API; silently absent on old).
  React.useEffect(() => {
    const ids = new Set<string>()
    for (const st of Object.values(detail?.stages || {})) {
      const id = stageRunId(st)
      if (id) ids.add(id)
    }
    const missing = [...ids].filter((id) => !(id in stageRunModels))
    if (missing.length === 0) return
    let cancelled = false
    void Promise.all(
      missing.map(async (id) => {
        try {
          return [id, normalizeRunModels(await apiJson(`/runs/${encodeURIComponent(id)}/models`))] as const
        } catch {
          return [id, [] as RunModel[]] as const
        }
      }),
    ).then((pairs) => {
      if (cancelled) return
      setStageRunModels((prev) => {
        const next = { ...prev }
        for (const [id, models] of pairs) next[id] = models
        return next
      })
    })
    return () => {
      cancelled = true
    }
  }, [detail, stageRunModels])

  const runsById = React.useMemo(() => new Map(projectRuns.map((r) => [r.run_id, r])), [projectRuns])
  const runName = (id: string, st?: ModelStage) =>
    st?.source_run_display_name || runDisplayName(runsById.get(id) ?? { run_id: id })
  const stageModelRow = (st: ModelStage | undefined): RunModel | null => {
    const id = stageRunId(st)
    const path = st?.artifact_path || st?.path
    if (!id || !path) return null
    return (stageRunModels[id] || []).find((m) => m.path === path) ?? null
  }

  const requestProd = async (name: string) => {
    setBusy(true)
    try {
      await apiJson(`/models/${encodeURIComponent(name)}/request-prod`, {
        method: 'POST',
        body: JSON.stringify({}),
      })
      pushToast(`Asked an approver to move ${name} to production`, 'success')
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
      pushToast(`${name} is now the production model`, 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  // Run picked in the register form → list its model files (new API; empty on old).
  React.useEffect(() => {
    const rid = regRunId.trim()
    setRegModels([])
    setRegModelPath('')
    if (!rid || !registerOpen) return
    let cancelled = false
    const handle = window.setTimeout(() => {
      apiJson(`/runs/${encodeURIComponent(rid)}/models`)
        .then((raw) => {
          if (cancelled) return
          const models = normalizeRunModels(raw)
          setRegModels(models)
          const pick = pickDefaultRunModel(models)
          if (pick) {
            setRegModelPath(pick.path)
            if (!regNameTouched && pick.suggested_name) setRegName(pick.suggested_name)
          }
        })
        .catch(() => {
          /* old API — fall back to slug */
        })
    }, 250)
    return () => {
      cancelled = true
      window.clearTimeout(handle)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [regRunId, registerOpen])

  const register = async (allowUntrained = false) => {
    const name = regName.trim()
    const run_id = regRunId.trim()
    const slug = regSlug.trim() || 'model'
    if (!name || !run_id) {
      pushToast('Name and run are required', 'error')
      return
    }
    setBusy(true)
    try {
      await apiJson('/models', {
        method: 'POST',
        body: JSON.stringify({
          name,
          run_id,
          stage: 'staging',
          // With a picked model file the server derives the slug; keep an
          // explicit one only when the user typed it (old APIs need slug).
          ...(regModelPath ? { model_path: regModelPath } : { slug }),
          ...(regModelPath && regSlugTouched ? { slug } : {}),
          ...(allowUntrained ? { allow_untrained: true } : {}),
        }),
      })
      pushToast(`Registered ${name} in staging`, 'success')
      setRegisterOpen(false)
      setRegName('')
      setRegRunId('')
      setRegNameTouched(false)
      setRegSlugTouched(false)
      await load()
      setSelected(name)
      if (activeProject) navigatePath(paths.model(activeProject, name), true)
    } catch (err) {
      const code = apiErrorCode(err)
      if (code === 'compiled_untrained' && !allowUntrained) {
        setBusy(false)
        if (
          window.confirm(
            'This model file was saved before training (it has random weights). Register it anyway?',
          )
        ) {
          await register(true)
        }
        return
      }
      pushToast(
        code === 'model_not_in_run'
          ? 'That model file does not belong to the selected run — pick one from the list.'
          : err instanceof Error
            ? err.message
            : String(err),
        'error',
      )
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
  /** List titles; colliding names ("Edge Optimizer model" ×2) get run id + date. */
  const listTitles = disambiguatedModelTitles(filteredRows)

  // Deep link /models/<name>: select that model once the registry list loads.
  React.useEffect(() => {
    if (!routeModel || loading) return
    const hit = findModelForRoute(rows, routeModel)
    setRouteModel(null)
    if (!hit) {
      if (rows.length > 0) pushToast(`Model "${routeModel}" is not in the registry`, 'error')
      return
    }
    setSelected(hit.name)
    setRevealModel(hit.name)
  }, [routeModel, rows, loading, pushToast])

  // The deep-linked model lives outside this workspace's runs → show All workspaces.
  const revealHidden = Boolean(revealModel) && !filteredRows.some((r) => r.name === revealModel)
  React.useEffect(() => {
    if (revealHidden && projectRunsLoaded && scopeMode === 'workspace') setScopeMode('all')
  }, [revealHidden, projectRunsLoaded, scopeMode])

  // Scroll the selected row into view once it is rendered.
  React.useEffect(() => {
    if (!revealModel || revealHidden) return
    const el = listRef.current?.querySelector<HTMLElement>(`[data-model-name="${CSS.escape(revealModel)}"]`)
    if (!el) return
    el.scrollIntoView({ block: 'nearest' })
    setRevealModel(null)
  }, [revealModel, revealHidden, rows, scopeMode, loading])

  const openWorkspaceRuns = () => {
    if (!activeProject) return
    setView('runs')
    navigatePath(paths.runs(activeProject))
  }

  const stages = detail?.stages || {}
  /* Ship the staging candidate first (what the user is evaluating), else prod / latest. */
  const primaryStageKey = stages.staging ? 'staging' : stages.prod ? 'prod' : stages.latest ? 'latest' : null
  const primaryRunId = (primaryStageKey ? stageRunId(stages[primaryStageKey]) : null) || undefined

  return (
    <ViewShell
      title="Models"
      description="Trained models saved from runs. Each model has stages: staging (candidate) and production (approved)."
      toolbar={
        activeProject ? (
          <SegmentedTabs
            aria-label="Model scope"
            value={scopeMode}
            options={[
              { id: 'workspace', label: 'This workspace' },
              { id: 'all', label: 'All workspaces' },
            ]}
            onChange={setScopeMode}
          />
        ) : undefined
      }
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
        <p className="text-[12px] text-ink-600">
          {scopeMode === 'workspace' ? (
            <>
              <span className="font-medium text-ink-800">Models for this workspace</span>
              {' '}
              — models trained by runs in this workspace.
            </>
          ) : (
            <>
              Showing <span className="font-medium text-ink-800">every registered model</span>, from all
              workspaces.
            </>
          )}
        </p>
      ) : null}
      {registerOpen && (
        <div className="rounded-2xl border border-ink-200 bg-white p-4 space-y-3 shadow-sm">
          <h3 className="text-sm font-semibold text-ink-950">Register from a run</h3>
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="text-[12px] text-ink-600">
              Name
              <input
                className="field-control mt-1"
                value={regName}
                onChange={(e) => {
                  setRegNameTouched(true)
                  setRegName(e.target.value)
                }}
              />
            </label>
            <label className="text-[12px] text-ink-600">
              Training run
              {activeProject && projectRuns.length > 0 ? (
                <select
                  className="field-control mt-1 font-mono"
                  value={regRunId}
                  onChange={(e) => setRegRunId(e.target.value)}
                >
                  <option value="">Select a recent run…</option>
                  {projectRuns.map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {runDisplayName(r)} · {r.status || ''} · {r.run_id.slice(0, 8)}
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
            <label
              className="text-[12px] text-ink-600"
              title="Name of the saved artifact inside the run (the folder under workspace/artifacts/)"
            >
              Saved artifact name
              <input
                className="field-control mt-1"
                value={regSlug}
                onChange={(e) => {
                  setRegSlugTouched(true)
                  setRegSlug(e.target.value)
                }}
              />
            </label>
          </div>
          {regModels.length > 0 ? (
            <label className="block text-[12px] text-ink-600">
              Model file
              <select
                className="field-control mt-1"
                value={regModelPath}
                onChange={(e) => setRegModelPath(e.target.value)}
              >
                {regModels.map((m) => (
                  <option key={m.path} value={m.path} disabled={!isShippableSource(m) && m.kind === 'compiled_untrained'}>
                    {runModelTitle(m)} — {runModelSummary(m)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <p className="text-[11px] text-ink-500">
            New models start in <span className="font-medium">staging</span> (candidate). Ask for production
            approval once it performs well.
          </p>
          <button type="button" className="btn-primary" disabled={busy} onClick={() => void register(false)}>
            Register to staging
          </button>
        </div>
      )}

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {loading ? (
        <LoadingBlock label="Loading models…" />
      ) : filteredRows.length === 0 ? (
        <EmptyState icon={EmptyBoxes}
          title={activeProject && scopeMode === 'workspace' ? 'No models for this workspace' : 'No registered models'}
          description={
            activeProject && scopeMode === 'workspace'
              ? 'Run a training pipeline, then register its model — or look at all workspaces.'
              : 'Train a model, then register it from a run to see it here.'
          }
          action={
            activeProject && scopeMode === 'workspace' ? (
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn-primary" onClick={openWorkspaceRuns}>
                  Open Runs
                </button>
                <button type="button" className="btn-secondary" onClick={() => setScopeMode('all')}>
                  All workspaces
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
          <ul
            ref={listRef}
            className="divide-y divide-ink-100 overflow-hidden rounded-lg border border-ink-200 bg-white"
          >
            {filteredRows.map((m) => (
              <li key={m.name} data-model-name={m.name}>
                <button
                  type="button"
                  className={
                    selected === m.name
                      ? 'ide-row is-active w-full !px-3 !py-2.5'
                      : 'ide-row w-full !px-3 !py-2.5'
                  }
                  onClick={() => {
                    setSelected(m.name)
                    if (activeProject) navigatePath(paths.model(activeProject, m.name), true)
                  }}
                >
                  <Box className="h-4 w-4 shrink-0 text-ink-400" />
                  <span className="min-w-0 flex-1" title={m.name}>
                    <span className="block truncate font-medium text-ink-900">{listTitles.get(m.name) ?? modelDisplayName(m)}</span>
                    {(() => {
                      const key = preferredStageKey(m.stages)
                      const metric = key ? modelPrimaryMetricText(m.stages?.[key]) : null
                      return metric ? (
                        <span className="block truncate text-[11px] font-normal text-ink-500">{metric}</span>
                      ) : null
                    })()}
                  </span>
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
              <EmptyState compact title="Select a model" description="Choose a model on the left to see its accuracy, files and stages." />
            ) : (
              <>
                <div>
                  <h2 className="text-base font-semibold text-ink-950" title={detail.name}>
                    {modelDisplayName(detail)}
                  </h2>
                  {modelDisplayName(detail) !== detail.name ? (
                    <p className="mt-0.5 text-[11px] text-ink-400" title="Registry name">
                      {detail.name}
                    </p>
                  ) : null}
                  {detail.description ? (
                    <p className="mt-1 text-sm text-ink-500">{detail.description}</p>
                  ) : null}
                </div>
                <div className="space-y-2">
                  {(['staging', 'prod', 'latest'] as const).map((stage) => {
                    const entry = stages[stage]
                    if (!entry && stage === 'latest') return null
                    const facts = stageFacts(entry)
                    const srcRun = stageRunId(entry)
                    const runModel = stageModelRow(entry)
                    const pathLabel = entry?.path_label || runModel?.path_label
                    const created = entry?.created_at || runModel?.created_at
                    const nodeId = entry?.node_id || runModel?.node_id
                    const nodeName = nodeId ? humanNodeLabel(runModel?.node_type || nodeId) : null
                    const kind = entry?.artifact_kind || runModel?.kind
                    return (
                      <div
                        key={stage}
                        className="space-y-2 rounded-xl border border-ink-100 bg-ink-50/80 px-3 py-2"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div
                            className="text-[11px] font-semibold uppercase tracking-wide text-ink-400"
                            title={MODEL_STAGE_HELP[stage]}
                          >
                            Model stage · {stage === 'prod' ? 'production' : stage}
                          </div>
                          {stage === 'staging' && entry ? (
                            entry.run_id === stages.prod?.run_id ? (
                              <span className="text-[11px] text-ink-400">Same model is in production</span>
                            ) : entry.run_id === detail.pending_prod?.run_id ? (
                              <span className="text-[11px] text-ink-500">Waiting for an approver</span>
                            ) : (
                              <button
                                type="button"
                                className="btn-secondary"
                                disabled={busy}
                                title={REQUEST_PROD_HELP}
                                onClick={() => void requestProd(detail.name)}
                              >
                                <Shield className="h-3.5 w-3.5" /> Request production
                              </button>
                            )
                          ) : null}
                          {stage === 'prod' && detail.pending_prod?.run_id ? (
                            <button
                              type="button"
                              className="btn-primary"
                              disabled={busy}
                              onClick={() => void approveProd(detail.name)}
                              title={`Requested ${detail.pending_prod.requested_at ? formatLocaleDateTime(detail.pending_prod.requested_at) : ''}${detail.pending_prod.requested_by ? ` by ${detail.pending_prod.requested_by}` : ''}`}
                            >
                              <CheckCircle2 className="h-3.5 w-3.5" /> Approve production
                            </button>
                          ) : null}
                        </div>
                        {!entry ? (
                          <p className="text-[12px] text-ink-400">
                            {stage === 'prod' ? 'No production model yet.' : 'Empty.'}
                          </p>
                        ) : (
                          <>
                            {facts.length > 0 ? (
                              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] sm:grid-cols-4">
                                {facts.map((f) => (
                                  <div key={f.label} className="min-w-0" title={f.title}>
                                    <dt className="text-[10px] uppercase tracking-wide text-ink-400">{f.label}</dt>
                                    <dd className="truncate font-medium text-ink-800">{f.value}</dd>
                                  </div>
                                ))}
                              </dl>
                            ) : null}
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-600">
                              {srcRun ? (
                                <span>
                                  From run{' '}
                                  <button
                                    type="button"
                                    className="font-medium text-accent-800 hover:underline"
                                    title={`Run ${srcRun}`}
                                    onClick={() => openRun(srcRun)}
                                  >
                                    {runName(srcRun, entry)}
                                  </button>
                                </span>
                              ) : null}
                              {pathLabel ? (
                                <span title="Which branch of the pipeline produced this model">
                                  Path: <span className="font-medium text-ink-800">{pathLabel}</span>
                                </span>
                              ) : null}
                              {nodeName ? (
                                <span title={nodeId}>
                                  {runModelKindLabel(kind)} by {nodeName}
                                </span>
                              ) : null}
                              {created ? (
                                <span title={formatLocaleDateTime(created)}>Created {formatRelativeTime(created)}</span>
                              ) : null}
                            </div>
                            {entry.exists === false ? (
                              <p className="rounded-lg border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-900">
                                The model file for this stage is missing on disk — re-run training or register
                                another run.
                              </p>
                            ) : null}
                          </>
                        )}
                      </div>
                    )
                  })}
                  {stages.staging && !stages.prod && !detail.pending_prod?.run_id ? (
                    <p className="text-[11px] leading-relaxed text-ink-500">{REQUEST_PROD_HELP}</p>
                  ) : null}
                  <p className="text-[11px] text-ink-400">
                    Model stages (staging / production) are separate from pipeline versions on Home — a
                    pipeline version is the saved graph, a model stage is the trained file it produced.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {primaryRunId ? (
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => openTrace({ runId: primaryRunId, project: activeProject || undefined })}
                    >
                      <GitBranch className="h-3.5 w-3.5" /> How it was made
                    </button>
                  ) : null}
                  {activeProject ? (
                    <>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => openData({ mode: 'outputs', project: activeProject })}
                      >
                        Datasets
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
                        title="Package this model for devices"
                        onClick={() => {
                          const q = new URLSearchParams()
                          if (primaryRunId) q.set('run_id', primaryRunId)
                          q.set('model', detail.name)
                          if (primaryStageKey) q.set('stage', primaryStageKey)
                          navigatePath(`${paths.ship(activeProject)}?${q.toString()}`)
                        }}
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
                      Open a workspace
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
