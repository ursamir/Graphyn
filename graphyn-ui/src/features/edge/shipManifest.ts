/**
 * Ship package manifest (`<package>.manifest.json`, written by
 * deployment_packager ≥ 1.1 next to the archive): contents + sha256,
 * self-test result, provenance summary and "how to run" commands.
 * Pure parsing / formatting helpers — rendered by ShipPackageSummary.
 */

export type ManifestFile = {
  path: string
  role: string
  size: number | null
  sha256: string | null
}

export type SelftestCheck = { name: string; status: string; detail: string }

export type SelftestSample = {
  file: string
  label: string | null
  predicted: string | null
  probability: number | null
  max_abs_diff: number | null
}

export type ShipManifest = {
  packageName: string
  packagePath: string | null
  sha256: string | null
  sizeBytes: number | null
  target: string | null
  builtAt: string | null
  packageRunId: string | null
  sourceRunId: string | null
  registeredModel: { name: string; stage: string | null; version: string | null } | null
  labels: string[]
  testAccuracy: number | null
  input: {
    sampleRate: number | null
    fixedLength: number | null
    durationS: number | null
    featureType: string | null
    tensorShape: number[] | null
    tensorDtype: string | null
  }
  contents: ManifestFile[]
  selftest: {
    status: string
    mode: string | null
    checks: SelftestCheck[]
    samples: SelftestSample[]
    notes: string[]
  }
  howToRun: string[]
  warning: string | null
}

/** Sidecar path for a package archive path. */
export function manifestPathFor(packagePath: string): string {
  const p = packagePath.trim()
  return p.endsWith('.manifest.json') ? p : `${p}.manifest.json`
}

/** True for a deployment_packager sidecar in a run's output listing. */
export function isShipManifestPath(path: string): boolean {
  return /\.(tar\.gz|tgz|zip|h)\.manifest\.json$/i.test(path.trim())
}

function str(v: unknown): string | null {
  return typeof v === 'string' && v.trim() ? v : null
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
}

function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

/** Parse the sidecar JSON; null when it is not a package manifest. */
export function parseShipManifest(raw: unknown): ShipManifest | null {
  const o = obj(raw)
  if (o.schema !== 'graphyn.package-manifest/1' && !Array.isArray(o.contents)) return null
  const reg = obj(o.registered_model)
  const input = obj(o.input)
  const tensor = obj(input.tensor)
  const st = obj(o.selftest)
  const metrics = obj(o.metrics)
  const shape = arr(tensor.shape).filter((x): x is number => typeof x === 'number')
  return {
    packageName: str(o.package) ?? 'package',
    packagePath: str(o.package_path),
    sha256: str(o.sha256),
    sizeBytes: num(o.size_bytes),
    target: str(o.target),
    builtAt: str(o.built_at),
    packageRunId: str(o.package_run_id),
    sourceRunId: str(o.source_run_id),
    registeredModel: str(reg.name)
      ? {
          name: String(reg.name),
          stage: str(reg.stage),
          version: reg.version == null ? null : String(reg.version),
        }
      : null,
    labels: arr(o.labels).map(String),
    testAccuracy: num(metrics.test_accuracy),
    input: {
      sampleRate: num(input.sample_rate),
      fixedLength: num(input.fixed_length),
      durationS: num(input.expected_duration_s),
      featureType: str(input.feature_type),
      tensorShape: shape.length ? shape : null,
      tensorDtype: str(tensor.dtype),
    },
    contents: arr(o.contents).map((c) => {
      const r = obj(c)
      return {
        path: String(r.path ?? ''),
        role: String(r.role ?? 'file'),
        size: num(r.size),
        sha256: str(r.sha256),
      }
    }).filter((c) => c.path),
    selftest: {
      status: str(st.status) ?? 'unknown',
      mode: str(st.mode),
      checks: arr(st.checks).map((c) => {
        const r = obj(c)
        return { name: String(r.name ?? ''), status: String(r.status ?? ''), detail: String(r.detail ?? '') }
      }),
      samples: arr(st.samples).map((s) => {
        const r = obj(s)
        return {
          file: String(r.file ?? ''),
          label: str(r.label),
          predicted: str(r.predicted),
          probability: num(r.probability),
          max_abs_diff: num(r.max_abs_diff),
        }
      }),
      notes: arr(st.notes).map(String),
    },
    howToRun: arr(o.how_to_run).map(String).filter(Boolean),
    warning: str(o.warning),
  }
}

/** Plain-words self-test headline + tone for a badge. */
export function selftestSummary(st: ShipManifest['selftest']): {
  label: string
  tone: 'ok' | 'warn' | 'bad' | 'muted'
} {
  const s = st.status.toLowerCase()
  if (s === 'passed') return { label: 'Self-test passed', tone: 'ok' }
  if (s === 'partial') return { label: 'Self-test partly run', tone: 'warn' }
  if (s === 'failed') return { label: 'Self-test failed', tone: 'bad' }
  return { label: 'Self-test skipped', tone: 'muted' }
}

/** Readable check name: `preprocessing_parity` → "Preprocessing parity". */
export function checkLabel(name: string): string {
  const text = name.replace(/_/g, ' ').trim()
  return text ? text[0].toUpperCase() + text.slice(1) : name
}

/** One-line input description: "16 kHz mono · 101 frames (≈1.00 s) · mfcc". */
export function inputSummary(input: ShipManifest['input']): string {
  const parts: string[] = []
  if (input.sampleRate) parts.push(`${input.sampleRate % 1000 === 0 ? input.sampleRate / 1000 : (input.sampleRate / 1000).toFixed(1)} kHz mono`)
  if (input.fixedLength) {
    parts.push(
      `${input.fixedLength} frames` + (input.durationS != null ? ` (≈${input.durationS.toFixed(2)} s)` : ''),
    )
  }
  if (input.featureType) parts.push(input.featureType)
  if (input.tensorShape) parts.push(`[${input.tensorShape.join(', ')}] ${input.tensorDtype ?? ''}`.trim())
  return parts.join(' · ')
}

/** Commands block for the "How to run" snippet (one shell line each). */
export function howToRunText(m: ShipManifest): string {
  if (m.howToRun.length) return m.howToRun.join('\n')
  return [
    `mkdir model && tar -xzf ${m.packageName} -C model && cd model`,
    'pip install -r requirements.txt',
    'python run_inference.py clip.wav --top-k 3',
  ].join('\n')
}
