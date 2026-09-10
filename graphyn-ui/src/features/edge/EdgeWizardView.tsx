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

function parseEdgeHash(): { project?: string; version?: string } {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const qIdx = raw.indexOf('?')
  if (qIdx < 0) return {}
  const params = new URLSearchParams(raw.slice(qIdx + 1))
  return {
    project: (params.get('project') || '').trim() || undefined,
    version: (params.get('version') || '').trim() || undefined,
  }
}

export default function EdgeWizardView() {
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)
  const openRun = useAppStore((s) => s.openRun)
  const openTrace = useAppStore((s) => s.openTrace)
  const openArtifacts = useAppStore((s) => s.openArtifacts)
  const openData = useAppStore((s) => s.openData)
  const openProjects = useAppStore((s) => s.openProjects)
  const setView = useAppStore((s) => s.setView)
  const pushToast = useAppStore((s) => s.pushToast)
  const setLastRunId = useAppStore((s) => s.setLastRunId)

  const initialEdge = React.useMemo(() => parseEdgeHash(), [])
  const [linkedProject, setLinkedProject] = React.useState(initialEdge.project ?? '')
  const [linkedVersion, setLinkedVersion] = React.useState(initialEdge.version ?? '')

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
      if (h.project) setPackageName((prev) => (prev === 'edge_model' ? `${h.project}_edge` : prev))
    }
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [])

  // Keep project/version in the hash across wizard steps so the chip survives navigation.
  React.useEffect(() => {
    if (!linkedProject && !linkedVersion) return
    const params = new URLSearchParams()
    if (linkedProject) params.set('project', linkedProject)
    if (linkedVersion) params.set('version', linkedVersion)
    const next = `#/edge?${params.toString()}`
    if (window.location.hash !== next) {
      window.history.replaceState(null, '', next)
    }
  }, [linkedProject, linkedVersion, step])

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
    setGraph(cloneTemplate())
    setStep(2)
    pushToast('Loaded edge-deploy template', 'success')
  }

  const openInBuilder = () => {
    loadGraphIntoBuilder(configuredGraph)
    pushToast('Opened edge graph in Builder', 'info')
  }

  const startRun = async () => {
    setRunning(true)
    setRunError(null)
    setRunStatus('starting')
    setDownloadPath(null)
    try {
      const res = await apiJson<{ run_id: string }>('/pipelines/run-async', {
        method: 'POST',
        body: JSON.stringify(configuredGraph),
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
        if (status === 'completed' || status === 'success' || status === 'done') {
          const pkg = guessPackagePath(target, packageName)
          setDownloadPath(pkg)
          setStep(4)
          return
        }
        if (status === 'failed' || status === 'cancelled' || status === 'error') {
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

  const ready = Boolean(graph)

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <PageHeader
        title="Edge deploy"
        description="Train elsewhere → optimize → package → download for on-device runtimes. For multi-machine pipeline workers, use Workers (Mode B)."
        actions={
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-secondary" onClick={openInBuilder}>
              <Workflow className="h-3.5 w-3.5" /> Open in Builder
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

      {(linkedProject || linkedVersion) && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm">
          <span className="text-ink-500">Dataset</span>
          <span className="rounded-full bg-accent-50 px-2.5 py-0.5 font-mono text-[12px] text-accent-900">
            {linkedProject || '—'}
            {linkedVersion ? ` / ${linkedVersion}` : ''}
          </span>
          <button
            type="button"
            className="btn-secondary"
            onClick={() =>
              openData({
                mode: 'outputs',
                project: linkedProject || undefined,
                version: linkedVersion || undefined,
              })
            }
          >
            Open Data
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => openProjects({ project: linkedProject || undefined })}
          >
            Open Projects
          </button>
          <span className="text-xs text-ink-400">
            Edge packages models; dataset project is linked for context.
          </span>
        </div>
      )}

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
          <h3 className="text-sm font-semibold text-ink-900">Choose a graph</h3>
          <p className="text-sm text-ink-500">
            Start from the Edge deploy template (model path → optimize → package), or open an
            existing graph in Builder and return here after configuring.
          </p>
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
                Loads <code className="font-mono">edge-deploy</code> with workspace/artifacts
                outputs.
              </p>
            </button>
            <button
              type="button"
              className="rounded-xl border border-ink-200 bg-ink-50/50 p-4 text-left hover:border-accent-400 hover:bg-white"
              onClick={() => {
                loadGraphIntoBuilder(cloneTemplate())
                pushToast('Template opened in Builder — edit, then Run from there or return to Edge', 'info')
              }}
            >
              <div className="flex items-center gap-2 text-sm font-semibold text-ink-900">
                <Workflow className="h-4 w-4" /> Create in Builder
              </div>
              <p className="mt-1 text-xs text-ink-500">
                Opens the same starter on the canvas for full editing.
              </p>
            </button>
          </div>
          {!ready && (
            <EmptyState
              title="No graph selected"
              description="Observe→Deploy: pick the edge template, configure, run, then download — or open Templates / Builder and come back with a packaged model."
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  <button type="button" className="btn-primary" onClick={useEdgeTemplate}>
                    Use edge template
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => openData({ mode: 'outputs' })}
                  >
                    Open Data
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => openProjects()}
                  >
                    Open Projects
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => {
                      setView('templates')
                      window.history.replaceState(null, '', '#/templates')
                    }}
                  >
                    Browse Templates
                  </button>
                </div>
              }
            />
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
