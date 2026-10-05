import { describe, expect, it } from 'vitest'
import {
  checkLabel,
  howToRunText,
  inputSummary,
  isShipManifestPath,
  manifestPathFor,
  parseShipManifest,
  selftestSummary,
} from './shipManifest'

const RAW = {
  schema: 'graphyn.package-manifest/1',
  package: 'kws_edge.tar.gz',
  package_path: 'workspace/artifacts/edge-deploy/runs/x/packages/kws_edge.tar.gz',
  sha256: 'a'.repeat(64),
  size_bytes: 52000,
  target: 'edge',
  source_run_id: '787747eeb2cc4c69a568f8bc0ab9cd6c',
  registered_model: { name: 'speech-commands-dscnn', stage: 'staging', version: null },
  labels: ['down', 'go'],
  metrics: { test_accuracy: 0.7225 },
  input: {
    sample_rate: 16000,
    fixed_length: 101,
    expected_duration_s: 1.0,
    feature_type: 'mfcc',
    tensor: { shape: [1, 101, 40, 1], dtype: 'uint8' },
  },
  contents: [
    { path: 'model.tflite', role: 'model', size: 46664, sha256: 'b'.repeat(64) },
    { path: '', role: 'junk' },
  ],
  selftest: {
    status: 'passed',
    mode: 'strict',
    checks: [{ name: 'preprocessing_parity', status: 'passed', detail: 'ok' }],
    samples: [{ file: 'v1/test/down/a.wav', label: 'down', predicted: 'down', probability: 0.87, max_abs_diff: 0 }],
    notes: [],
  },
  how_to_run: ['sha256sum kws_edge.tar.gz', 'python run_inference.py clip.wav --top-k 3'],
}

describe('shipManifest', () => {
  it('derives the sidecar path and recognises it in output listings', () => {
    expect(manifestPathFor('a/b/kws_edge.tar.gz')).toBe('a/b/kws_edge.tar.gz.manifest.json')
    expect(manifestPathFor('a/kws.zip.manifest.json')).toBe('a/kws.zip.manifest.json')
    expect(isShipManifestPath('runs/x/packages/kws_edge.tar.gz.manifest.json')).toBe(true)
    expect(isShipManifestPath('runs/x/metrics.json')).toBe(false)
  })

  it('parses a packager manifest', () => {
    const m = parseShipManifest(RAW)!
    expect(m.packageName).toBe('kws_edge.tar.gz')
    expect(m.contents).toHaveLength(1)
    expect(m.registeredModel).toEqual({ name: 'speech-commands-dscnn', stage: 'staging', version: null })
    expect(m.testAccuracy).toBeCloseTo(0.7225)
    expect(m.selftest.samples[0].predicted).toBe('down')
    expect(selftestSummary(m.selftest)).toEqual({ label: 'Self-test passed', tone: 'ok' })
    expect(inputSummary(m.input)).toBe('16 kHz mono · 101 frames (≈1.00 s) · mfcc · [1, 101, 40, 1] uint8')
    expect(howToRunText(m)).toContain('python run_inference.py clip.wav')
  })

  it('rejects non-manifest JSON and labels statuses', () => {
    expect(parseShipManifest({ accuracy: 0.9 })).toBeNull()
    expect(parseShipManifest(null)).toBeNull()
    expect(selftestSummary({ status: 'failed', mode: null, checks: [], samples: [], notes: [] }).tone).toBe('bad')
    expect(selftestSummary({ status: 'skipped', mode: null, checks: [], samples: [], notes: [] }).tone).toBe('muted')
    expect(checkLabel('input_shape')).toBe('Input shape')
  })
})
