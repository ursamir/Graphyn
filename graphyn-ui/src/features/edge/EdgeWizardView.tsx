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
import { FieldSelect } from '../../components/FieldSelect'
import {
  EDGE_BACKENDS,
  EDGE_DEPLOY_TEMPLATE,
  EDGE_QUANTIZATIONS,
  EDGE_TARGETS,
  applyEdgeConfig,
  guessPackagePath,
  isModelLikeArtifact,
  pickExistingModelPath,
  preferSavedModelPath,
  resolveModelPathCandidates,
  type EdgeBackend,
  type EdgeQuantization,
  type EdgeTarget,
} from './edgeDeployTemplate'
import { isTerminalFailure, isTerminalSuccess } from '../../lib/runStatus'
import DevicesView from '../ship/DevicesView'
import { paths } from '../../routes/paths'
import { goView, onPathChange, readSearchParams, replacePathSearch } from '../../routes/nav'

type WizardStep = 1 | 2 | 3 | 4
type ShipTab = 'package' | 'devices'

const STEP_LABELS: Record<WizardStep, string> = {
  1: 'Graph',
  2: 'Configure',
  3: 'Package run',
  4: 'Download',
}

type RegistryModel = {
  name: string
  stages?: Record<string, { run_id?: string; slug?: string; path?: string }>
}

function cloneTemplate(): GraphIR {
  return structuredClone(EDGE_DEPLOY_TEMPLATE)
}

function parseEdgeLocation(): { project?: string; version?: string; runId?: string; tab?: ShipTab } {
  const params = readSearchParams()
  const pathname = window.location.pathname
  const parts = pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  const tabParam = (params.get('tab') || '').trim().toLowerCase()
  const devicesPath =
    pathname.includes('/devices') ||
    (parts[0] === 'workspaces' && parts[2] === 'ship' && parts[3] === 'devices') ||
    tabParam === 'devices'
  let projectFromPath: string | undefined
  if (parts[0] === 'workspaces' && parts[1] && parts[2] === 'ship') {
    projectFromPath = decodeURIComponent(parts[1])
  }
  return {
    project: (params.get('project') || '').trim() || projectFromPath || undefined,
    version: (params.get('version') || '').trim() || undefined,
    runId: (params.get('run_id') || '').trim() || undefined,
    tab: devicesPath ? 'devices' : 'package',
  }
}

function pickChecksum(data: unknown): string | null {
  if (!data || typeof data !== 'object') return null
  const o = data as Record<string, unknown>
  for (const k of ['checksum', 'sha256', 'hash', 'content_hash', 'digest']) {
    const v = o[k]
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  const meta = o.metadata
  if (meta && typeof meta === 'object' && !Array.isArray(meta)) {
    return pickChecksum(meta)
  }
  return null
}

export default function EdgeWizardView() {
  const loadGraphIntoBuilder = useAppStore((s) => s.loadGraphIntoBuilder)
  const openRun = useAppStore((s) => s.openRun)
  const openTrace = useAppStore((s) => s.openTrace)
  const openArtifacts = useAppStore((s) => s.openArtifacts)
  const openProjects = useAppStore((s) => s.openProjects)
  const pushToast = useAppStore((s) => s.pushToast)
  const setLastRunId = useAppStore((s) => s.setLastRunId)
  const activeProject = useAppStore((s) => s.activeProject)

  const initialEdge = React.useMemo(() => parseEdgeLocation(), [])
  const [shipTab, setShipTab] = React.useState<ShipTab>(initialEdge.tab ?? 'package')
  const [linkedProject, setLinkedProject] = React.useState(initialEdge.project ?? '')
  const [linkedVersion, setLinkedVersion] = React.useState(initialEdge.version ?? '')
  const [sourceRunId, setSourceRunId] = React.useState(initialEdge.runId ?? '')
  const [projectRuns, setProjectRuns] = React.useState<
    Array<{ run_id: string; status?: string; graph_name?: string }>
  >([])
  const [sourceArtifacts, setSourceArtifacts] = React.useState<
    Array<{
      artifact_id?: string
      artifact_type?: string
      uri?: string
      path?: string
      data_path?: string
      metadata?: Record<string, unknown>
    }>
  >([])
  const [sourceArtifactId, setSourceArtifactId] = React.useState('')
  const [registryModels, setRegistryModels] = React.useState<RegistryModel[]>([])
  const [pickedModel, setPickedModel] = React.useState('')

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
  const [packageExists, setPackageExists] = React.useState(false)
  const [packageChecking, setPackageChecking] = React.useState(false)
  const [promoteAlias, setPromoteAlias] = React.useState<'staging' | 'prod'>('staging')
  const [promoting, setPromoting] = React.useState(false)
  const [packageChecksum, setPackageChecksum] = React.useState<string | null>(null)

  const resolvedPackagePath = downloadPath || guessPackagePath(target, packageName)
  const runFailed = Boolean(runId && runStatus && isTerminalFailure(runStatus))

  React.useEffect(() => {
    void apiJson<{ models?: RegistryModel[] }>('/models')
      .then((res) => setRegistryModels(Array.isArray(res?.models) ? res.models : []))
      .catch(() => setRegistryModels([]))
  }, [])

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

  // Probe package path for skip-to-download / header Artifacts gating.
  React.useEffect(() => {
    let cancelled = false
    const path = resolvedPackagePath.trim()
    if (!path) {
      setPackageExists(false)
      return
    }
    setPackageChecking(true)
    const handle = window.setTimeout(() => {
      void (async () => {
        try {
          const res = await apiFetch('/outputs/file', { query: { path } })
          if (cancelled) return
          if (res.status === 404) {
            setPackageExists(false)
          } else if (res.status === 400) {
            const body = await res.json().catch(() => ({} as { detail?: string }))
            const detail = String((body as { detail?: string }).detail || '')
            setPackageExists(/directory/i.test(detail))
          } else {
            setPackageExists(true)
          }
        } catch {
          if (!cancelled) setPackageExists(false)
        } finally {
          if (!cancelled) setPackageChecking(false)
        }
      })()
    }, 350)
    return () => {
      cancelled = true
      window.clearTimeout(handle)
    }
  }, [resolvedPackagePath, runStatus])

  React.useEffect(() => {
    const apply = () => {
      const h = parseEdgeLocation()
      if (h.tab) setShipTab(h.tab)
      if (h.project) setLinkedProject(h.project)
      if (h.version) setLinkedVersion(h.version)
      if (h.runId) setSourceRunId(h.runId)
      if (h.project) setPackageName((prev) => (prev === 'edge_model' ? `${h.project}_edge` : prev))
    }
    return onPathChange(apply)
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
          Array<{
            artifact_id?: string
            artifact_type?: string
            uri?: string
            path?: string
            metadata?: Record<string, unknown>
          }>
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

  // Prefer a recent successful workspace run as the Ship source (don't leave blank / orphan to global).
  React.useEffect(() => {
    if (sourceRunId.trim()) return
    const ok = projectRuns.find((r) => isTerminalSuccess(r.status || ''))
    if (ok?.run_id) setSourceRunId(ok.run_id)
  }, [projectRuns, sourceRunId])

  // Keep project/version/run_id on path search; devices tab via pathname segment.
  React.useEffect(() => {
    const W = linkedProject.trim() || activeProject || ''
    const base = W
      ? shipTab === 'devices'
        ? paths.shipDevices(W)
        : paths.ship(W)
      : shipTab === 'devices'
        ? paths.deployShipDevices()
        : paths.deployShip()
    replacePathSearch(
      {
        project: linkedProject.trim() || undefined,
        version: linkedVersion.trim() || undefined,
        run_id: sourceRunId.trim() || undefined,
      },
      base,
    )
  }, [linkedProject, linkedVersion, sourceRunId, step, shipTab, activeProject])

  // Package name only — never invent model path from project name (project ≠ slug).
  React.useEffect(() => {
    if (!linkedProject) return
    setPackageName((prev) => (prev === 'edge_model' ? `${linkedProject}_edge` : prev))
  }, [linkedProject])

  const probeFetch = React.useCallback(async (path: string) => {
    return apiFetch('/outputs/file', { query: { path } })
  }, [])

  const resolveAndSetModelPath = React.useCallback(
    async (input: {
      slug?: string | null
      runId?: string | null
      stage?: string | null
      stagePath?: string | null
      artifactUri?: string | null
    }) => {
      const candidates = resolveModelPathCandidates(input)
      if (candidates.length === 0) return
      const { path, verified } = await pickExistingModelPath(candidates, probeFetch)
      if (path) {
        setModelPath(path)
        setModelPathMissing(!verified)
      }
    },
    [probeFetch],
  )

  const applyRegistryModel = (name: string) => {
    setPickedModel(name)
    if (!name) return
    const model = registryModels.find((m) => m.name === name)
    if (!model) return
    const stages = model.stages || {}
    const stageKey =
      stages.staging
        ? 'staging'
        : stages.prod
          ? 'prod'
          : stages.production
            ? 'production'
            : stages.latest
              ? 'latest'
              : Object.keys(stages)[0] || ''
    const stage = stageKey ? stages[stageKey] : null
    if (stage?.run_id) setSourceRunId(stage.run_id)
    const slug =
      stage?.slug ||
      (typeof stage?.path === 'string'
        ? stage.path.replace(/^workspace\/artifacts\//, '').split('/')[0]
        : model.name)
    void resolveAndSetModelPath({
      slug,
      runId: stage?.run_id || sourceRunId || null,
      stage: stageKey || 'staging',
      stagePath: typeof stage?.path === 'string' ? stage.path : null,
    })
    pushToast(`Picked model ${name}`, 'info')
  }

  const applySourceArtifact = (id: string) => {
    setSourceArtifactId(id)
    if (!id) return
    const hit = sourceArtifacts.find((a) => String(a.artifact_id || '') === id)
    if (!hit) return
    const meta =
      hit.metadata && typeof hit.metadata === 'object'
        ? (hit.metadata as Record<string, unknown>)
        : null
    // data_path is the real ArtifactRecord field; uri/path/meta.path are fallbacks.
    const uri = String(
      hit.data_path || hit.uri || hit.path || (typeof meta?.path === 'string' ? meta.path : '') || '',
    ).trim()
    const slugFromUri = uri.match(/workspace\/artifacts\/([^/]+)/)?.[1]
    void resolveAndSetModelPath({
      slug: slugFromUri || null,
      runId: sourceRunId || null,
      stage: 'staging',
      artifactUri: uri || null,
      stagePath: uri && !isModelLikeArtifact(hit) ? null : uri || null,
    })
  }

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
    setPackageExists(false)
    setPackageChecksum(null)
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
        if (isTerminalSuccess(status)) {
          let artsDir: string | null = null
          try {
            const detail = await apiJson<{ artifacts_dir?: string }>(`/runs/${runId}`)
            if (typeof detail.artifacts_dir === 'string' && detail.artifacts_dir.trim()) {
              artsDir = detail.artifacts_dir.trim()
            }
          } catch {
            /* fall through to latest symlink guess */
          }
          let pkg = guessPackagePath(target, packageName, artsDir)
          try {
            const arts = await apiJson<Array<Record<string, unknown>>>('/artifacts', {
              query: { run_id: runId },
            })
            if (!cancelled && Array.isArray(arts)) {
              let checksum: string | null = null
              for (const a of arts) {
                if (!checksum) checksum = pickChecksum(a)
                const meta =
                  a.metadata && typeof a.metadata === 'object'
                    ? (a.metadata as Record<string, unknown>)
                    : null
                const metaPath = typeof meta?.path === 'string' ? meta.path : ''
                const uri = String(a.data_path || a.uri || a.path || metaPath || '').trim()
                const typ = String(a.artifact_type || '').toLowerCase()
                if (
                  uri &&
                  (typ.includes('package') ||
                    /\.(tar\.gz|tgz|zip|h)$/i.test(uri) ||
                    /_edge\.tar\.gz$/i.test(uri))
                ) {
                  pkg = uri
                  break
                }
              }
              setPackageChecksum(checksum)
            }
          } catch {
            if (!cancelled) setPackageChecksum(null)
          }
          if (!cancelled) {
            setDownloadPath(pkg)
            setPackageExists(true)
            setStep(4)
          }
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
    const path = resolvedPackagePath
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

  const failureDiagnostics =
    runFailed && runId ? (
      <div className="space-y-2 rounded-xl border border-rose-300 bg-rose-50/80 px-3 py-3">
        <div className="text-sm font-semibold text-rose-950">Package run diagnostics</div>
        <p className="text-xs text-rose-900/90">
          Run id <code className="font-mono text-[11px]">{runId}</code>
          {runStatus ? (
            <>
              {' '}
              · <StatusBadge status={runStatus} />
            </>
          ) : null}
        </p>
        {runError ? <p className="text-xs text-rose-900">{runError}</p> : null}
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-primary" onClick={() => openRun(runId)}>
            <RefreshCw className="h-3.5 w-3.5" /> Open run
          </button>
          <button type="button" className="btn-secondary" onClick={() => openTrace({ runId })}>
            <GitBranch className="h-3.5 w-3.5" /> Open lineage
          </button>
          <button type="button" className="btn-secondary" onClick={() => openArtifacts({ runId })}>
            <Archive className="h-3.5 w-3.5" /> Open outputs
          </button>
          <button type="button" className="btn-quiet" onClick={openInBuilder}>
            <Workflow className="h-3.5 w-3.5" /> Open Editor
          </button>
        </div>
      </div>
    ) : null

  return (
    // Top padding lives on the header, not the scroll container: a sticky child's
    // `top: 0` resolves against the scrollport's PADDING box, so `p-6` would pin
    // the lineage bar 24px low and let content scroll through the strip above it.
    <div className="h-full min-h-0 overflow-y-auto px-6 pb-6 space-y-6">
      <PageHeader
        className="pt-6"
        title="Ship"
        description="Deploy — package a trained run for on-device delivery, or browse the device fleet."
        actions={
          shipTab === 'package' && packageExists ? (
            <button
              type="button"
              className="btn-secondary"
              onClick={() => openArtifacts(runId ? { runId } : undefined)}
            >
              <Archive className="h-3.5 w-3.5" /> Artifacts
            </button>
          ) : undefined
        }
      />

      <div className="flex flex-wrap gap-1 rounded-xl bg-ink-100/70 p-1 w-fit">
        <button
          type="button"
          className={shipTab === 'package' ? 'tab-pill tab-pill-on' : 'tab-pill'}
          onClick={() => setShipTab('package')}
        >
          Package
        </button>
        <button
          type="button"
          className={shipTab === 'devices' ? 'tab-pill tab-pill-on' : 'tab-pill'}
          onClick={() => setShipTab('devices')}
        >
          Devices
        </button>
      </div>

      {shipTab === 'devices' ? (
        <DevicesView workspaceId={activeProject || linkedProject || null} embedded />
      ) : (
        <>
          <div className="sticky top-0 z-20 flex flex-wrap items-center gap-2 rounded-xl border border-ink-200 bg-white/95 px-3 py-2 text-sm shadow-sm backdrop-blur">
            <span className="text-ink-500">Lineage</span>
            <input
              className="rounded-lg border border-ink-200 px-2 py-1 font-mono text-[12px]"
              placeholder="project"
              value={linkedProject}
              onChange={(e) => setLinkedProject(e.target.value.trim())}
              aria-label="Project"
            />
            <FieldSelect
              className="min-w-[14rem] max-w-[22rem] flex-1"
              triggerClassName="!mt-0 rounded-lg border border-ink-200 px-2 py-1 font-mono text-[12px]"
              value={sourceRunId}
              onChange={setSourceRunId}
              aria-label="Source run"
              placeholder="Select source run…"
              emptyLabel="Select source run…"
              mono
              options={projectRuns.map((r) => ({
                value: r.run_id,
                label: `${r.run_id.slice(0, 8)} ${r.status || ''}`.trim(),
                description: r.graph_name || undefined,
              }))}
            />
            <input
              className="min-w-[12rem] flex-1 rounded-lg border border-ink-200 px-2 py-1 font-mono text-[12px]"
              placeholder="or paste run_id"
              value={sourceRunId}
              onChange={(e) => setSourceRunId(e.target.value.trim())}
              aria-label="Source run id"
            />
            {sourceRunId ? (
              <button type="button" className="btn-secondary" onClick={() => openRun(sourceRunId)}>
                Open source run
              </button>
            ) : null}
            {sourceRunId ? (
              <button
                type="button"
                className="btn-quiet"
                onClick={() => openTrace({ runId: sourceRunId })}
              >
                <GitBranch className="h-3.5 w-3.5" /> Lineage
              </button>
            ) : null}
          </div>

          <ol className="flex flex-wrap gap-2">
            {([1, 2, 3, 4] as WizardStep[]).map((n) => {
              const active = step === n
              const done = step > n
              const hasLineage = Boolean(linkedProject.trim() && sourceRunId.trim())
              const canJump =
                n <= 2 ||
                (n === 3 && hasLineage) ||
                (n === 4 && hasLineage && Boolean(runId))
              return (
                <li key={n}>
                  <button
                    type="button"
                    disabled={!canJump && n !== step}
                    title={
                      n >= 3 && !hasLineage
                        ? 'Select project + source run first'
                        : n === 4 && !runId
                          ? 'Run package step first'
                          : undefined
                    }
                    onClick={() => {
                      if (n === step) return
                      if (n >= 3 && !hasLineage) {
                        pushToast('Select project + source run before packaging', 'error')
                        return
                      }
                      if (n === 4 && !runId) {
                        pushToast('Run the package step before download', 'error')
                        return
                      }
                      setStep(n)
                    }}
                    className={[
                      'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition',
                      active
                        ? 'border-accent-400 bg-white text-ink-950 shadow-sm'
                        : done
                          ? 'border-ink-200 bg-ink-50 text-ink-700'
                          : 'border-ink-100 bg-white/60 text-ink-400',
                      !canJump && n !== step ? 'cursor-not-allowed opacity-50' : '',
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
              <h3 className="text-sm font-semibold text-ink-900">Graph</h3>
              <p className="text-sm text-ink-500">
                This wizard is{' '}
                <strong className="font-medium text-ink-700">optimize → package → download</strong>
                — not collect/train. Set project + source train run in the lineage bar above, then
                load the edge template.
              </p>
              {!linkedProject.trim() || !sourceRunId.trim() ? (
                <EmptyState
                  title="Project + source run required"
                  description="Open a workspace, run a train pipeline from Templates/Editor, then return here with that run_id in the lineage bar."
                  action={
                    <div className="flex flex-wrap justify-center gap-2">
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => goView('templates')}
                      >
                        Open Templates
                      </button>
                      <button type="button" className="btn-secondary" onClick={() => openProjects()}>
                        Projects
                      </button>
                    </div>
                  }
                />
              ) : (
                <div className="space-y-3">
                  <button
                    type="button"
                    className="w-full rounded-xl border border-accent-300 bg-accent-50/40 p-4 text-left hover:border-accent-400 hover:bg-white"
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
                    className="ide-quiet-btn text-[12px]"
                    onClick={() => openTrace({ runId: sourceRunId })}
                  >
                    <GitBranch className="h-3.5 w-3.5" /> Inspect source lineage
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
                Required: a Keras SavedModel directory or <code className="font-mono">.keras</code>{' '}
                file under <code className="font-mono">workspace/artifacts/…</code> (from trainer /
                Example 06). INT8 needs <code className="font-mono">X_train_repr.npy</code> beside
                the model.
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block text-sm sm:col-span-2">
                  <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                    Auto-pick from model registry
                  </span>
                  <FieldSelect
                    className="mb-2 w-full"
                    value={pickedModel}
                    onChange={applyRegistryModel}
                    aria-label="Pick registered model"
                    placeholder="Select registered model…"
                    emptyLabel="Select registered model…"
                    options={registryModels.map((m) => {
                      const stages = m.stages || {}
                      const stageKey =
                        stages.staging
                          ? 'staging'
                          : stages.prod
                            ? 'prod'
                            : stages.production
                              ? 'production'
                              : stages.latest
                                ? 'latest'
                                : Object.keys(stages)[0] || ''
                      const stage = stageKey ? stages[stageKey] : undefined
                      const pathHint =
                        (typeof stage?.path === 'string' && stage.path.trim()) ||
                        (stage?.slug ? `workspace/artifacts/${stage.slug}` : '')
                      return {
                        value: m.name,
                        label: stageKey ? `${m.name} · ${stageKey}` : m.name,
                        description: pathHint
                          ? preferSavedModelPath(pathHint)
                          : undefined,
                      }
                    })}
                  />
                  {registryModels.length === 0 ? (
                    <p className="mb-2 text-[11px] text-ink-400">
                      No models in GET /models yet — register from Runs, or paste a path below.
                    </p>
                  ) : null}
                </label>
                <label className="block text-sm sm:col-span-2">
                  <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                    Model path
                  </span>
                  {sourceArtifacts.length > 0 ? (
                    <FieldSelect
                      className="mb-2 w-full"
                      value={sourceArtifactId}
                      onChange={applySourceArtifact}
                      aria-label="Source artifact"
                      placeholder="Pick artifact from source run…"
                      emptyLabel="Pick artifact from source run…"
                      mono
                      options={[
                        ...sourceArtifacts
                          .filter(isModelLikeArtifact)
                          .map((a) => {
                            const id = String(a.artifact_id || '')
                            const typ = String(a.artifact_type || 'model')
                            const uri = String(a.data_path || a.uri || a.path || '')
                            return {
                              value: id,
                              label: `${id.slice(0, 10)}… · ${typ}`,
                              description: uri || undefined,
                            }
                          }),
                        ...sourceArtifacts
                          .filter((a) => !isModelLikeArtifact(a))
                          .map((a) => {
                            const id = String(a.artifact_id || '')
                            const typ = String(a.artifact_type || 'artifact')
                            const uri = String(a.data_path || a.uri || a.path || '')
                            return {
                              value: id,
                              label: `${id.slice(0, 10)}… · ${typ}`,
                              description: uri ? `${uri} (not a model)` : undefined,
                            }
                          }),
                      ]}
                    />
                  ) : (
                    <p className="mb-2 text-[11px] text-ink-400">
                      No artifacts listed for this run yet — paste a workspace model path below
                      (fail-closed if missing).
                    </p>
                  )}
                  <input
                    className="field-control mt-0 w-full font-mono text-xs"
                    value={modelPath}
                    onChange={(e) => setModelPath(e.target.value)}
                    placeholder="workspace/artifacts/<slug>/runs/<run_id>/saved_model"
                  />
                  {!modelPathChecking && !modelPathMissing && modelPath.trim() ? (
                    <span className="mt-1 block text-[11px] text-emerald-700">
                      Verified on disk: <code className="font-mono">{modelPath}</code>
                    </span>
                  ) : null}
                  {linkedProject ? (
                    <span className="mt-1 block text-[11px] text-ink-400">
                      Linked dataset <code className="font-mono">{linkedProject}</code>
                      {linkedVersion ? (
                        <>
                          {' '}
                          / <code className="font-mono">{linkedVersion}</code>
                        </>
                      ) : null}{' '}
                      — path comes from registry / run artifacts, not the project name.
                    </span>
                  ) : null}
                  {!modelPathChecking && modelPathMissing ? (
                    <div className="mt-2 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950">
                      <p className="font-medium">Model path not found on disk</p>
                      <p className="mt-1 text-amber-900/90">
                        <code className="font-mono">{modelPath || '(empty)'}</code> is missing. Train
                        or export a model first — do not invent a fake path. Use Templates/Editor to
                        train, or pick an existing artifact.
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <button
                          type="button"
                          className="btn-primary"
                          onClick={() => goView('templates')}
                        >
                          Open Templates
                        </button>
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => goView('builder')}
                        >
                          Open Editor
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
                  <FieldSelect
                    allowEmpty={false}
                    value={backend}
                    onChange={(v) => setBackend(v as EdgeBackend)}
                    aria-label="Optimizer backend"
                    options={EDGE_BACKENDS.map((b) => ({ value: b, label: b }))}
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                    Quantization
                  </span>
                  <FieldSelect
                    allowEmpty={false}
                    value={quantization}
                    onChange={(v) => setQuantization(v as EdgeQuantization)}
                    aria-label="Quantization"
                    options={EDGE_QUANTIZATIONS.map((q) => ({ value: q, label: q }))}
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                    Package target
                  </span>
                  <FieldSelect
                    allowEmpty={false}
                    value={target}
                    onChange={(v) => setTarget(v as EdgeTarget)}
                    aria-label="Package target"
                    options={EDGE_TARGETS.map((t) => ({ value: t, label: t }))}
                  />
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
                    <Workflow className="h-3.5 w-3.5" /> Open in Editor
                  </button>
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => {
                      if (!graph) setGraph(cloneTemplate())
                      setStep(3)
                    }}
                  >
                    Next: Package run <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="rounded-2xl border border-ink-200/80 bg-white p-5 shadow-sm space-y-4">
              <h3 className="text-sm font-semibold text-ink-900">Package run</h3>
              <p className="text-sm text-ink-500">
                Executes the configured optimize → package graph via{' '}
                <code className="font-mono">POST /pipelines/run-async</code>. Needs TensorFlow (or
                ONNX stack) in the plugin runtime.
              </p>
              {runError && !runFailed && <ErrorBanner message={runError} />}
              {runId && !runFailed && (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-ink-500">Run</span>
                  <code className="font-mono text-xs text-ink-800">{runId}</code>
                  {runStatus && <StatusBadge status={runStatus} />}
                </div>
              )}
              {running && <LoadingBlock label="Starting run…" />}
              {failureDiagnostics}
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
                {runId && !runFailed && (
                  <button type="button" className="btn-secondary" onClick={() => openRun(runId)}>
                    <RefreshCw className="h-3.5 w-3.5" /> Open run
                  </button>
                )}
                {packageExists ? (
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setStep(4)}
                    title="Package artifact found — skip to download"
                  >
                    Skip to download
                  </button>
                ) : (
                  <p className="w-full text-xs text-ink-400">
                    {packageChecking
                      ? 'Checking for package artifact…'
                      : 'Skip to download is available after a package artifact exists — run the package step first.'}
                  </p>
                )}
              </div>
            </div>
          )}

          {step === 4 && (
            <div className="rounded-2xl border border-ink-200/80 bg-white p-5 shadow-sm space-y-4">
              <h3 className="text-sm font-semibold text-ink-900">Download package</h3>
              {!packageExists && !packageChecking ? (
                <EmptyState
                  title="Run package step first"
                  description="No package artifact at the expected path yet. Finish Configure → Package run, or adjust the path if the packager wrote elsewhere."
                  action={
                    <button type="button" className="btn-primary" onClick={() => setStep(3)}>
                      Back to Package run
                    </button>
                  }
                />
              ) : (
                <>
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
                      value={resolvedPackagePath}
                      onChange={(e) => setDownloadPath(e.target.value)}
                    />
                  </label>
                  <div className="rounded-xl border border-ink-100 bg-ink-50/70 px-3 py-2 text-xs text-ink-700">
                    <span className="font-semibold uppercase tracking-wide text-ink-400 text-[10px]">
                      Checksum
                    </span>
                    <div className="mt-0.5 font-mono text-[11px] break-all">
                      {packageChecksum || 'Checksum when packager emits it'}
                    </div>
                  </div>
                </>
              )}
              {runError && !runFailed && <ErrorBanner message={runError} />}
              {failureDiagnostics}
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn-primary"
                  disabled={downloading || !packageExists}
                  onClick={() => void doDownload()}
                >
                  <Download className="h-3.5 w-3.5" /> {downloading ? 'Downloading…' : 'Download'}
                </button>
                {runId && packageExists && (
                  <div className="inline-flex flex-wrap items-center gap-2">
                    <FieldSelect
                      className="w-[8rem]"
                      allowEmpty={false}
                      value={promoteAlias}
                      onChange={(v) => setPromoteAlias(v as 'staging' | 'prod')}
                      aria-label="Promote alias"
                      options={[
                        { value: 'staging', label: 'staging' },
                        { value: 'prod', label: 'prod' },
                      ]}
                      triggerClassName="!mt-0 rounded-lg border border-ink-200 px-2 py-1.5 text-xs text-ink-800"
                    />
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
                <button type="button" className="btn-secondary" onClick={openInBuilder}>
                  <Workflow className="h-3.5 w-3.5" /> Open in Editor
                </button>
                <button type="button" className="btn-secondary" onClick={() => setStep(3)}>
                  Back
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
