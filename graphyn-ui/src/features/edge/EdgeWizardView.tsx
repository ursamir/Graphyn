import React from 'react'
import {
  Archive,
  Check,
  ChevronRight,
  Cpu,
  Download,
  GitBranch,
  Play,
  RefreshCw,
  Workflow,
} from 'lucide-react'
import { apiFetch, apiJson, downloadOutputFile } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import type { GraphIR } from '../../types/graph'
import {
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'
import {
  EDGE_BACKENDS,
  EDGE_DEPLOY_TEMPLATE,
  EDGE_QUANTIZATIONS,
  EDGE_TARGETS,
  applyEdgeConfig,
  guessPackagePath,
  type EdgeBackend,
  type EdgeQuantization,
  type EdgeTarget,
} from './edgeDeployTemplate'
import { isTerminalFailure, isTerminalSuccess } from '../../lib/runStatus'

type WizardStep = 1 | 2 | 3 | 4

const STEP_LABELS: Record<WizardStep, string> = {
  1: 'Graph',
  2: 'Configure',
  3: 'Run',
  4: 'Download',
}

function cloneTemplate(): GraphIR {
  return structuredClone(EDGE_DEPLOY_TEMPLATE)
}

function parseEdgeHash(): { project?: string; version?: string; runId?: string } {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const qIdx = raw.indexOf('?')
  if (qIdx < 0) return {}
  const params = new URLSearchParams(raw.slice(qIdx + 1))
  return {
    project: (params.get('project') || '').trim() || undefined,
    version: (params.get('version') || '').trim() || undefined,
    runId: (params.get('run_id') || '').trim() || undefined,
  }
}

export default function EdgeWizardView() {
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)
  const openRun = useAppStore((s) => s.openRun)
  const openTrace = useAppStore((s) => s.openTrace)
  const openArtifacts = useAppStore((s) => s.openArtifacts)
  const openProjects = useAppStore((s) => s.openProjects)
  const setView = useAppStore((s) => s.setView)
  const pushToast = useAppStore((s) => s.pushToast)
  const setLastRunId = useAppStore((s) => s.setLastRunId)

  const initialEdge = React.useMemo(() => parseEdgeHash(), [])
  const [linkedProject, setLinkedProject] = React.useState(initialEdge.project ?? '')
  const [linkedVersion, setLinkedVersion] = React.useState(initialEdge.version ?? '')
  const [sourceRunId, setSourceRunId] = React.useState(initialEdge.runId ?? '')
  const [projectRuns, setProjectRuns] = React.useState<
    Array<{ run_id: string; status?: string; graph_name?: string }>
  >([])
  const [sourceArtifacts, setSourceArtifacts] = React.useState<
    Array<{ artifact_id?: string; artifact_type?: string; uri?: string; path?: string; metadata?: Record<string, unknown> }>
  >([])
  const [sourceArtifactId, setSourceArtifactId] = React.useState('')
  const activeProject = useAppStore((s) => s.activeProject)

  const [step, setStep] = React.useState<WizardStep>(1)
  const [graph, setGraph] = React.useState<GraphIR | null>(null)
  const [modelPath, setModelPath] = React.useState('workspace/artifacts/models/saved_model')
  const [labelsCsv, setLabelsCsv] = React.useState('yes, no, up, down, go, stop')
  const [backend, setBackend] = React.useState<EdgeBackend>('tflite')
  const [quantization, setQuantization] = React.useState<EdgeQuantization>('float32')
  const [target, setTarget] = React.useState<EdgeTarget>('edge')
  const [packageName, setPackageName] = React.useState(
    initialEdge.project ? `${initialEdge.project}_edge` : 'edge_model',
  )

  const [runId, setRunId] = React.useState<string | null>(null)
  const [runStatus, setRunStatus] = React.useState<string | null>(null)
  const [runError, setRunError] = React.useState<string | null>(null)
  const [running, setRunning] = React.useState(false)
  const [downloadPath, setDownloadPath] = React.useState<string | null>(null)
  const [downloading, setDownloading] = React.useState(false)
  const [modelPathMissing, setModelPathMissing] = React.useState(false)
  const [modelPathChecking, setModelPathChecking] = React.useState(false)
  const [promoteAlias, setPromoteAlias] = React.useState<'staging' | 'prod'>('staging')
  const [promoting, setPromoting] = React.useState(false)

  // Probe model path: 404 => missing; 400 "directory" / 200 / other jailed hit => present.
  React.useEffect(() => {
    let cancelled = false
    const path = modelPath.trim()
    if (!path) {
      setModelPathMissing(true)
      return
    }
    setModelPathChecking(true)
    const handle = window.setTimeout(() => {
      void (async () => {
        try {
          const res = await apiFetch('/outputs/file', { query: { path } })
          if (cancelled) return
          if (res.status === 404) {
            setModelPathMissing(true)
          } else if (res.status === 400) {
            const body = await res.json().catch(() => ({} as { detail?: string }))
            const detail = String((body as { detail?: string }).detail || '')
            // Directory is a valid SavedModel root — treat as present.
            setModelPathMissing(!/directory/i.test(detail))
          } else {
            setModelPathMissing(false)
          }
        } catch {
          if (!cancelled) setModelPathMissing(true)
        } finally {
          if (!cancelled) setModelPathChecking(false)
        }
      })()
    }, 350)
    return () => {
      cancelled = true
      window.clearTimeout(handle)
    }
  }, [modelPath])

  React.useEffect(() => {
    const apply = () => {
      const h = parseEdgeHash()
      if (h.project) setLinkedProject(h.project)
      if (h.version) setLinkedVersion(h.version)
      if (h.runId) setSourceRunId(h.runId)
      if (h.project) setPackageName((prev) => (prev === 'edge_model' ? `${h.project}_edge` : prev))
    }
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [])

  React.useEffect(() => {
    let cancelled = false
    const rid = sourceRunId.trim()
    if (!rid) {
      setSourceArtifacts([])
      return
    }
    void (async () => {
      try {
        const arts = await apiJson<
          Array<{ artifact_id?: string; artifact_type?: string; uri?: string; path?: string; metadata?: Record<string, unknown> }>
        >('/artifacts', { query: { run_id: rid } })
        if (!cancelled) setSourceArtifacts(Array.isArray(arts) ? arts : [])
      } catch {
        if (!cancelled) setSourceArtifacts([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sourceRunId])

  React.useEffect(() => {
    if (!linkedProject && activeProject) setLinkedProject(activeProject)
  }, [activeProject, linkedProject])

  React.useEffect(() => {
    let cancelled = false
    const project = linkedProject.trim()
    if (!project) {
      setProjectRuns([])
      return
    }
    void (async () => {
      try {
        const runs = await apiJson<Array<{ run_id: string; status?: string; graph_name?: string }>>(
          '/runs',
          { query: { limit: 20, offset: 0, project } },
        )
        if (!cancelled) setProjectRuns(Array.isArray(runs) ? runs : [])
      } catch {
        if (!cancelled) setProjectRuns([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [linkedProject])

  // Keep project/version/run_id in the hash across wizard steps so the chip survives navigation.
  React.useEffect(() => {
    if (!linkedProject && !linkedVersion && !sourceRunId) return
    const params = new URLSearchParams()
    if (linkedProject) params.set('project', linkedProject)
    if (linkedVersion) params.set('version', linkedVersion)
    if (sourceRunId.trim()) params.set('run_id', sourceRunId.trim())
    const next = `#/edge?${params.toString()}`
    if (window.location.hash !== next) {
      window.history.replaceState(null, '', next)
    }
  }, [linkedProject, linkedVersion, sourceRunId, step])

  // Wire linked dataset into path-like fields when still at defaults.
  React.useEffect(() => {
    if (!linkedProject) return
    setPackageName((prev) => (prev === 'edge_model' ? `${linkedProject}_edge` : prev))
    setModelPath((prev) =>
      prev === 'workspace/artifacts/models/saved_model'
        ? `workspace/artifacts/${linkedProject}/saved_model`
        : prev,
    )
  }, [linkedProject])

  const configuredGraph = React.useMemo(() => {
    const base = graph ?? EDGE_DEPLOY_TEMPLATE
    return applyEdgeConfig(base, {
      modelPath,
      labelsCsv,
      backend,
      quantization,
      target,
      packageName,
    })
  }, [graph, modelPath, labelsCsv, backend, quantization, target, packageName])

  const useEdgeTemplate = () => {
    if (!linkedProject.trim()) {
      pushToast('Select a project first — Edge packages must hang off a workspace', 'error')
      return
    }
    if (!sourceRunId.trim()) {
      pushToast('Pick a source run (train lineage) before loading the edge template', 'error')
      return
    }
    setGraph(cloneTemplate())
    setStep(2)
    pushToast('Loaded edge-deploy template (optimize → package)', 'success')
  }

  const openInBuilder = () => {
    loadGraphIntoBuilder(configuredGraph)
    pushToast('Opened edge graph in Editor', 'info')
  }

  const startRun = async () => {
    if (!linkedProject.trim() || !sourceRunId.trim()) {
      pushToast('Project + source run_id required for accountable edge packaging', 'error')
      setStep(1)
      return
    }
    setRunning(true)
    setRunError(null)
    setRunStatus('starting')
    setDownloadPath(null)
    try {
      const payload = {
        ...configuredGraph,
        metadata: {
          ...(configuredGraph.metadata || {}),
          project: linkedProject.trim(),
          name: configuredGraph.metadata?.name || packageName,
        },
        project: linkedProject.trim(),
        source_run_id: sourceRunId.trim(),
        ...(sourceArtifactId.trim() ? { source_artifact_id: sourceArtifactId.trim() } : {}),
      }
      const res = await apiJson<{ run_id: string }>('/pipelines/run-async', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setRunId(res.run_id)
      setLastRunId(res.run_id)
      setRunStatus('running')
      pushToast(`Edge run started: ${res.run_id.slice(0, 8)}…`, 'success')
      setStep(3)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setRunError(msg)
      setRunStatus('failed')
      pushToast(msg, 'error')
    } finally {
      setRunning(false)
    }
  }

  React.useEffect(() => {
    if (!runId) return
    let cancelled = false
    const tick = async () => {
      try {
        const st = await apiJson<{ status?: string; error?: string }>(`/runs/${runId}/status`)
        if (cancelled) return
        const status = (st.status || '').toLowerCase()
        setRunStatus(status || 'unknown')
        // Journal uses "completed"; distributed / UI may say "succeeded"
        if (isTerminalSuccess(status)) {
          const pkg = guessPackagePath(target, packageName)
          setDownloadPath(pkg)
          setStep(4)
          return
        }
        if (isTerminalFailure(status)) {
          setRunError(st.error || `Run ${status}`)
          return
        }
      } catch {
        /* keep polling */
      }
      if (!cancelled) window.setTimeout(tick, 2000)
    }
    void tick()
    return () => {
      cancelled = true
    }
  }, [runId, target, packageName])

  const doDownload = async () => {
    const path = downloadPath || guessPackagePath(target, packageName)
    setDownloading(true)
    try {
      await downloadOutputFile(path)
      pushToast(`Downloading ${path.split('/').pop()}`, 'success')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      pushToast(msg, 'error')
      setRunError(
        `${msg} — open Artifacts / Data if the package landed under a different name.`,
      )
    } finally {
      setDownloading(false)
    }
  }

  const doPromote = async () => {
    if (!runId) {
      pushToast('Run the edge package first, then promote', 'error')
      return
    }
    setPromoting(true)
    try {
      const res = await apiJson<{ alias?: string }>(`/runs/${runId}/promote`, {
        method: 'POST',
        body: JSON.stringify({ alias: promoteAlias }),
      })
      pushToast(`Edge package promoted to ${res?.alias || promoteAlias}`, 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setPromoting(false)
    }
  }

  const ready = Boolean(graph)

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <PageHeader
        title="Edge deploy"
        description="Optimize → package → download for on-device runtimes. Train/collect live in the Editor; this wizard starts from a project run for lineage. For multi-machine workers, use Workers (Mode B)."
        actions={
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-secondary" onClick={openInBuilder}>
              <Workflow className="h-3.5 w-3.5" /> Open in Editor
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => openArtifacts(runId ? { runId } : undefined)}
            >
              <Archive className="h-3.5 w-3.5" /> Artifacts
            </button>
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm">
        <span className="text-ink-500">Lineage</span>
        <input
          className="rounded-lg border border-ink-200 px-2 py-1 font-mono text-[12px]"
          placeholder="project"
          value={linkedProject}
          onChange={(e) => setLinkedProject(e.target.value.trim())}
          aria-label="Project"
        />
        <select
          className="max-w-[16rem] rounded-lg border border-ink-200 px-2 py-1 font-mono text-[12px]"
          value={sourceRunId}
          onChange={(e) => setSourceRunId(e.target.value)}
          aria-label="Source run"
        >
          <option value="">Select source run…</option>
          {projectRuns.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {r.run_id.slice(0, 8)}… {r.status || ''} {r.graph_name ? `· ${r.graph_name}` : ''}
            </option>
          ))}
        </select>
        <input
          className="min-w-[12rem] flex-1 rounded-lg border border-ink-200 px-2 py-1 font-mono text-[12px]"
          placeholder="or paste run_id"
          value={sourceRunId}
          onChange={(e) => setSourceRunId(e.target.value.trim())}
          aria-label="Source run id"
        />
        <button
          type="button"
          className="btn-secondary"
          onClick={() => {
            setView('templates')
            window.history.replaceState(null, '', '#/templates')
          }}
        >
          Train template
        </button>
        {sourceRunId ? (
          <button type="button" className="btn-secondary" onClick={() => openTrace({ runId: sourceRunId })}>
            <GitBranch className="h-3.5 w-3.5" /> Trace source
          </button>
        ) : null}
      </div>

      <ol className="flex flex-wrap gap-2">
        {([1, 2, 3, 4] as WizardStep[]).map((n) => {
          const active = step === n
          const done = step > n
          return (
            <li key={n}>
              <button
                type="button"
                onClick={() => setStep(n)}
                className={[
                  'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition',
                  active
                    ? 'border-accent-400 bg-white text-ink-950 shadow-sm'
                    : done
                      ? 'border-ink-200 bg-ink-50 text-ink-700'
                      : 'border-ink-100 bg-white/60 text-ink-400',
                ].join(' ')}
              >
                <span
                  className={[
                    'inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px]',
                    active || done ? 'bg-accent-500 text-ink-950' : 'bg-ink-100 text-ink-500',
                  ].join(' ')}
                >
                  {done ? <Check className="h-3 w-3" /> : n}
                </span>
                {STEP_LABELS[n]}
              </button>
            </li>
          )
        })}
      </ol>

      {step === 1 && (
        <div className="rounded-2xl border border-ink-200/80 bg-white p-5 shadow-sm space-y-4">
          <h3 className="text-sm font-semibold text-ink-900">Lineage, then graph</h3>
          <p className="text-sm text-ink-500">
            This wizard is <strong className="font-medium text-ink-700">optimize → package → download</strong>
            — not collect/train. Pick a project + source train run above, then load the edge template.
            Model path must resolve under the workspace (fail-closed; no mock success).
          </p>
          {!linkedProject.trim() || !sourceRunId.trim() ? (
            <EmptyState
              title="Project + source run required"
              description="Open a workspace, run a train pipeline from Templates/Editor, then return here with that run_id."
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  <button type="button" className="btn-primary" onClick={() => openProjects()}>
                    Projects
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => {
                      setView('templates')
                      window.history.replaceState(null, '', '#/templates')
                    }}
                  >
                    Train template
                  </button>
                </div>
              }
            />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                className="rounded-xl border border-ink-200 bg-ink-50/50 p-4 text-left hover:border-accent-400 hover:bg-white"
                onClick={useEdgeTemplate}
              >
                <div className="flex items-center gap-2 text-sm font-semibold text-ink-900">
                  <Cpu className="h-4 w-4 text-accent-700" /> Use edge template
                </div>
                <p className="mt-1 text-xs text-ink-500">
                  Loads <code className="font-mono">edge-deploy</code> for source run{' '}
                  <code className="font-mono">{sourceRunId.slice(0, 8)}…</code>
                </p>
              </button>
              <button
                type="button"
                className="rounded-xl border border-ink-200 bg-ink-50/50 p-4 text-left hover:border-accent-400 hover:bg-white"
                onClick={() => openTrace({ runId: sourceRunId })}
              >
                <div className="flex items-center gap-2 text-sm font-semibold text-ink-900">
                  <GitBranch className="h-4 w-4 text-accent-700" /> Inspect source lineage
                </div>
                <p className="mt-1 text-xs text-ink-500">Confirm the train run before packaging.</p>
              </button>
            </div>
          )}
          {ready && (
            <div className="flex justify-end">
              <button type="button" className="btn-primary" onClick={() => setStep(2)}>
                Configure <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      )}

      {step === 2 && (
        <div className="rounded-2xl border border-ink-200/80 bg-white p-5 shadow-sm space-y-4">
          <h3 className="text-sm font-semibold text-ink-900">Configure</h3>
          <p className="text-xs text-ink-500">
            Required: a Keras SavedModel directory or <code className="font-mono">.keras</code> file
            under <code className="font-mono">workspace/artifacts/…</code> (from trainer / Example
            06). INT8 needs <code className="font-mono">X_train_repr.npy</code> beside the model.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm sm:col-span-2">
              <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                Model path
              </span>
              {sourceArtifacts.length > 0 ? (
                <select
                  className="field-control mb-2 w-full font-mono text-xs"
                  value={sourceArtifactId}
                  onChange={(e) => {
                    const id = e.target.value
                    setSourceArtifactId(id)
                    const hit = sourceArtifacts.find((a) => String(a.artifact_id || '') === id)
                    if (!hit) return
                    const uri = String(hit.uri || hit.path || hit.metadata?.path || '').trim()
                    if (uri) setModelPath(uri)
                  }}
                  aria-label="Source artifact"
                >
                  <option value="">Pick artifact from source run…</option>
                  {sourceArtifacts.map((a) => {
                    const id = String(a.artifact_id || '')
                    const typ = String(a.artifact_type || 'artifact')
                    const uri = String(a.uri || a.path || '')
                    return (
                      <option key={id} value={id}>
                        {id.slice(0, 10)}… · {typ}
                        {uri ? ` · ${uri}` : ''}
                      </option>
                    )
                  })}
                </select>
              ) : (
                <p className="mb-2 text-[11px] text-ink-400">
                  No artifacts listed for this run yet — paste a workspace model path below (fail-closed if missing).
                </p>
              )}
              <input
                className="field-control mt-0 w-full font-mono text-xs"
                value={modelPath}
                onChange={(e) => setModelPath(e.target.value)}
                placeholder="workspace/artifacts/models/saved_model"
              />
              {linkedProject ? (
                <span className="mt-1 block text-[11px] text-ink-400">
                  Linked dataset <code className="font-mono">{linkedProject}</code>
                  {linkedVersion ? (
                    <>
                      {' '}
                      / <code className="font-mono">{linkedVersion}</code>
                    </>
                  ) : null}{' '}
                  — adjust path if your trainer wrote elsewhere.
                </span>
              ) : null}
              {!modelPathChecking && modelPathMissing ? (
                <div className="mt-2 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950">
                  <p className="font-medium">Model path not found on disk</p>
                  <p className="mt-1 text-amber-900/90">
                    <code className="font-mono">{modelPath || '(empty)'}</code> is missing. Train or
                    export a model first — do not invent a fake path. Use Templates/Builder to train,
                    or pick an existing artifact.
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button type="button" className="btn-secondary" onClick={() => setView('templates')}>
                      Templates
                    </button>
                    <button type="button" className="btn-secondary" onClick={() => setView('builder')}>
                      Builder
                    </button>
                    <button type="button" className="btn-secondary" onClick={() => openArtifacts({})}>
                      Artifacts
                    </button>
                  </div>
                </div>
              ) : null}
            </label>
            <label className="block text-sm sm:col-span-2">
              <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                Labels (comma-separated)
              </span>
              <input
                className="field-control mt-0 w-full text-xs"
                value={labelsCsv}
                onChange={(e) => setLabelsCsv(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                Optimizer backend
              </span>
              <select
                className="field-control mt-0 w-full text-xs"
                value={backend}
                onChange={(e) => setBackend(e.target.value as EdgeBackend)}
              >
                {EDGE_BACKENDS.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                Quantization
              </span>
              <select
                className="field-control mt-0 w-full text-xs"
                value={quantization}
                onChange={(e) => setQuantization(e.target.value as EdgeQuantization)}
              >
                {EDGE_QUANTIZATIONS.map((q) => (
                  <option key={q} value={q}>
                    {q}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                Package target
              </span>
              <select
                className="field-control mt-0 w-full text-xs"
                value={target}
                onChange={(e) => setTarget(e.target.value as EdgeTarget)}
              >
                {EDGE_TARGETS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                Package name
              </span>
              <input
                className="field-control mt-0 w-full font-mono text-xs"
                value={packageName}
                onChange={(e) => setPackageName(e.target.value)}
              />
            </label>
          </div>
          <div className="flex flex-wrap justify-between gap-2">
            <button type="button" className="btn-secondary" onClick={() => setStep(1)}>
              Back
            </button>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn-secondary" onClick={openInBuilder}>
                Open in Builder
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  if (!graph) setGraph(cloneTemplate())
                  setStep(3)
                }}
              >
                Next: Run <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="rounded-2xl border border-ink-200/80 bg-white p-5 shadow-sm space-y-4">
          <h3 className="text-sm font-semibold text-ink-900">Run</h3>
          <p className="text-sm text-ink-500">
            Starts <code className="font-mono">POST /pipelines/run-async</code> with the configured
            graph. Needs TensorFlow (or ONNX stack) in the plugin runtime for optimize.
          </p>
          {runError && <ErrorBanner message={runError} />}
          {runId && (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-ink-500">Run</span>
              <code className="font-mono text-xs text-ink-800">{runId}</code>
              {runStatus && <StatusBadge status={runStatus} />}
            </div>
          )}
          {running && <LoadingBlock label="Starting run…" />}
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-secondary" onClick={() => setStep(2)}>
              Back
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={running}
              onClick={() => void startRun()}
            >
              <Play className="h-3.5 w-3.5" /> {runId ? 'Re-run' : 'Run pipeline'}
            </button>
            {runId && (
              <>
                <button type="button" className="btn-secondary" onClick={() => openRun(runId)}>
                  <RefreshCw className="h-3.5 w-3.5" /> Open run
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => openTrace({ runId })}
                >
                  <GitBranch className="h-3.5 w-3.5" /> View lineage
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => openArtifacts({ runId })}
                >
                  <Archive className="h-3.5 w-3.5" /> View artifacts
                </button>
              </>
            )}
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setStep(4)}
              title="Skip to download if you already have a package"
            >
              Skip to download
            </button>
          </div>
          <p className="text-xs text-ink-400">
            If the run is heavy or deps are missing, open in Builder, fix the model path, then use
            Artifacts → Downloads when the package appears.
          </p>
        </div>
      )}

      {step === 4 && (
        <div className="rounded-2xl border border-ink-200/80 bg-white p-5 shadow-sm space-y-4">
          <h3 className="text-sm font-semibold text-ink-900">Download package</h3>
          <p className="text-sm text-ink-500">
            Expected package path from packager config (adjust if your run wrote a different
            name):
          </p>
          <label className="block text-sm">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
              Artifact path
            </span>
            <input
              className="field-control mt-0 w-full font-mono text-xs"
              value={downloadPath ?? guessPackagePath(target, packageName)}
              onChange={(e) => setDownloadPath(e.target.value)}
            />
          </label>
          {runError && <ErrorBanner message={runError} />}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={downloading}
              onClick={() => void doDownload()}
            >
              <Download className="h-3.5 w-3.5" /> {downloading ? 'Downloading…' : 'Download'}
            </button>
            {runId && (
              <div className="inline-flex flex-wrap items-center gap-2">
                <select
                  className="rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800"
                  value={promoteAlias}
                  onChange={(e) => setPromoteAlias(e.target.value as 'staging' | 'prod')}
                >
                  <option value="staging">staging</option>
                  <option value="prod">prod</option>
                </select>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={promoting}
                  onClick={() => void doPromote()}
                >
                  {promoting ? 'Promoting…' : 'Promote package'}
                </button>
              </div>
            )}
            <button
              type="button"
              className="btn-secondary"
              onClick={() => openArtifacts(runId ? { runId } : undefined)}
            >
              <Archive className="h-3.5 w-3.5" /> View artifacts
            </button>
            {runId && (
              <>
                <button type="button" className="btn-secondary" onClick={() => openRun(runId)}>
                  <RefreshCw className="h-3.5 w-3.5" /> Open run
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => openTrace({ runId })}
                >
                  <GitBranch className="h-3.5 w-3.5" /> View lineage
                </button>
              </>
            )}
            <button type="button" className="btn-secondary" onClick={openInBuilder}>
              <Workflow className="h-3.5 w-3.5" /> Open in Builder
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
