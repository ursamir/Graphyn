import React from 'react'
import { PackageOpen as EmptyPackageOpen, Rocket as EmptyRocket } from 'lucide-react'
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
import { unwrapList } from '../../api/unwrapList'
import { apiErrorCode, apiErrorDetail } from '../../api/errorCode'
import { useAppStore } from '../../store/appStore'
import type { GraphIR } from '../../types/graph'
import {
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  StatusBadge,
} from '../../components/ui'
import { WorkbenchPage } from '../../layout'
import { SegmentedTabs } from '../../components/ui'
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
import { formatRelativeTime } from '../../lib/format'
import { runDisplayName } from '../../lib/runDisplay'
import {
  checkLabelsAgainstModel,
  isShippableSource,
  normalizeRunModels,
  parseLabelsCsv,
  pickDefaultRunModel,
  runModelSummary,
  runModelTitle,
  splitShipModels,
  runModelsFromOutputs,
  shipLineageModel,
  type RunModel,
} from './runModels'
import DevicesView from '../ship/DevicesView'
import { ShipPackageSummary } from './ShipPackageSummary'
import { useShipManifest } from './useShipManifest'
import { DEVICES_ENABLED } from '../ship/devicesFlag'
import { paths } from '../../routes/paths'
import { goView, onPathChange, readSearchParams, replacePathSearch } from '../../routes/nav'

type WizardStep = 1 | 2 | 3 | 4
type ShipTab = 'package' | 'devices'

const STEP_LABELS: Record<WizardStep, string> = {
  1: 'Source run',
  2: 'Configure',
  3: 'Package run',
  4: 'Download',
}

type RegistryStage = {
  run_id?: string
  version?: string | number | null
  slug?: string
  path?: string
  /** UX API: resolved model file for this stage (+ `exists` false when gone). */
  artifact_path?: string
  artifact_kind?: string
  format?: string
  exists?: boolean
  labels?: string[]
  path_label?: string
  source_run_display_name?: string
}

type RegistryModel = {
  name: string
  stages?: Record<string, RegistryStage>
}

function cloneTemplate(): GraphIR {
  return structuredClone(EDGE_DEPLOY_TEMPLATE)
}

function parseEdgeLocation(): {
  project?: string
  version?: string
  runId?: string
  tab?: ShipTab
  model?: string
  stage?: string
  modelPath?: string
} {
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
    // Devices tab is hidden until a device API exists (DEVICES_ENABLED).
    tab: devicesPath && DEVICES_ENABLED ? 'devices' : 'package',
    // Carried from Models → "Use in Ship" so Configure preselects that model.
    model: (params.get('model') || '').trim() || undefined,
    stage: (params.get('stage') || '').trim() || undefined,
    modelPath: (params.get('model_path') || '').trim() || undefined,
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
  /** "Paste ID" toggle in the Ship from bar (raw run-id input hidden by default). */
  const [pasteIdOpen, setPasteIdOpen] = React.useState(false)
  /** Model list fold: untrained / converted files behind "Show all files (N)". */
  const [showAllModelFiles, setShowAllModelFiles] = React.useState(false)
  const [linkedVersion, setLinkedVersion] = React.useState(initialEdge.version ?? '')
  const [sourceRunId, setSourceRunId] = React.useState(initialEdge.runId ?? '')
  const [projectRuns, setProjectRuns] = React.useState<
    Array<{
      run_id: string
      status?: string
      graph_name?: string
      display_name?: string
      summary?: { best_path_id?: string | null } | null
    }>
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
  /** Run id whose artifacts are in `sourceArtifacts` (null while loading / failed). */
  const [sourceArtifactsRun, setSourceArtifactsRun] = React.useState<string | null>(null)
  const [registryModels, setRegistryModels] = React.useState<RegistryModel[]>([])
  const [pickedModel, setPickedModel] = React.useState('')

  const [step, setStep] = React.useState<WizardStep>(1)
  const [graph, setGraph] = React.useState<GraphIR | null>(null)
  // Never prefill a guessed path — it is set only from a real run model / verified probe.
  const [modelPath, setModelPath] = React.useState(initialEdge.modelPath ?? '')
  const [labelsCsv, setLabelsCsv] = React.useState('')
  /** User typed labels by hand — stop auto-filling from the picked model. */
  const [labelsTouched, setLabelsTouched] = React.useState(false)
  const [runModels, setRunModels] = React.useState<RunModel[]>([])
  /** Run id whose models are in `runModels` (null while loading / none). */
  const [runModelsRun, setRunModelsRun] = React.useState<string | null>(null)
  const [runModelsLoading, setRunModelsLoading] = React.useState(false)
  /** Model carried from Models → Use in Ship (`?model=&stage=`). */
  const [carriedModel] = React.useState<{ name?: string; stage?: string }>(() => ({
    name: initialEdge.model,
    stage: initialEdge.stage,
  }))
  const autoAdvancedRef = React.useRef(false)
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
  const [shipPackages, setShipPackages] = React.useState<
    Array<{ package_id?: string; status?: string; checksum?: string; env?: string; created_at?: string }>
  >([])
  const [creatingShipPkg, setCreatingShipPkg] = React.useState(false)

  const resolvedPackagePath = downloadPath || guessPackagePath(target, packageName)
  const runFailed = Boolean(runId && runStatus && isTerminalFailure(runStatus))
  /** deployment_packager ≥ 1.1 sidecar: contents + sha256, how to run, self-test. */
  const { manifest: shipManifest } = useShipManifest(
    packageExists ? resolvedPackagePath : null,
    runStatus,
  )
  const shownChecksum = shipManifest?.sha256 || packageChecksum || null

  React.useEffect(() => {
    void apiJson<{ models?: RegistryModel[] }>('/models')
      .then((res) => setRegistryModels(Array.isArray(res?.models) ? res.models : []))
      .catch(() => setRegistryModels([]))
  }, [])

  // Wave A: list ship packages for workspace (SRS §9.2.14) — non-blocking.
  React.useEffect(() => {
    const project = (linkedProject.trim() || activeProject || '').trim()
    if (!project) {
      setShipPackages([])
      return
    }
    let cancelled = false
    void apiJson<{ items?: Array<Record<string, unknown>>; total?: number }>(
      `/projects/${encodeURIComponent(project)}/ship/packages`,
    )
      .then((res) => {
        if (cancelled) return
        const items = Array.isArray(res?.items) ? res.items : []
        setShipPackages(
          items.map((it) => ({
            package_id: typeof it.package_id === 'string' ? it.package_id : undefined,
            status: typeof it.status === 'string' ? it.status : undefined,
            checksum: typeof it.checksum === 'string' ? it.checksum : undefined,
            env: typeof it.env === 'string' ? it.env : undefined,
            created_at: typeof it.created_at === 'string' ? it.created_at : undefined,
          })),
        )
        const firstChecksum = items.find((it) => typeof it.checksum === 'string')?.checksum
        if (typeof firstChecksum === 'string' && firstChecksum) {
          setPackageChecksum((prev) => prev || firstChecksum)
        }
      })
      .catch(() => {
        if (!cancelled) setShipPackages([])
      })
    return () => {
      cancelled = true
    }
  }, [linkedProject, activeProject])

  // Probe model path: 404 => missing; 400 "directory" / 200 / other jailed hit => present.
  React.useEffect(() => {
    let cancelled = false
    const path = modelPath.trim()
    if (!path) {
      // Nothing picked yet — Configure shows "pick a model", not "missing on disk".
      setModelPathMissing(false)
      setModelPathChecking(false)
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
    // Only probe a real package path (from a finished run) or the guessed default
    // when this workspace has built packages before — otherwise the guess
    // (`…/edge-deploy/latest/packages/<name>_edge.tar.gz`) just 404s on every visit.
    if (!path || (!downloadPath && shipPackages.length === 0)) {
      setPackageExists(false)
      setPackageChecking(false)
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
  }, [resolvedPackagePath, runStatus, downloadPath, shipPackages.length])

  React.useEffect(() => {
    const apply = () => {
      const h = parseEdgeLocation()
      if (h.tab) setShipTab(DEVICES_ENABLED ? h.tab : 'package')
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
        if (!cancelled) {
          setSourceArtifacts(Array.isArray(arts) ? arts : [])
          setSourceArtifactsRun(rid)
        }
      } catch {
        if (!cancelled) {
          setSourceArtifacts([])
          setSourceArtifactsRun(null)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sourceRunId])

  // Models this run produced (GET /runs/{id}/models; fallback: scan run outputs).
  React.useEffect(() => {
    const rid = sourceRunId.trim()
    if (!rid) {
      setRunModels([])
      setRunModelsRun(null)
      setRunModelsLoading(false)
      return
    }
    let cancelled = false
    setRunModelsLoading(true)
    void (async () => {
      let models: RunModel[] = []
      try {
        models = normalizeRunModels(await apiJson(`/runs/${encodeURIComponent(rid)}/models`))
      } catch {
        models = []
      }
      if (models.length === 0) {
        try {
          models = runModelsFromOutputs(await apiJson(`/runs/${encodeURIComponent(rid)}/outputs`))
        } catch {
          models = []
        }
      }
      if (cancelled) return
      setRunModels(models)
      setRunModelsRun(rid)
      setRunModelsLoading(false)
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
        const runs = unwrapList<{ run_id: string; status?: string; graph_name?: string }>(
          await apiJson('/runs', { query: { limit: 20, offset: 0, project } }),
        ).filter((r) => r && typeof r.run_id === 'string')
        if (!cancelled) setProjectRuns(runs)
      } catch {
        if (!cancelled) setProjectRuns([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [linkedProject])

  /* Runs known to have produced a model: registry stage pointers (same logic
     as ModelsView.modelRunIds) plus a light artifact probe of the few newest
     successful runs. Ship used to preselect the newest *successful* run even
     when it produced no model, then probe default paths that 404. */
  const registryModelRunIds = React.useMemo(() => {
    const ids = new Set<string>()
    for (const m of registryModels) {
      for (const st of Object.values(m.stages || {})) if (st?.run_id) ids.add(st.run_id)
    }
    return ids
  }, [registryModels])
  const [probedModelRuns, setProbedModelRuns] = React.useState<{ project: string; ids: string[] } | null>(null)
  React.useEffect(() => {
    const project = linkedProject.trim()
    if (!project) return
    let cancelled = false
    const candidates = projectRuns
      .filter((r) => isTerminalSuccess(r.status || '') && !registryModelRunIds.has(r.run_id))
      .slice(0, 5)
    void (async () => {
      const found: string[] = []
      for (const r of candidates) {
        try {
          const arts = unwrapList<Record<string, unknown>>(
            await apiJson('/artifacts', { query: { run_id: r.run_id } }),
          )
          if (arts.some((a) => isModelLikeArtifact(a as Parameters<typeof isModelLikeArtifact>[0]))) {
            found.push(r.run_id)
          }
        } catch {
          /* skip */
        }
        if (cancelled) return
      }
      if (!cancelled) setProbedModelRuns({ project, ids: found })
    })()
    return () => {
      cancelled = true
    }
  }, [projectRuns, registryModelRunIds, linkedProject])
  const modelRunIds = React.useMemo(() => {
    const ids = new Set(registryModelRunIds)
    if (probedModelRuns && probedModelRuns.project === linkedProject.trim()) {
      for (const id of probedModelRuns.ids) ids.add(id)
    }
    return ids
  }, [registryModelRunIds, probedModelRuns, linkedProject])
  const modelRuns = React.useMemo(
    () => projectRuns.filter((r) => modelRunIds.has(r.run_id)),
    [projectRuns, modelRunIds],
  )

  // Preselect only a recent workspace run that actually has a model.
  React.useEffect(() => {
    if (sourceRunId.trim()) return
    const ok = modelRuns.find((r) => isTerminalSuccess(r.status || '')) ?? modelRuns[0]
    if (ok?.run_id) setSourceRunId(ok.run_id)
  }, [modelRuns, sourceRunId])

  /* Registry stage carried from Models → Use in Ship. Its resolved
     `artifact_path` (UX API) is the preferred model when it belongs to the
     selected source run and still exists. */
  const carriedStage = React.useMemo<RegistryStage | null>(() => {
    if (!carriedModel.name) return null
    const m = registryModels.find((r) => r.name === carriedModel.name)
    const stages = m?.stages || {}
    const key =
      (carriedModel.stage && stages[carriedModel.stage] ? carriedModel.stage : '') ||
      (stages.staging ? 'staging' : stages.prod ? 'prod' : stages.latest ? 'latest' : Object.keys(stages)[0] || '')
    return key ? stages[key] ?? null : null
  }, [carriedModel, registryModels])
  const preferredModelPath = React.useMemo(() => {
    if (initialEdge.modelPath) return initialEdge.modelPath
    const st = carriedStage
    if (!st || st.exists === false) return null
    if (st.run_id && sourceRunId.trim() && st.run_id !== sourceRunId.trim()) return null
    return typeof st.artifact_path === 'string' && st.artifact_path.trim() ? st.artifact_path.trim() : null
  }, [carriedStage, sourceRunId, initialEdge.modelPath])
  const bestPathId = React.useMemo(() => {
    const row = projectRuns.find((r) => r.run_id === sourceRunId.trim())
    const id = row?.summary?.best_path_id
    return typeof id === 'string' ? id : null
  }, [projectRuns, sourceRunId])

  /** Path we set automatically (so a run switch can clear it without eating user input). */
  const autoModelPathRef = React.useRef<string | null>(null)
  const autoPickKeyRef = React.useRef<string>('')
  React.useEffect(() => {
    const rid = sourceRunId.trim()
    if (!rid || runModelsRun !== rid) return
    const key = `${rid}|${preferredModelPath ?? ''}|${bestPathId ?? ''}|${runModels.length}`
    if (autoPickKeyRef.current === key) return
    autoPickKeyRef.current = key
    const userPath = modelPath.trim() && modelPath !== autoModelPathRef.current
    if (userPath && runModels.some((m) => m.path === modelPath)) return
    const pick = pickDefaultRunModel(runModels, { preferredPath: preferredModelPath, bestPathId })
    if (pick) {
      autoModelPathRef.current = pick.path
      setModelPath(pick.path)
      setSourceArtifactId('')
      return
    }
    if (preferredModelPath) {
      // Old API: no model list, but the registry resolved an existing file.
      autoModelPathRef.current = preferredModelPath
      setModelPath(preferredModelPath)
      return
    }
    if (!userPath) {
      autoModelPathRef.current = null
      setModelPath('')
    }
  }, [sourceRunId, runModelsRun, runModels, preferredModelPath, bestPathId, modelPath])

  const selectedRunModel = React.useMemo(
    () => runModels.find((m) => m.path === modelPath.trim()) ?? null,
    [runModels, modelPath],
  )
  const modelLabels = React.useMemo<string[] | null>(() => {
    if (selectedRunModel?.labels?.length) return selectedRunModel.labels
    if (carriedStage?.labels?.length && preferredModelPath && preferredModelPath === modelPath.trim()) {
      return carriedStage.labels.map(String)
    }
    return null
  }, [selectedRunModel, carriedStage, preferredModelPath, modelPath])
  // Prefill labels in the model's class order (labels.txt) unless the user typed their own.
  React.useEffect(() => {
    if (labelsTouched || !modelLabels) return
    setLabelsCsv(modelLabels.join(', '))
  }, [modelLabels, labelsTouched])
  const enteredLabels = React.useMemo(() => parseLabelsCsv(labelsCsv), [labelsCsv])
  const labelCheck = React.useMemo(
    () => checkLabelsAgainstModel(modelLabels, enteredLabels),
    [modelLabels, enteredLabels],
  )
  const configBlocker: string | null = !modelPath.trim()
    ? 'Pick a model to ship.'
    : enteredLabels.length === 0
      ? 'Enter the class labels.'
      : labelCheck.status === 'order'
        ? `Labels are in a different order than the model's classes (${labelCheck.expected.join(', ')}). Every prediction would be mislabeled.`
        : labelCheck.status === 'set'
          ? `Labels don't match the model's classes (${labelCheck.expected.join(', ')}).`
          : null

  const pickRunModel = (m: RunModel) => {
    if (!isShippableSource(m)) return
    autoModelPathRef.current = null
    setModelPath(m.path)
    setSourceArtifactId('')
    if (m.labels?.length) {
      setLabelsTouched(false)
      setLabelsCsv(m.labels.join(', '))
    }
  }

  // Step 1 is optional: once workspace + source run are known, load the edge
  // template and land on Configure automatically (once — Back still works).
  React.useEffect(() => {
    if (autoAdvancedRef.current || step !== 1) return
    if (!linkedProject.trim() || !sourceRunId.trim()) return
    autoAdvancedRef.current = true
    setGraph((g) => g ?? cloneTemplate())
    setStep(2)
  }, [linkedProject, sourceRunId, step])

  // Prefer path workspace id; devices tab via pathname segment.
  // Do not mirror ?project= when /workspaces/:id/ship already carries the id.
  React.useEffect(() => {
    const W = linkedProject.trim() || activeProject || ''
    if (!W) {
      replacePathSearch({}, paths.workspaces())
      return
    }
    const base = shipTab === 'devices' ? paths.shipDevices(W) : paths.ship(W)
    replacePathSearch(
      {
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
      // Only adopt a path that exists on disk — a guessed alias path that 404s
      // (…/staging/saved_model) is worse than an honest "pick a model".
      if (path && verified) {
        setModelPath(path)
        setModelPathMissing(false)
      } else {
        pushToast('That model file is no longer on disk — pick one of the run’s models instead', 'error')
      }
    },
    [probeFetch, pushToast],
  )

  const createShipPackageFromRegistry = async () => {
    const project = (linkedProject.trim() || activeProject || '').trim()
    if (!project) {
      pushToast('Select a workspace first', 'error')
      return
    }
    if (!pickedModel && !modelPath.trim()) {
      pushToast('Pick a model first', 'error')
      return
    }
    const model = registryModels.find((m) => m.name === pickedModel)
    const stages = model?.stages || {}
    const stageKey =
      stages.staging
        ? 'staging'
        : stages.prod
          ? 'prod'
          : stages.latest
            ? 'latest'
            : Object.keys(stages)[0] || 'staging'
    setCreatingShipPkg(true)
    try {
      const res = await apiJson<{
        package_id?: string
        status?: string
        manifest?: { checksums?: { sha256?: string } }
      }>(`/projects/${encodeURIComponent(project)}/ship/packages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': `ui-ship-${project}-${pickedModel}-${Date.now()}`,
        },
        body: JSON.stringify({
          ...(pickedModel ? { model_name: pickedModel, model_stage_or_version: stageKey } : {}),
          // UX API: ship the exact model file + labels picked in Configure.
          ...(modelPath.trim() ? { model_path: modelPath.trim() } : {}),
          ...(sourceRunId.trim() ? { run_id: sourceRunId.trim() } : {}),
          ...(enteredLabels.length ? { labels: enteredLabels } : {}),
          target: { runtime: backend || 'tflite', arch: 'any' },
          env: 'draft',
          unsigned_allowed: true,
        }),
      })
      const sha = res?.manifest?.checksums?.sha256
      if (sha) setPackageChecksum(sha)
      const warnings = Array.isArray((res as { warnings?: unknown })?.warnings)
        ? ((res as { warnings: Array<{ message?: string }> }).warnings
            .map((w) => (w && typeof w.message === 'string' ? w.message : ''))
            .filter(Boolean))
        : []
      pushToast(
        `Device package created${warnings.length ? ` — note: ${warnings.join('; ')}` : ''}`,
        warnings.length ? 'info' : 'success',
      )
      // refresh list
      const listed = await apiJson<{ items?: Array<Record<string, unknown>> }>(
        `/projects/${encodeURIComponent(project)}/ship/packages`,
      )
      const items = Array.isArray(listed?.items) ? listed.items : []
      setShipPackages(
        items.map((it) => ({
          package_id: typeof it.package_id === 'string' ? it.package_id : undefined,
          status: typeof it.status === 'string' ? it.status : undefined,
          checksum: typeof it.checksum === 'string' ? it.checksum : undefined,
          env: typeof it.env === 'string' ? it.env : undefined,
          created_at: typeof it.created_at === 'string' ? it.created_at : undefined,
        })),
      )
    } catch (err) {
      if (apiErrorCode(err) === 'labels_mismatch') {
        const expected = apiErrorDetail(err)?.expected
        pushToast(
          `Labels are in the wrong order for this model${Array.isArray(expected) ? ` — model class order is ${expected.join(', ')}` : ''}`,
          'error',
        )
        if (Array.isArray(expected)) {
          setLabelsTouched(false)
          setLabelsCsv(expected.map(String).join(', '))
        }
      } else {
        pushToast(err instanceof Error ? err.message : 'Device package create failed', 'error')
      }
    } finally {
      setCreatingShipPkg(false)
    }
  }

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
    // UX API: stages carry the real model file (`artifact_path`, and `path` is
    // no longer an alias dir) — use it as-is, never append /saved_model.
    const resolved = (stage?.artifact_path || '').trim()
    if (resolved && stage?.exists !== false) {
      autoModelPathRef.current = null
      setModelPath(resolved)
      if (stage?.labels?.length) {
        setLabelsTouched(false)
        setLabelsCsv(stage.labels.map(String).join(', '))
      }
      pushToast(`Using ${name}${stageKey ? ` (model stage ${stageKey})` : ''}`, 'info')
      return
    }
    if (stage?.exists === false) {
      pushToast(`${name}'s model file is missing on disk — pick another model`, 'error')
      return
    }
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
    const slugFromUri = uri.match(/(?:^|\/)(?:workspace\/)?artifacts\/([^/]+)/)?.[1]
    void resolveAndSetModelPath({
      slug: slugFromUri || null,
      runId: sourceRunId || null,
      stage: 'staging',
      artifactUri: uri || null,
      stagePath: uri && !isModelLikeArtifact(hit) ? null : uri || null,
    })
  }

  // Source run artifacts arrived and the model path is still the placeholder:
  // adopt the run's first model artifact instead of a guessed default path.
  // Only when the run has no model list (old API, no model files in outputs).
  React.useEffect(() => {
    if (modelPath.trim() || sourceArtifactId || runModelsLoading || runModels.length > 0) return
    const first = sourceArtifacts.find(isModelLikeArtifact)
    if (first?.artifact_id) applySourceArtifact(String(first.artifact_id))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceArtifacts, runModelsLoading, runModels.length])

  const configuredGraph = React.useMemo(() => {
    const base = graph ?? EDGE_DEPLOY_TEMPLATE
    return applyEdgeConfig(base, {
      modelPath,
      labelsCsv,
      backend,
      quantization,
      target,
      packageName,
      sourceRunId,
    })
  }, [graph, modelPath, labelsCsv, backend, quantization, target, packageName, sourceRunId])

  const useEdgeTemplate = () => {
    if (!linkedProject.trim()) {
      pushToast('Open a workspace first', 'error')
      return
    }
    if (!sourceRunId.trim()) {
      pushToast('Pick the training run whose model you want to ship', 'error')
      return
    }
    setGraph(cloneTemplate())
    setStep(2)
    pushToast('Ready to configure the package', 'success')
  }

  const openInBuilder = () => {
    loadGraphIntoBuilder(configuredGraph)
    pushToast('Opened edge graph in Editor', 'info')
  }

  /** Registered model (name · stage · version) whose file this package ships, if any. */
  const lineageModel = shipLineageModel({
    registry: registryModels,
    modelPath,
    preferredName: pickedModel || carriedModel.name || null,
    preferredStage: pickedModel ? null : carriedModel.stage || null,
  })

  const startRun = async () => {
    if (!linkedProject.trim() || !sourceRunId.trim()) {
      pushToast('Pick the training run whose model you want to ship first', 'error')
      setStep(1)
      return
    }
    if (configBlocker) {
      pushToast(configBlocker, 'error')
      setStep(2)
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
        // `ship` → "via Ship wizard" in the run record (API reads it from the
        // top level of the run payload).
        trigger: 'ship',
        // Registered model being shipped (sealed into the run record's lineage;
        // older APIs ignore the field).
        ...(lineageModel ? { lineage: { model: lineageModel } } : {}),
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
      const raw = err instanceof Error ? err.message : String(err)
      const msg = apiErrorCode(err) === 'labels_mismatch' || /labels_mismatch/i.test(raw)
        ? `The labels don't match the model's class order. ${raw}`
        : raw
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
            const arts = unwrapList<Record<string, unknown>>(await apiJson('/artifacts', {
              query: { run_id: runId },
            }))
            if (!cancelled) {
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
        `${msg} — open Run outputs / Datasets if the package landed under a different name.`,
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
              · <StatusBadge kind="run" status={runStatus} />
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
    <WorkbenchPage
      title="Ship"
      description="Package a trained model for on-device delivery."
      toolbar={
        !DEVICES_ENABLED ? undefined : <SegmentedTabs
          aria-label="Ship mode"
          value={shipTab}
          options={[
            { id: 'package', label: 'Package' },
            { id: 'devices', label: 'Devices' },
          ]}
          onChange={setShipTab}
        />
      }
      actions={
        shipTab === 'package' && packageExists ? (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => openArtifacts(runId ? { runId } : undefined)}
          >
            <Archive className="h-3.5 w-3.5" /> Run outputs
          </button>
        ) : undefined
      }
    >
      <div className="space-y-6">
      {DEVICES_ENABLED && shipTab === 'devices' ? (
        <DevicesView workspaceId={activeProject || linkedProject || null} embedded />
      ) : (
        <>
          {/* Sticky "Ship from" band: an opaque full-bleed strip pinned to the very
              top of the scroll area (cancels .workbench-scroll's px-4/py-3), so the
              model list never shows through above or behind the bar when scrolled. */}
          <div className="sticky -top-3 z-20 -mx-4 -mt-3 border-b border-ink-100 bg-white px-4 pb-2 pt-3">
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm shadow-sm">
            <span className="text-ink-500" title="The training run whose model you are shipping">
              Ship from
            </span>
            {/* Workspace is implicit (the open workspace); only ask for it when none is open. */}
            {linkedProject ? null : (
              <input
                className="rounded-lg border border-ink-200 px-2 py-1 text-[12px]"
                placeholder="Workspace"
                value={linkedProject}
                onChange={(e) => setLinkedProject(e.target.value.trim())}
                aria-label="Workspace"
              />
            )}
            <FieldSelect
              className="min-w-[14rem] max-w-[22rem] flex-1"
              triggerClassName="!mt-0 rounded-lg border border-ink-200 px-2 py-1 font-mono text-[12px]"
              value={sourceRunId}
              onChange={setSourceRunId}
              aria-label="Source run"
              placeholder="Select a training run…"
              emptyLabel="Select a training run…"
              options={(modelRuns.length > 0 ? modelRuns : projectRuns).map((r) => ({
                value: r.run_id,
                label: runDisplayName(r),
                description: [
                  r.run_id.slice(0, 8),
                  modelRuns.length > 0 ? null : 'no model files found',
                  r.status && !isTerminalSuccess(r.status) ? r.status : null,
                ]
                  .filter(Boolean)
                  .join(' · '),
              }))}
            />
            {pasteIdOpen ? (
              <input
                autoFocus
                className="min-w-[12rem] flex-1 rounded-lg border border-ink-200 px-2 py-1 font-mono text-[12px]"
                placeholder="Run id"
                value={sourceRunId}
                onChange={(e) => setSourceRunId(e.target.value.trim())}
                onKeyDown={(e) => {
                  if (e.key === 'Escape' || e.key === 'Enter') setPasteIdOpen(false)
                }}
                aria-label="Source run id"
              />
            ) : (
              <button
                type="button"
                className="text-[12px] text-ink-500 hover:text-accent-800 hover:underline"
                title={linkedProject ? `Workspace ${linkedProject} — paste the id of a run that isn't listed` : 'Paste a run id'}
                onClick={() => setPasteIdOpen(true)}
              >
                Paste ID
              </button>
            )}
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
                        ? 'Select workspace + source run first'
                        : n === 4 && !runId
                          ? 'Run package step first'
                          : undefined
                    }
                    onClick={() => {
                      if (n === step) return
                      if (n >= 3 && !hasLineage) {
                        pushToast('Select workspace + source run before packaging', 'error')
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
            <div className="rounded-lg border border-ink-200/80 bg-white p-5 shadow-sm space-y-4">
              <h3 className="text-sm font-semibold text-ink-900">Source run</h3>
              <p className="text-sm text-ink-500">
                Ship turns a trained model into a package for devices: convert → package → download.
                Pick the training run above — Configure opens automatically.
              </p>
              {linkedProject.trim() && !sourceRunId.trim() ? (
                <EmptyState icon={EmptyRocket}
                  title={
                    modelRuns.length > 0
                      ? 'Pick a source run'
                      : `No runs with a model in ${linkedProject.trim()} yet`
                  }
                  description={
                    modelRuns.length > 0
                      ? 'Choose the train run whose model you want to ship in the lineage bar above.'
                      : 'Run a training pipeline (e.g. Speech commands E2E) first, then come back here to package its model.'
                  }
                  action={
                    <div className="flex flex-wrap justify-center gap-2">
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => goView('templates')}
                      >
                        Open Templates
                      </button>
                      <button type="button" className="btn-secondary" onClick={() => goView('runs')}>
                        Runs
                      </button>
                    </div>
                  }
                />
              ) : !linkedProject.trim() || !sourceRunId.trim() ? (
                <EmptyState icon={EmptyRocket}
                  title="Pick a workspace and a training run"
                  description="Open a workspace and train a model from Templates or the Editor, then pick that run above."
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
                        Workspaces
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
                      <Cpu className="h-4 w-4 text-accent-700" /> Continue to Configure
                    </div>
                    <p className="mt-1 text-xs text-ink-500">
                      Uses the standard convert → package pipeline for{' '}
                      {runDisplayName(projectRuns.find((r) => r.run_id === sourceRunId.trim()) ?? { run_id: sourceRunId })}
                    </p>
                  </button>
                  {sourceArtifactsRun === sourceRunId.trim() &&
                  !modelRunIds.has(sourceRunId.trim()) &&
                  !sourceArtifacts.some(isModelLikeArtifact) ? (
                    <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                      This run saved no model files. Pick a training run that saved a model
                      {modelRuns.length > 0 ? ` (${modelRuns.length} in this workspace)` : ''}.
                    </p>
                  ) : null}
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
                Choose the trained model to convert and package for devices. INT8 quantization also
                needs the representative sample file the trainer saves next to the model.
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2 sm:col-span-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="block text-[12px] font-medium text-ink-700">
                      Model to ship
                    </span>
                    {carriedModel.name ? (
                      <span className="text-[11px] text-ink-500" title="Chosen on the Models page">
                        From Models: <span className="font-medium text-ink-700">{carriedModel.name}</span>
                        {carriedModel.stage ? ` · model stage ${carriedModel.stage}` : ''}
                      </span>
                    ) : null}
                  </div>
                  {runModelsLoading || (sourceRunId.trim() && runModelsRun !== sourceRunId.trim()) ? (
                    <LoadingBlock label="Looking for this run’s models…" />
                  ) : runModels.length > 0 ? (
                    (() => {
                      /* Main list: shippable trained models, best first. Untrained /
                         already-converted files sit behind "Show all files (N)" (opened
                         automatically when the current pick is one of them). */
                      const { main, rest } = splitShipModels(runModels, bestPathId)
                      const pickedInRest = rest.some((m) => m.path === modelPath.trim())
                      const showRest = showAllModelFiles || pickedInRest || main.length === 0
                      const renderRow = (m: (typeof runModels)[number]) => {
                        const shippable = isShippableSource(m)
                        const active = m.path === modelPath.trim()
                        return (
                          <li key={m.path}>
                            <button
                              type="button"
                              role="radio"
                              aria-checked={active}
                              disabled={!shippable}
                              title={m.path}
                              onClick={() => pickRunModel(m)}
                              className={[
                                'flex w-full items-start gap-3 px-3 py-2 text-left transition',
                                active ? 'bg-accent-50' : 'bg-white hover:bg-ink-50',
                                shippable ? '' : 'cursor-not-allowed opacity-60',
                              ].join(' ')}
                            >
                              <span
                                aria-hidden
                                className={[
                                  'mt-1 inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border',
                                  active ? 'border-accent-600 bg-accent-500' : 'border-ink-300 bg-white',
                                ].join(' ')}
                              />
                              <span className="min-w-0 flex-1">
                                <span className="flex flex-wrap items-center gap-2 text-[13px] font-medium text-ink-900">
                                  <span className="truncate">{runModelTitle(m)}</span>
                                  {bestPathId && m.path_id === bestPathId && shippable ? (
                                    <span className="text-[11px] font-normal text-emerald-700">Best result</span>
                                  ) : null}
                                </span>
                                <span className="block text-[11px] text-ink-500">
                                  {runModelSummary(m)}
                                  {m.created_at ? ` · ${formatRelativeTime(m.created_at)}` : ''}
                                  {m.labels?.length ? ` · ${m.labels.length} classes` : ''}
                                </span>
                                {!shippable ? (
                                  <span className="block text-[11px] text-amber-800">
                                    {m.kind === 'compiled_untrained'
                                      ? 'Not trained yet — this is the empty model before training.'
                                      : 'Already converted — pick the trained model it came from.'}
                                  </span>
                                ) : null}
                              </span>
                            </button>
                          </li>
                        )
                      }
                      return (
                        <div className="space-y-1.5">
                          <ul
                            role="radiogroup"
                            aria-label="Model to ship"
                            className="divide-y divide-ink-100 overflow-hidden rounded-xl border border-ink-200"
                          >
                            {main.map(renderRow)}
                            {showRest ? rest.map(renderRow) : null}
                          </ul>
                          {main.length === 0 ? (
                            <p className="text-[11px] text-amber-800">
                              No trained model in this run — the files below can’t be shipped as-is.
                            </p>
                          ) : null}
                          {rest.length > 0 && main.length > 0 && !pickedInRest ? (
                            <button
                              type="button"
                              className="text-[12px] text-ink-500 hover:text-accent-800 hover:underline"
                              aria-expanded={showRest}
                              onClick={() => setShowAllModelFiles((v) => !v)}
                            >
                              {showRest ? 'Hide other files' : `Show all files (${runModels.length})`}
                            </button>
                          ) : null}
                        </div>
                      )
                    })()
                  ) : (
                    <EmptyState
                      compact
                      icon={EmptyRocket}
                      title="This run saved no model files"
                      description="Pick a different training run in the bar above, or train a model first."
                      action={
                        <button type="button" className="btn-secondary" onClick={() => goView('templates')}>
                          Open Templates
                        </button>
                      }
                    />
                  )}
                  {!runModelsLoading && runModels.length === 0 && modelPath.trim() && !modelPathMissing && !modelPathChecking ? (
                    <p className="text-[11px] text-emerald-700" title={modelPath}>
                      Using the registered model file (found on disk).
                    </p>
                  ) : null}
                </div>
                <label className="block text-sm sm:col-span-2">
                  <span className="mb-1 block text-[12px] font-medium text-ink-700">
                    Class labels, in the model's output order
                  </span>
                  <input
                    className={[
                      'field-control mt-0 w-full text-xs',
                      labelCheck.status === 'order' || labelCheck.status === 'set' ? '!border-rose-400' : '',
                    ].join(' ')}
                    value={labelsCsv}
                    placeholder={modelLabels ? modelLabels.join(', ') : 'e.g. down, go, no, stop, up, yes'}
                    aria-invalid={labelCheck.status === 'order' || labelCheck.status === 'set'}
                    onChange={(e) => {
                      setLabelsTouched(true)
                      setLabelsCsv(e.target.value)
                    }}
                  />
                  {labelCheck.status === 'ok' ? (
                    <span className="mt-1 block text-[11px] text-emerald-700">Matches the model's class order.</span>
                  ) : labelCheck.status === 'unknown' ? (
                    <span className="mt-1 block text-[11px] text-ink-400">
                      Comma-separated. The order must match the order the model was trained with.
                    </span>
                  ) : (
                    <div className="mt-1 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-[11px] text-rose-900" role="alert">
                      {labelCheck.status === 'order'
                        ? 'Same classes, different order — every prediction would get the wrong name.'
                        : `Different classes than the model${labelCheck.missing.length ? ` (missing: ${labelCheck.missing.join(', ')})` : ''}${labelCheck.extra.length ? ` (unknown: ${labelCheck.extra.join(', ')})` : ''}.`}{' '}
                      Model class order is <span className="font-medium">{labelCheck.expected.join(', ')}</span>.{' '}
                      <button
                        type="button"
                        className="font-medium underline"
                        onClick={() => {
                          setLabelsTouched(false)
                          setLabelsCsv(labelCheck.expected.join(', '))
                        }}
                      >
                        Use model order
                      </button>
                    </div>
                  )}
                </label>
                <details className="rounded-xl border border-ink-100 bg-ink-50/50 px-3 py-2 sm:col-span-2">
                  <summary className="cursor-pointer select-none text-[12px] font-medium text-ink-600">
                    Advanced — registered models, file path
                  </summary>
                  <div className="mt-3 space-y-3">
                <div className="block text-sm">
                  <span className="mb-1 block text-[12px] font-medium text-ink-700">
                    Registered model (model registry)
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
                        (typeof stage?.artifact_path === 'string' && stage.artifact_path.trim()) ||
                        (typeof stage?.path === 'string' && stage.path.trim()) ||
                        (stage?.slug ? `workspace/artifacts/${stage.slug}` : '')
                      return {
                        value: m.name,
                        label: stageKey ? `${m.name} · model stage ${stageKey}` : m.name,
                        description:
                          stage?.exists === false
                            ? 'model file missing'
                            : [stage?.path_label, stage?.format, stage?.source_run_display_name]
                                .filter(Boolean)
                                .join(' · ') ||
                              (pathHint
                                ? stage?.artifact_path
                                  ? pathHint
                                  : preferSavedModelPath(pathHint)
                                : undefined),
                      }
                    })}
                  />
                  {registryModels.length === 0 ? (
                    <p className="mb-2 text-[11px] text-ink-400">
                      No registered models yet — register one from Models, or paste a path below.
                    </p>
                  ) : (
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        className="ide-quiet-btn text-[12px]"
                        disabled={creatingShipPkg || (!pickedModel && !modelPath.trim()) || Boolean(configBlocker)}
                        title="Build a package with the model file and labels, without the convert step"
                        onClick={() => void createShipPackageFromRegistry()}
                      >
                        {creatingShipPkg ? 'Creating package…' : 'Package as-is (no conversion)'}
                      </button>
                      {shipPackages.length > 0 ? (
                        <span className="text-[11px] text-ink-400">
                          {shipPackages.length} package{shipPackages.length === 1 ? '' : 's'} in workspace
                        </span>
                      ) : null}
                    </div>
                  )}
                </div>
                <div className="block text-sm">
                  <span className="mb-1 block text-[12px] font-medium text-ink-700">
                    Model file path
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
                      Paste a model file or SavedModel folder inside the workspace. Missing paths are rejected.
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
                  {!modelPathChecking && modelPathMissing && modelPath.trim() ? (
                    <div className="mt-2 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950">
                      <p className="font-medium">Model path not found on disk</p>
                      <p className="mt-1 text-amber-900/90">
                        <code className="font-mono">{modelPath}</code> does not exist. Pick one of the
                        run’s models above, or train a model first from Templates.
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
                </div>
                  </div>
                </details>
                <label className="block text-sm">
                  <span className="mb-1 block text-[12px] font-medium text-ink-700">
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
                  <span className="mb-1 block text-[12px] font-medium text-ink-700">
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
                  <span className="mb-1 block text-[12px] font-medium text-ink-700">
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
                  <span className="mb-1 block text-[12px] font-medium text-ink-700">
                    Package name
                  </span>
                  <input
                    className="field-control mt-0 w-full font-mono text-xs"
                    value={packageName}
                    onChange={(e) => setPackageName(e.target.value)}
                  />
                </label>
              </div>
              {configBlocker && modelPath.trim() ? (
                <p className="text-right text-[11px] text-rose-700">{configBlocker}</p>
              ) : null}
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
                    disabled={Boolean(configBlocker)}
                    title={configBlocker ?? undefined}
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
                Converts the model and builds the device package. This needs the TensorFlow (or
                ONNX) runtime on the server.
              </p>
              {runError && !runFailed && <ErrorBanner message={runError} />}
              {runId && !runFailed && (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-ink-500">Run</span>
                  <code className="font-mono text-xs text-ink-800">{runId}</code>
                  {runStatus && <StatusBadge kind="run" status={runStatus} />}
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
                <EmptyState icon={EmptyPackageOpen}
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
                    <span className="mb-1 block text-[12px] font-medium text-ink-700">
                      Artifact path
                    </span>
                    <input
                      className="field-control mt-0 w-full font-mono text-xs"
                      value={resolvedPackagePath}
                      onChange={(e) => setDownloadPath(e.target.value)}
                    />
                  </label>
                  <div className="rounded-xl border border-ink-100 bg-ink-50/70 px-3 py-2 text-xs text-ink-700">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium text-ink-500 text-[11px]">
                        Package checksum (sha256)
                      </span>
                      {shownChecksum ? (
                        <button
                          type="button"
                          className="btn-quiet text-[11px]"
                          onClick={() => {
                            void navigator.clipboard?.writeText(shownChecksum)
                            pushToast('Checksum copied', 'success')
                          }}
                        >
                          Copy
                        </button>
                      ) : null}
                    </div>
                    <div className="mt-0.5 font-mono text-[11px] break-all" data-testid="ship-package-checksum">
                      {shownChecksum ? (
                        <>
                          <span className="text-ink-400">sha256:</span> {shownChecksum}
                        </>
                      ) : (
                        <span className="text-ink-500">
                          Pending — shown when ship package create or packager artifact emits{' '}
                          <code className="font-mono text-[10px]">checksums.sha256</code> (SHIP-002).
                        </span>
                      )}
                    </div>
                    {shipPackages.length > 0 ? (
                      <ul className="mt-2 space-y-1 border-t border-ink-100 pt-2">
                        {shipPackages.slice(0, 5).map((p, idx) => (
                          <li key={p.package_id || p.checksum || `pkg-${idx}`} className="font-mono text-[10px] text-ink-600">
                            {p.package_id || 'pkg'} · {p.status || '—'}
                            {p.checksum ? (
                              <>
                                {' '}
                                · <span className="text-ink-800">{p.checksum.slice(0, 16)}…</span>
                              </>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </>
              )}
              {packageExists && shipManifest ? (
                <ShipPackageSummary manifest={shipManifest} onOpenRun={(id) => openRun(id)} />
              ) : null}
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
    </WorkbenchPage>
  )
}
