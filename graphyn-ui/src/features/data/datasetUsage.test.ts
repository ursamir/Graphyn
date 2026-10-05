import { describe, expect, it } from 'vitest'
import { mostUsedInputLabel, runDatasetPaths, usedInputLabels } from './datasetUsage'

describe('usedInputLabels', () => {
  const labels = ['dog_bark', 'go', 'speech-commands', 'yes']
  const runs = [
    { run_id: 'a', summary: { dataset: { source_path: 'workspace/datasets/input/speech-commands', resolved_path: null } } },
    { run_id: 'b', summary: null },
    { run_id: 'c', summary: { dataset: { source_path: 'workspace/datasets/input/speech-commands-extra' } } },
  ]
  it('matches whole path segments from run dataset paths', () => {
    expect(usedInputLabels(labels, runs)).toEqual(['speech-commands'])
  })
  it('includes pinned labels, in catalog order', () => {
    expect(usedInputLabels(labels, runs, ['yes', 'missing'])).toEqual(['speech-commands', 'yes'])
  })
  it('reads paths defensively', () => {
    expect(runDatasetPaths(null)).toEqual([])
    expect(runDatasetPaths({ meta: { summary: { dataset: { resolved_path: 'x/go' } } } })).toEqual(['x/go'])
  })
})

describe('mostUsedInputLabel', () => {
  it('prefers the dataset most runs read', () => {
    const run = (p: string) => ({ summary: { dataset: { source_path: p } } })
    const runs = [run('workspace/datasets/input/speech-commands'), run('workspace/datasets/input/speech-commands'), run('workspace/datasets/input/speech-commands/down')]
    expect(mostUsedInputLabel(['down', 'speech-commands'], runs)).toBe('speech-commands')
    expect(mostUsedInputLabel(['x'], runs)).toBeNull()
  })
})
