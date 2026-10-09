/**
 * Run record (audit / reproducibility) — pure parsing of a run's `prove.json`
 * + `meta.json` (or the backend's enriched record fields) into one view model
 * for the Overview "Run record" card, plus the Verify checklist, the Replay
 * 409 input diff, archive flags, cache provenance and failure text helpers.
 *
 * Everything here is defensive: old runs / old API containers miss most of the
 * newer fields, so every value is optional and gaps are reported explicitly
 * ("not recorded") rather than hidden. Pure — unit-tested (runRecord.test.ts).
 */

type Rec = Record<string, unknown>

function asRec(v: unknown): Rec | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null
}

function str(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v.trim()
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  return ''
}

function firstStr(...vals: unknown[]): string {
  for (const v of vals) {
    const s = str(v)
    if (s) return s
  }
  return ''
}

function finiteNum(v: unknown): number | null {
  const n = typeof v === 'string' && v.trim() !== '' ? Number(v) : v
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

// ── Formatting ─────────────────────────────────────────────────────────

/** "b30993f454cc…" → "b30993f4" (hashes are never links, ids are). */
export function shortHash(hash: string | null | undefined, n = 8): string {
  const h = str(hash).replace(/^sha256:/i, '')
  if (!h) return ''
  return h.length > n ? h.slice(0, n) : h
}

/** Absolute local time with seconds ("Oct 3, 2026, 20:52:16"). */
export function formatAbsoluteLocal(iso: string | null | undefined): string {
  const s = str(iso)
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  try {
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return d.toISOString()
  }
}

/** "2026-10-03 18:52:16 UTC". */
export function formatUtc(iso: string | null | undefined): string {
  const s = str(iso)
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return `${d.toISOString().slice(0, 19).replace('T', ' ')} UTC`
}

/** 588096 → "9m 48s"; 6049 → "6.0 s"; 340 → "340 ms". */
export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  const h = Math.floor(ms / 3_600_000)
  const m = Math.floor((ms % 3_600_000) / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`
}

// ── Record view model ──────────────────────────────────────────────────

export type RecordGap = {
  /** Stable key ("node_versions", "plugin_version", …). */
  key: string
  /** Short field name shown in the warning. */
  label: string
  /** What is missing, in plain words. */
  hint: string
}

export type NodeVersionRow = {
  nodeType: string
  version: string
  plugin: string
  codeHash: string
  /** "isolated" | "inprocess" | "builtin" ('' on old records). */
  runtime: string
  /** "builtin" / empty / unknown — counts as not recorded. */
  placeholder: boolean
}

export type InputRow = {
  /** Path / name / dataset label ('' when only a hash was recorded). */
  label: string
  hash: string
  datasetVersion: string
  /** Node that reads it ('' on old records). */
  nodeId?: string
  /** "dir" | "file" | "missing". */
  kind?: string
  /** "content" | "manifest" (huge dirs: relpaths + sizes only). */
  hashMode?: string
  fileCount?: number | null
}

export type DatasetVersionRow = { name: string; version: string; hash: string }

export type EnvironmentView = {
  python: string
  platform: string
  image: string
  git: string
  libs: Array<[string, string]>
  /** Isolated plugin venvs the run used: plugin → sorted [lib, version] pairs. */
  pluginLibs: Array<{ plugin: string; python: string; libs: Array<[string, string]> }>
}

/** Registered model a run consumed or shipped (record `lineage.models`). */
export type LineageModelView = {
  name: string
  stage: string
  version: string
  modelHash: string
  resolved: boolean
}

export type PipelineVersionView =
  | {
      kind: 'saved'
      name: string
      env: string
      revision: string
      /** Graph was edited after load (pipeline_source "saved_modified"). */
      modified?: boolean
      /** How the backend matched it: "declared" | "content_hash" | "name_only". */
      match?: string
      /** Backend label ("name@v1"). */
      label?: string
    }
  | { kind: 'ad-hoc' }

export type RunRecordView = {
  runId: string
  actor: string
  /** true = named API token; false = self-declared (X-Actor); null = not recorded (old run). */
  actorVerified: boolean | null
  /** Name the caller claimed (X-Actor) when it differs from / was not trusted as the actor. */
  claimedActor: string
  trigger: string
  startedAt: string
  endedAt: string
  durationMs: number | null
  graphHash: string
  materializedGraphHash: string
  pipeline: PipelineVersionView | null
  seed: number | null
  runtimeVersion: string
  graphynVersion: string
  nodeVersions: NodeVersionRow[]
  inputs: InputRow[]
  datasetVersions: DatasetVersionRow[]
  environment: EnvironmentView | null
  lineageModels: LineageModelView[]
  recordHash: string
  chainPosition: number | null
  prevRecordHash: string
  replayOf: string
  /** Every field that is missing or a placeholder (amber "not recorded"). */
  gaps: RecordGap[]
  /** Was a prove record available at all? (false → only meta fields). */
  hasProve: boolean
}

const PLACEHOLDER_VERSIONS = new Set(['', 'builtin', 'unknown', 'none', 'null', 'n/a', 'na', '?', '0', '0.0.0'])

/** "builtin" / "" / "unknown" → true (the version was not really recorded). */
export function isPlaceholderVersion(v: unknown): boolean {
  return PLACEHOLDER_VERSIONS.has(str(v).toLowerCase())
}

/**
 * The record payload: backend `record` / `prove` (detail top level or meta),
 * else the raw prove.json the caller fetched.
 */
export function pickProve(detail: unknown, proveFile?: unknown): Rec | null {
  const d = asRec(detail)
  const meta = asRec(d?.meta)
  for (const cand of [d?.record, d?.prove, d?.run_record, meta?.record, meta?.prove, proveFile]) {
    const r = asRec(cand)
    if (r && Object.keys(r).length > 0) return r
  }
  return null
}

function nodeVersionRows(prove: Rec): NodeVersionRow[] {
  const impl = asRec(prove.node_implementation_versions) || asRec(prove.node_versions) || {}
  const plugins = asRec(prove.plugin_version) || asRec(prove.plugin_versions) || {}
  const pluginHashes = asRec(prove.plugin_code_hashes) || {}
  const hashes = asRec(prove.node_code_hashes) || asRec(prove.code_hashes) || {}
  const rows: NodeVersionRow[] = []
  for (const t of Object.keys(impl)) {
    const raw = impl[t]
    const obj = asRec(raw)
    const plugin = obj ? firstStr(obj.plugin, obj.plugin_name) : ''
    const pluginRaw = plugins[plugin || t]
    const pluginVer = typeof pluginRaw === 'string' ? pluginRaw.trim() : firstStr(asRec(pluginRaw)?.version)
    const version = obj ? firstStr(obj.version, obj.node_version, obj.plugin_version, obj.impl_version) : str(raw)
    const codeHash = firstStr(
      obj?.plugin_code_hash,
      obj?.code_hash,
      obj?.source_hash,
      obj?.sha256,
      hashes[t],
      pluginHashes[plugin || t],
      asRec(pluginRaw)?.code_hash,
    )
    const v = version && !isPlaceholderVersion(version) ? version : pluginVer || version
    rows.push({
      nodeType: t,
      version: v,
      plugin,
      codeHash,
      runtime: obj ? str(obj.runtime) : '',
      placeholder: isPlaceholderVersion(v) && !codeHash,
    })
  }
  return rows.sort((a, b) => a.nodeType.localeCompare(b.nodeType))
}

function inputRows(prove: Rec): InputRow[] {
  const ext = prove.external_inputs
  const raw =
    Array.isArray(ext) && ext.length > 0 ? ext : prove.inputs ?? prove.input_artifact_hashes ?? ext
  const out: InputRow[] = []
  if (Array.isArray(raw)) {
    for (const item of raw) {
      if (typeof item === 'string') {
        if (item.trim()) out.push({ label: '', hash: item.trim(), datasetVersion: '' })
        continue
      }
      const o = asRec(item)
      if (!o) continue
      const hash = firstStr(o.sha256, o.hash, o.content_hash, o.digest)
      const where = firstStr(o.path, o.uri, o.name, o.source, o.artifact_id)
      // Backend rows carry `label: "<node label> · <config key>"` — show where
      // the input entered the graph next to the path it points at.
      const label = [str(o.label), where].filter(Boolean).join(' — ')
      const ds = asRec(o.dataset)
      const datasetVersion = ds
        ? [firstStr(ds.project, ds.name), firstStr(ds.version)].filter(Boolean).join(' ')
        : firstStr(o.dataset_version, o.version, typeof o.dataset === 'string' ? o.dataset : '')
      if (hash || label) {
        out.push({
          label,
          hash,
          datasetVersion,
          nodeId: firstStr(o.node_id),
          kind: firstStr(o.kind),
          hashMode: firstStr(o.hash_mode),
          fileCount: finiteNum(o.file_count),
        })
      }
    }
  } else if (asRec(raw)) {
    for (const [k, v] of Object.entries(raw as Rec)) {
      const o = asRec(v)
      out.push({
        label: k,
        hash: o ? firstStr(o.sha256, o.hash, o.content_hash) : str(v),
        datasetVersion: o ? firstStr(o.dataset_version, o.version) : '',
      })
    }
  }
  return out
}

function datasetVersionRows(prove: Rec): DatasetVersionRow[] {
  const raw = prove.dataset_versions
  const out: DatasetVersionRow[] = []
  if (Array.isArray(raw)) {
    for (const item of raw) {
      if (typeof item === 'string') {
        if (item.trim()) out.push({ name: item.trim(), version: '', hash: '' })
        continue
      }
      const o = asRec(item)
      if (!o) continue
      out.push({
        name: firstStr(o.name, o.dataset, o.project, o.label, o.path),
        version: firstStr(o.version, o.version_tag, o.revision),
        hash: firstStr(o.content_hash, o.hash, o.sha256),
      })
    }
  } else if (asRec(raw)) {
    for (const [k, v] of Object.entries(raw as Rec)) {
      const o = asRec(v)
      out.push({
        name: k,
        version: o ? firstStr(o.version, o.version_tag) : str(v),
        hash: o ? firstStr(o.content_hash, o.hash) : '',
      })
    }
  }
  return out
}

function environmentView(prove: Rec): EnvironmentView | null {
  const env = asRec(prove.environment)
  if (!env) return null
  const libsRaw = asRec(env.libs) || asRec(env.packages) || asRec(env.libraries) || asRec(env.versions)
  const libs: Array<[string, string]> = libsRaw
    ? Object.entries(libsRaw)
        .map(([k, v]) => [k, str(v) || str(asRec(v)?.version)] as [string, string])
        .filter(([, v]) => Boolean(v))
        .sort((a, b) => a[0].localeCompare(b[0]))
    : []
  const gitRaw = env.git ?? env.git_commit ?? env.git_sha
  const gitObj = asRec(gitRaw)
  const git = gitObj
    ? [firstStr(gitObj.commit, gitObj.sha, gitObj.rev).slice(0, 12), gitObj.dirty === true ? 'dirty' : '']
        .filter(Boolean)
        .join(' · ')
    : str(gitRaw)
  const pluginEnvs = asRec(env.plugin_environments)
  const pluginLibs = pluginEnvs
    ? Object.entries(pluginEnvs)
        .map(([plugin, raw]) => {
          const pe = asRec(raw)
          const libsRec = asRec(pe?.libraries)
          const libs = libsRec
            ? Object.entries(libsRec)
                .map(([k, v]) => [k, str(v)] as [string, string])
                .filter(([, v]) => Boolean(v))
                .sort((a, b) => a[0].localeCompare(b[0]))
            : []
          return { plugin, python: str(pe?.python), libs }
        })
        .filter((p) => p.libs.length > 0)
        .sort((a, b) => a.plugin.localeCompare(b.plugin))
    : []
  const view: EnvironmentView = {
    python: [firstStr(env.python, env.python_version), str(env.implementation)].filter(Boolean).join(' '),
    platform: [firstStr(env.platform, env.os), str(env.machine)].filter(Boolean).join(' · '),
    image: firstStr(env.image, env.container_image, env.container_image_digest, env.docker_image, env.image_digest),
    git,
    libs,
    pluginLibs,
  }
  return view.python || view.platform || view.image || view.git || view.libs.length ? view : null
}

function lineageModelsView(prove: Rec): LineageModelView[] {
  const lineage = asRec(prove.lineage)
  const models = Array.isArray(lineage?.models) ? lineage.models : []
  return models
    .map((m) => asRec(m))
    .filter((m): m is Rec => Boolean(m && str(m.name)))
    .map((m) => ({
      name: str(m.name),
      stage: str(m.stage),
      // Older records put the stage name in `version` ("staging") — not a version.
      version: str(m.version) === str(m.stage) ? '' : str(m.version),
      modelHash: str(m.model_hash),
      resolved: m.resolved !== false,
    }))
}

function pipelineView(prove: Rec, meta: Rec | null): PipelineVersionView | null {
  const source = str(prove.pipeline_source ?? meta?.pipeline_source).toLowerCase()
  const raw = prove.pipeline_version ?? meta?.pipeline_ref ?? meta?.pipeline_version
  const o = asRec(raw)
  if (source === 'adhoc' || source === 'ad-hoc' || source === 'ad_hoc') return { kind: 'ad-hoc' }
  if (o) {
    if (o.ad_hoc === true || /^ad[-_]?hoc$/.test(str(o.kind).toLowerCase())) return { kind: 'ad-hoc' }
    const name = firstStr(o.name, o.pipeline, o.pipeline_name)
    const env = firstStr(o.env, o.environment, o.stage)
    const rh = firstStr(o.revision_hash)
    const revision = firstStr(o.version, o.revision, o.version_id) || (rh ? shortHash(rh, 12) : '')
    if (name || env || revision) {
      return {
        kind: 'saved',
        name,
        env,
        revision,
        modified: source === 'saved_modified',
        match: firstStr(o.match),
        label: firstStr(o.label),
      }
    }
    return null
  }
  const s = str(raw)
  if (s) {
    // "speech/staging@v3" | "v3"
    const m = s.match(/^([^/@]+)(?:\/([^@]+))?(?:@(.+))?$/)
    if (m && (m[2] || m[3])) return { kind: 'saved', name: m[1], env: m[2] || '', revision: m[3] || '' }
    return { kind: 'saved', name: '', env: '', revision: s }
  }
  return null
}

/** Build the run record view; `prove` may be null (old API, file missing). */
export function buildRunRecord(input: {
  runId: string
  prove: unknown
  meta?: unknown
  /** Run detail (GET /runs/{id}) for replay_of / record_hash at top level. */
  detail?: unknown
  graphMetadata?: { seed?: unknown } | null
}): RunRecordView {
  const prove = asRec(input.prove) || {}
  const hasProve = Object.keys(prove).length > 0
  const detail = asRec(input.detail)
  const meta = asRec(input.meta) || asRec(detail?.meta)
  const startedAt = firstStr(meta?.started_at, meta?.created_at, detail?.created_at)
  const durationS = finiteNum(meta?.duration_s ?? detail?.duration_s)
  let endedAt = firstStr(meta?.finished_at, meta?.ended_at, meta?.completed_at, detail?.finished_at)
  let durationMs = durationS != null ? durationS * 1000 : null
  if (!endedAt && startedAt && durationMs != null) {
    const t = Date.parse(startedAt)
    if (Number.isFinite(t)) endedAt = new Date(t + durationMs).toISOString()
  }
  if (durationMs == null && startedAt && endedAt) {
    const a = Date.parse(startedAt)
    const b = Date.parse(endedAt)
    if (Number.isFinite(a) && Number.isFinite(b) && b >= a) durationMs = b - a
  }
  const seed = finiteNum(prove.seed ?? meta?.seed ?? input.graphMetadata?.seed)
  const chain = asRec(prove.chain) || asRec(detail?.record_chain) || asRec(meta?.record_chain)
  const chainPosition = finiteNum(
    chain?.position ?? chain?.index ?? chain?.seq ?? prove.chain_position ?? prove.chain_index ?? detail?.chain_position,
  )
  const view: RunRecordView = {
    runId: input.runId,
    actor: firstStr(prove.actor, meta?.actor, detail?.actor),
    actorVerified: boolOrNull(prove.actor_verified ?? meta?.actor_verified ?? detail?.actor_verified),
    claimedActor: firstStr(prove.claimed_actor, meta?.claimed_actor, detail?.claimed_actor),
    trigger: firstStr(prove.trigger, meta?.trigger, detail?.trigger),
    startedAt,
    endedAt,
    durationMs,
    graphHash: firstStr(prove.graph_hash, meta?.graph_hash),
    materializedGraphHash: firstStr(meta?.materialized_graph_hash, prove.materialized_graph_hash),
    pipeline: pipelineView(prove, meta),
    seed,
    runtimeVersion: str(prove.runtime_version),
    graphynVersion: str(prove.graphyn_version),
    nodeVersions: nodeVersionRows(prove),
    inputs: inputRows(prove),
    datasetVersions: datasetVersionRows(prove),
    environment: environmentView(prove),
    lineageModels: lineageModelsView(prove),
    recordHash: firstStr(prove.record_hash, prove.hash, detail?.record_hash, meta?.record_hash),
    chainPosition,
    prevRecordHash: firstStr(chain?.prev_hash, chain?.previous_hash, prove.prev_record_hash, prove.previous_record_hash),
    replayOf: replayOfRun(detail ?? meta) || str(prove.replay_of),
    gaps: [],
    hasProve,
  }
  view.gaps = recordGaps(view, prove)
  return view
}

/** Amber "not recorded" items for a record. */
export function recordGaps(view: RunRecordView, prove: Rec = {}): RecordGap[] {
  const gaps: RecordGap[] = []
  if (!view.hasProve) {
    gaps.push({ key: 'record', label: 'Record', hint: 'No reproducibility record (prove.json) was written for this run' })
    return gaps
  }
  if (!view.actor) gaps.push({ key: 'actor', label: 'Actor', hint: 'who started the run was not recorded' })
  else if (['system', 'api', 'unknown', 'anonymous', 'unidentified'].includes(view.actor.toLowerCase())) {
    gaps.push({ key: 'actor', label: 'Actor', hint: `only a generic actor ("${view.actor}") was recorded, not a person or agent` })
  }
  if (!view.graphHash) gaps.push({ key: 'graph_hash', label: 'Graph hash', hint: 'graph snapshot hash missing' })
  if (view.seed == null) gaps.push({ key: 'seed', label: 'Seed', hint: 'random seed not recorded' })
  if (view.pipeline == null) {
    gaps.push({ key: 'pipeline_version', label: 'Pipeline version', hint: 'not recorded — run is not tied to a saved pipeline version' })
  }
  const ph = view.nodeVersions.filter((n) => n.placeholder)
  if (view.nodeVersions.length === 0) {
    gaps.push({ key: 'node_versions', label: 'Node versions', hint: 'node implementation versions not recorded' })
  } else if (ph.length > 0) {
    gaps.push({
      key: 'node_versions',
      label: 'Node versions',
      hint: `${ph.length} of ${view.nodeVersions.length} node types only say "${ph[0].version || 'unknown'}" — no plugin version or code hash`,
    })
  }
  const pv = prove.plugin_version ?? prove.plugin_versions
  if (pv == null || (asRec(pv) && Object.keys(pv as Rec).length === 0) || (typeof pv === 'string' && !pv.trim())) {
    gaps.push({ key: 'plugin_version', label: 'Plugin versions', hint: 'plugin versions not recorded' })
  }
  if (view.inputs.length > 0 && view.inputs.every((i) => !i.hash)) {
    gaps.push({ key: 'inputs', label: 'Inputs', hint: 'external inputs have no content hashes' })
  }
  if (view.datasetVersions.length === 0) {
    gaps.push({ key: 'dataset_versions', label: 'Dataset versions', hint: 'dataset versions not recorded' })
  }
  if (!view.environment) {
    gaps.push({ key: 'environment', label: 'Environment', hint: 'Python / library / image / git versions not recorded' })
  }
  if (!view.recordHash) {
    gaps.push({ key: 'record_hash', label: 'Record hash', hint: 'record is not hashed or chained — tampering would not be detectable' })
  }
  return gaps
}

export function gapFor(view: RunRecordView, key: string): RecordGap | undefined {
  return view.gaps.find((g) => g.key === key)
}

/** Human trigger label ("api" → "API", "schedule" → "Schedule"). */
export function triggerLabel(trigger: string): string {
  const t = trigger.trim().toLowerCase()
  const map: Record<string, string> = {
    api: 'API',
    ui: 'Console',
    console: 'Console',
    cli: 'CLI',
    mcp: 'MCP (agent)',
    agent: 'Agent',
    schedule: 'Schedule',
    scheduler: 'Schedule',
    webhook: 'Webhook',
    replay: 'Replay',
    sdk: 'Python SDK',
    ship: 'Ship wizard',
  }
  return map[t] || (trigger ? trigger.charAt(0).toUpperCase() + trigger.slice(1) : '')
}

/** Plain-text copy of the whole record (Copy all). */
export function recordCopyText(view: RunRecordView): string {
  const lines: string[] = [`Run ${view.runId}`]
  const add = (k: string, v: string | number | null | undefined) => {
    if (v == null || v === '') return
    lines.push(`${k}: ${v}`)
  }
  add('Actor', view.actor)
  add('Trigger', view.trigger)
  add('Started', view.startedAt ? formatUtc(view.startedAt) : '')
  add('Ended', view.endedAt ? formatUtc(view.endedAt) : '')
  add('Duration', formatDurationMs(view.durationMs))
  add('Graph hash', view.graphHash)
  add('Materialized graph hash', view.materializedGraphHash)
  if (view.pipeline?.kind === 'saved') {
    add('Pipeline version', [view.pipeline.name, view.pipeline.env, view.pipeline.revision].filter(Boolean).join(' / '))
  } else if (view.pipeline?.kind === 'ad-hoc') add('Pipeline version', 'ad-hoc graph')
  add('Seed', view.seed)
  add('Runtime', view.runtimeVersion)
  add('Graphyn', view.graphynVersion)
  for (const n of view.nodeVersions) {
    add(`Node ${n.nodeType}`, [n.version || 'not recorded', n.plugin, n.codeHash].filter(Boolean).join(' · '))
  }
  view.inputs.forEach((i, idx) =>
    add(`Input ${idx + 1}`, [i.label, i.hash, i.datasetVersion].filter(Boolean).join(' · ')),
  )
  for (const d of view.datasetVersions) add(`Dataset ${d.name}`, [d.version, d.hash].filter(Boolean).join(' · '))
  if (view.environment) {
    add('Python', view.environment.python)
    add('Platform', view.environment.platform)
    add('Image', view.environment.image)
    add('Git', view.environment.git)
    for (const [k, v] of view.environment.libs) add(`lib ${k}`, v)
  }
  add('Record hash', view.recordHash)
  add('Chain position', view.chainPosition)
  add('Previous record hash', view.prevRecordHash)
  add('Replay of', view.replayOf)
  if (view.gaps.length) lines.push(`Not recorded: ${view.gaps.map((g) => g.label).join(', ')}`)
  return lines.join('\n')
}

// ── Replay / archive / relations ───────────────────────────────────────

/** `replay_of` run id from a run row / detail / meta ('' when absent). */
export function replayOfRun(run: unknown): string {
  const r = asRec(run)
  if (!r) return ''
  const meta = asRec(r.meta)
  return firstStr(r.replay_of, meta?.replay_of, asRec(r.replay)?.of, asRec(meta?.replay)?.of)
}

/** Archived flag (`archived`, `archived_at`, status "archived"). */
export function isArchivedRun(run: unknown): boolean {
  const r = asRec(run)
  if (!r) return false
  const meta = asRec(r.meta)
  for (const o of [r, meta]) {
    if (!o) continue
    if (o.archived === true) return true
    if (str(o.archived_at)) return true
    if (str(o.status).toLowerCase() === 'archived') return true
  }
  return false
}

export type InputChange = {
  label: string
  recorded: string
  current: string
  /** "changed" | "missing" | "added" | … */
  change: string
}

/**
 * 409 "inputs changed" detail from POST /runs/{id}/replay → rows for the diff.
 * Accepts `{changes|diff|inputs|changed_inputs: [...]}` under `detail`, `error`
 * or the top level; each row `{path|input|name, recorded|expected|old, current|actual|new, status}`.
 */
export function parseReplayConflict(body: unknown): { message: string; changes: InputChange[] } {
  const root = asRec(body) || {}
  const candidates = [asRec(root.detail), asRec(root.error), asRec(asRec(root.error)?.detail), root].filter(
    Boolean,
  ) as Rec[]
  let message = ''
  const changes: InputChange[] = []
  for (const c of candidates) {
    if (!message) message = firstStr(c.message, typeof c.detail === 'string' ? c.detail : '')
    const list = [c.changes, c.diff, c.inputs, c.changed_inputs, c.input_changes].find(Array.isArray) as
      | unknown[]
      | undefined
    if (!list || changes.length) continue
    for (const item of list) {
      if (typeof item === 'string') {
        changes.push({ label: item, recorded: '', current: '', change: 'changed' })
        continue
      }
      const o = asRec(item)
      if (!o) continue
      changes.push({
        label: firstStr(o.path, o.input, o.name, o.label, o.uri, o.node_id),
        recorded: firstStr(o.recorded, o.expected, o.old, o.recorded_hash, o.expected_hash, o.before),
        current: firstStr(o.current, o.actual, o.new, o.current_hash, o.actual_hash, o.after),
        change: firstStr(o.status, o.change, o.kind) || 'changed',
      })
    }
  }
  return { message, changes }
}

/** New run id from a replay response. */
export function replayRunId(res: unknown): string {
  const r = asRec(res)
  if (!r) return ''
  return firstStr(r.run_id, r.new_run_id, r.id, asRec(r.run)?.run_id)
}

// ── Verify checklist ───────────────────────────────────────────────────

export type VerifyState = 'pass' | 'changed' | 'failed' | 'unknown'

export type VerifyItem = {
  key: string
  /** Checklist group: graph | inputs | outputs | record | chain | other. */
  group: string
  label: string
  /** Path / node the check is about ('' for run-wide checks). */
  target: string
  nodeId: string
  state: VerifyState
  detail: string
}

export type VerifyGroup = { group: string; label: string; state: VerifyState; items: VerifyItem[] }

/** One-line Verify strip: verdict, passed/total checks (items across groups), tone. */
export function verifyStripSummary(
  groups: Array<Pick<VerifyGroup, 'state' | 'items'>>,
  ok: boolean | null,
  status: string,
  /** Server `summary` counts win over the client item count when present. */
  counts?: Pick<VerifyCounts, 'passed' | 'total'> | null,
): { verdict: string; passed: number; total: number; tone: 'ok' | 'warn' | 'bad' } {
  const items = groups.flatMap((g) => (g.items.length ? g.items : [{ state: g.state }]))
  const total = counts && counts.total > 0 ? counts.total : items.length
  const passed = counts && counts.total > 0 ? counts.passed : items.filter((i) => i.state === 'pass').length
  if (status === 'unsealed') return { verdict: 'Not sealed — nothing to verify', passed, total, tone: 'warn' }
  if (ok) return { verdict: 'Verified ✓', passed, total, tone: 'ok' }
  if (groups.some((g) => g.state === 'failed')) return { verdict: 'Verification failed', passed, total, tone: 'bad' }
  if (groups.some((g) => g.state === 'changed')) return { verdict: 'Changed since this run', passed, total, tone: 'warn' }
  return { verdict: 'Verification incomplete', passed, total, tone: 'warn' }
}

// ── Last verify / verify history (server-side record of every Verify) ───

export type VerifyCounts = {
  passed: number
  failed: number
  changed: number
  missing: number
  skipped: number
  total: number
}

/** Server `summary:{passed, failed, changed, missing, skipped, total}` (null when absent). */
export function parseVerifyCounts(raw: unknown): VerifyCounts | null {
  const r = asRec(raw)
  if (!r) return null
  const n = (k: string) => finiteNum(r[k]) ?? 0
  const total = finiteNum(r.total)
  if (total == null) return null
  return { passed: n('passed'), failed: n('failed'), changed: n('changed'), missing: n('missing'), skipped: n('skipped'), total }
}

export type LastVerify = {
  checkedAt: string
  actor: string
  /** null = record predates verified identities. */
  actorVerified: boolean | null
  claimedActor: string
  ok: boolean | null
  status: string
  passed: number | null
  total: number | null
}

function boolOrNull(v: unknown): boolean | null {
  return typeof v === 'boolean' ? v : null
}

/**
 * A verify outcome from any of: run detail / list row `last_verify:{checked_at,
 * actor, actor_verified, ok, status, passed, total}`, a `POST|GET /verify`
 * response (`checked_at`, `actor`, …, `summary:{passed,total}`), or a history row.
 */
export function parseLastVerify(raw: unknown): LastVerify | null {
  const r = asRec(raw)
  if (!r) return null
  const checkedAt = firstStr(r.checked_at, r.verified_at)
  const counts = parseVerifyCounts(r.summary)
  const ok = boolOrNull(r.ok)
  const status = str(r.status).toLowerCase()
  if (!checkedAt && ok == null && !status) return null
  return {
    checkedAt,
    actor: str(r.actor),
    actorVerified: boolOrNull(r.actor_verified),
    claimedActor: str(r.claimed_actor),
    ok,
    status,
    passed: finiteNum(r.passed) ?? counts?.passed ?? null,
    total: finiteNum(r.total) ?? counts?.total ?? null,
  }
}

/** `last_verify` of a run detail (top level, else meta) or list row. */
export function lastVerifyOf(run: unknown): LastVerify | null {
  const r = asRec(run)
  if (!r) return null
  return parseLastVerify(r.last_verify) ?? parseLastVerify(asRec(r.meta)?.last_verify)
}

/** "Oct 4 17:59" (local, no year/seconds). */
export function formatVerifyWhen(iso: string | null | undefined): string {
  const s = str(iso)
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  try {
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
  } catch {
    return d.toISOString().slice(0, 16).replace('T', ' ')
  }
}

/**
 * Run record summary verdict from the last verify:
 * "Verified ✓ Oct 4 17:59 by alice · 6/6" / "Verify failed Oct 4 17:59 by alice · 4/6" /
 * "Not sealed" / "Not verified". Generic actors ("unidentified", "api") drop the "by".
 */
export function lastVerifyText(
  lv: LastVerify | null | undefined,
  fmt: (iso: string) => string = formatVerifyWhen,
): { text: string; verdict: string; tone: 'ok' | 'bad' | 'warn' | 'muted' } {
  if (!lv) return { text: 'Not verified', verdict: 'Not verified', tone: 'muted' }
  if (lv.status === 'unsealed') return { text: 'Not sealed', verdict: 'Not sealed', tone: 'warn' }
  const verdict = lv.ok ? 'Verified ✓' : 'Verify failed'
  const parts = [verdict]
  const when = lv.checkedAt ? fmt(lv.checkedAt) : ''
  if (when) parts.push(when)
  const generic = ['', 'unidentified', 'api', 'anonymous', 'unknown', 'system'].includes(lv.actor.toLowerCase())
  if (!generic) parts.push(`by ${lv.actor}`)
  let text = parts.join(' ')
  if (lv.total != null && lv.total > 0) text += ` · ${lv.passed ?? 0}/${lv.total}`
  return { text, verdict, tone: lv.ok ? 'ok' : 'bad' }
}

export type VerifyHistoryRow = LastVerify & { recordHash: string; counts: VerifyCounts | null }

/** `GET /runs/{id}/verify/history` → newest-first rows + server total. */
export function parseVerifyHistory(raw: unknown): { total: number; rows: VerifyHistoryRow[] } {
  const r = asRec(raw)
  const list = Array.isArray(raw) ? raw : Array.isArray(r?.history) ? (r!.history as unknown[]) : []
  const rows: VerifyHistoryRow[] = []
  for (const item of list) {
    const lv = parseLastVerify(item)
    if (!lv) continue
    const o = asRec(item)!
    rows.push({ ...lv, recordHash: str(o.record_hash), counts: parseVerifyCounts(o.summary) })
  }
  return { total: finiteNum(r?.total) ?? rows.length, rows }
}

const VERIFY_GROUPS: Array<[string, string, RegExp]> = [
  ['graph', 'Graph snapshot', /^(graph|graph_snapshot|graph_hash|materialized_graph)/],
  ['inputs', 'Inputs', /^(inputs?|external_inputs?|input_hashes|datasets?)/],
  ['outputs', 'Outputs', /^(outputs?|output_hashes)/],
  ['record', 'Record hash', /^(record|record_hash|prove)/],
  ['chain', 'Record chain', /^(chain|record_chain)/],
]

function verifyGroupOf(key: string): [string, string] {
  const k = key.toLowerCase()
  for (const [g, label, re] of VERIFY_GROUPS) if (re.test(k)) return [g, label]
  return ['other', key.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase())]
}

export function verifyState(raw: unknown): VerifyState {
  if (raw === true) return 'pass'
  if (raw === false) return 'failed'
  const s = str(raw).toLowerCase()
  if (!s) return 'unknown'
  if (/^(pass|passed|ok|match|matches|matched|verified|valid|unchanged|same|intact)$/.test(s)) return 'pass'
  if (/^(changed|mismatch|drift|drifted|modified|differs?|different)$/.test(s)) return 'changed'
  if (/^(fail|failed|error|missing|tampered|invalid|broken|corrupt)$/.test(s)) return 'failed'
  return 'unknown'
}

const STATE_RANK: Record<VerifyState, number> = { pass: 0, unknown: 1, changed: 2, failed: 3 }

/** Worst state of a set (failed > changed > unknown > pass); unknown when empty. */
export function worstVerifyState(states: VerifyState[]): VerifyState {
  if (!states.length) return 'unknown'
  return states.reduce((w, s) => (STATE_RANK[s] > STATE_RANK[w] ? s : w), 'pass' as VerifyState)
}

function verifyDetail(o: Rec): string {
  const d = firstStr(o.detail, o.message, o.reason, o.note)
  if (d) return d
  const det = asRec(o.details)
  if (det) {
    const parts: string[] = []
    for (const k of ['added', 'removed', 'modified']) {
      const v = det[k]
      const n = Array.isArray(v) ? v.length : finiteNum(v)
      if (n) parts.push(`${n} ${k}`)
    }
    if (det.prev_ok === false) parts.push('previous record link broken')
    if (det.entry_found === false) parts.push('not found in chain')
    if (finiteNum(det.seq) != null) parts.push(`position ${finiteNum(det.seq)}`)
    if (parts.length) return parts.join(' · ')
  }
  const st = str(o.status).toLowerCase()
  if (st === 'missing') return 'missing now'
  if (st === 'skipped') return 'skipped'
  const exp = firstStr(o.expected, o.recorded)
  const act = firstStr(o.actual, o.current)
  if (exp && act && exp !== act) return `recorded ${shortHash(exp, 12)} · now ${shortHash(act, 12)}`
  const n = finiteNum(o.changed_count ?? o.mismatches)
  const t = finiteNum(o.total ?? o.count ?? o.checked)
  if (n != null && t != null) return `${n} of ${t} changed`
  return ''
}

/**
 * GET /runs/{id}/verify → checklist. Contract: `{status, ok, checks: [{check,
 * target?, node_id?, status, expected?, actual?, details?}]}`; also accepts
 * `{key|name}` rows or a keyed map `{graph: {status}, inputs: true}`.
 */
export function normalizeVerify(raw: unknown): { ok: boolean | null; status: string; items: VerifyItem[] } {
  const r = asRec(raw)
  if (!r) return { ok: null, status: '', items: [] }
  const items: VerifyItem[] = []
  const push = (key: string, o: Rec | null, value: unknown) => {
    const [group, groupLabel] = verifyGroupOf(key)
    items.push({
      key: `${key}#${items.length}`,
      group,
      label: (o && firstStr(o.label, o.title)) || groupLabel,
      target: o ? firstStr(o.target, o.path) : '',
      nodeId: o ? firstStr(o.node_id) : '',
      state: verifyState(o ? o.status ?? o.state ?? o.result ?? o.ok ?? o.passed ?? o.match ?? o.valid : value),
      detail: o ? verifyDetail(o) : '',
    })
  }
  const list = [r.checks, r.items, r.results].find(Array.isArray) as unknown[] | undefined
  if (list) {
    for (const item of list) {
      const o = asRec(item)
      if (!o) continue
      push(firstStr(o.check, o.key, o.name, o.id) || 'other', o, null)
    }
  } else {
    const skip = new Set(['ok', 'run_id', 'verified_at', 'checked_at', 'status', 'summary', 'message', 'valid', 'passed', 'actor', 'actor_verified', 'claimed_actor', 'history_count'])
    for (const [key, v] of Object.entries(r)) {
      if (skip.has(key)) continue
      const o = asRec(v)
      if (o) push(key, o, null)
      else if (typeof v === 'boolean' || typeof v === 'string') push(key, null, v)
    }
  }
  const status = str(r.status).toLowerCase()
  const okRaw = r.ok ?? r.valid ?? r.passed
  const ok =
    typeof okRaw === 'boolean'
      ? okRaw
      : status
        ? verifyState(status) === 'pass'
        : items.length
          ? items.every((i) => i.state === 'pass')
          : null
  return { ok, status, items }
}

/** Checklist rows: one per group in a fixed order, worst state wins. */
export function groupVerify(items: VerifyItem[]): VerifyGroup[] {
  const order = ['graph', 'inputs', 'outputs', 'record', 'chain', 'other']
  const by = new Map<string, VerifyItem[]>()
  for (const it of items) by.set(it.group, [...(by.get(it.group) || []), it])
  const out: VerifyGroup[] = []
  for (const g of order) {
    const rows = by.get(g)
    if (!rows?.length) continue
    // A "skipped" chain check is unknown, not a failure.
    out.push({
      group: g,
      label: rows[0].group === 'other' ? rows[0].label : verifyGroupOf(g === 'record' ? 'record' : g)[1],
      state: worstVerifyState(rows.map((r) => r.state)),
      items: rows,
    })
  }
  return out
}

// ── Cache provenance ───────────────────────────────────────────────────

/**
 * node_id → cache source run id, from meta/debug `node_stats[].cache_source_run_id`
 * and the record's `cache: [{node_id, source_run_id}]`. Nodes that hit the
 * cache without a recorded source are absent (UI: "source run not recorded").
 */
export function cacheSourcesFromNodeStats(nodeStats: unknown, recordCache?: unknown): Map<string, string> {
  const out = new Map<string, string>()
  for (const list of [recordCache, nodeStats]) {
    if (!Array.isArray(list)) continue
    for (const row of list) {
      const o = asRec(row)
      if (!o) continue
      const id = firstStr(o.node_id, o.id)
      const src = firstStr(o.cache_source_run_id, o.source_run_id, o.cache_source, asRec(o.cache)?.source_run_id)
      if (id && src) out.set(id, src)
    }
  }
  return out
}

// ── Node labels ────────────────────────────────────────────────────────

/**
 * Backend path-aware step labels: `meta.node_labels` / `record.node_labels` /
 * `node_stats[].node_label` (node_id → "Trainer · Path C (MobileNet · lr 0.002)").
 */
export function nodeLabelsFromRun(detail: unknown, extraStats?: unknown): Map<string, string> {
  const out = new Map<string, string>()
  const d = asRec(detail)
  const meta = asRec(d?.meta)
  const record = asRec(d?.record)
  for (const src of [record?.node_labels, meta?.node_labels, d?.node_labels]) {
    const o = asRec(src)
    if (!o) continue
    for (const [k, v] of Object.entries(o)) {
      const s = str(v)
      if (s) out.set(k, s)
    }
  }
  for (const list of [meta?.node_stats, extraStats]) {
    if (!Array.isArray(list)) continue
    for (const row of list) {
      const o = asRec(row)
      const id = firstStr(o?.node_id)
      const label = firstStr(o?.node_label)
      if (id && label && !out.has(id)) out.set(id, label)
    }
  }
  return out
}

/** `node_label` on one journal event ('' when absent). */
export function eventNodeLabel(ev: unknown): string {
  const o = asRec(ev)
  if (!o) return ''
  const direct = firstStr(o.node_label)
  if (direct) return direct
  // Logger rows wrap the event JSON in `message`.
  if (typeof o.message === 'string' && o.message.trim().startsWith('{')) {
    try {
      return firstStr(asRec(JSON.parse(o.message))?.node_label)
    } catch {
      return ''
    }
  }
  return ''
}

// ── Failures ───────────────────────────────────────────────────────────

/** Traceback lines that are framework plumbing, not the user's problem. */
const NOISE_LINE =
  /(site-packages\/(anyio|starlette|fastapi|uvicorn|concurrent)|\/asyncio\/|concurrent\/futures|app\/core\/execution\/(orchestrator|node_executor|executor)\.py|^\s*\^+\s*$|^During handling of the above exception|^\s*~+\^*~*\s*$)/

export type FailureView = {
  /** "ValueError: input shape mismatch". */
  headline: string
  errorType: string
  message: string
  /** Traceback with noise frames removed ('' when none). */
  traceback: string
  hiddenNoise: number
}

/**
 * Failed-step text: backend `error_type` + `error` / `message` + `traceback`,
 * else parse a "Traceback (most recent call last): … \nValueError: msg" blob.
 */
/** Backend reason codes (not exception classes) → readable label. */
const ERROR_TYPE_LABELS: Record<string, string> = {
  orphaned_by_restart: 'Orphaned by restart',
}

export function failureView(input: {
  error?: unknown
  errorType?: unknown
  traceback?: unknown
}): FailureView | null {
  const rawErr = str(input.error)
  const rawTb = str(input.traceback)
  let errorType = str(input.errorType)
  let message = rawErr
  let tb = rawTb
  if (!tb && /Traceback \(most recent call last\)/.test(rawErr)) {
    tb = rawErr
    const lines = rawErr.split('\n').map((l) => l.trimEnd()).filter(Boolean)
    const last = lines[lines.length - 1] || ''
    message = last
  }
  if (!message && !tb) return null
  const reasonCode = errorType || (message.match(/^([a-z][a-z0-9_]+):\s/) || [])[1] || ''
  if (ERROR_TYPE_LABELS[reasonCode]) {
    if (message.startsWith(`${reasonCode}:`)) message = message.slice(reasonCode.length + 1).trim()
    errorType = ERROR_TYPE_LABELS[reasonCode]
  }
  // "ValueError: msg" → type + msg (only when the prefix looks like an exception class).
  const m = message.match(/^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning|Fault|Failure))\s*:\s*([\s\S]*)$/)
  if (m) {
    if (!errorType) errorType = m[1]
    if (m[1] === errorType || m[1].endsWith(`.${errorType}`)) message = m[2]
  }
  const firstLine = message.split('\n')[0].trim()
  const headline = errorType ? `${errorType}: ${firstLine}` : firstLine
  let hiddenNoise = 0
  let traceback = ''
  if (tb) {
    const kept: string[] = []
    const lines = tb.split('\n')
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]
      if (NOISE_LINE.test(line)) {
        hiddenNoise++
        // Drop the source line that follows a noisy "File …" frame too.
        if (/^\s*File "/.test(line) && i + 1 < lines.length && !/^\s*File "/.test(lines[i + 1])) {
          i++
          hiddenNoise++
        }
        continue
      }
      kept.push(line)
    }
    traceback = kept.join('\n').trim()
  }
  return { headline, errorType, message, traceback, hiddenNoise }
}

// ── Short id links ─────────────────────────────────────────────────────

/** Full run id for links; returns '' for a truncated/blank id we must not link. */
export function linkableRunId(id: unknown): string {
  const s = str(id)
  // Run ids are 32-hex (uuid4().hex) or uuid-like; never link an 8-char prefix
  // we produced ourselves, but do accept full ids of other shapes.
  if (!s) return ''
  if (/^[0-9a-f]{1,11}$/i.test(s)) return ''
  return s
}

/** node_id → failure from the journal's `node_error` events (latest wins). */
export function failuresByNode(events: unknown): Map<string, FailureView> {
  const out = new Map<string, FailureView>()
  if (!Array.isArray(events)) return out
  for (const row of events) {
    let ev = asRec(row)
    if (!ev) continue
    if (typeof ev.message === 'string' && ev.message.trim().startsWith('{')) {
      try {
        const inner = asRec(JSON.parse(ev.message))
        if (inner) ev = { ...ev, ...inner }
      } catch {
        /* plain text */
      }
    }
    if (str(ev.type ?? ev.event) !== 'node_error') continue
    const id = str(ev.node_id)
    if (!id) continue
    const f = failureView({
      error: firstStr(ev.error_message, ev.error, ev.message),
      errorType: ev.error_type,
      traceback: ev.traceback,
    })
    if (f) out.set(id, f)
  }
  return out
}

/** Backend labels can carry a "(MobileNet · lr 0.002)" description — keep it for tooltips. */
export function compactNodeLabel(label: string): string {
  return label.replace(/\s*\([^()]*\)\s*$/, '').trim() || label
}
