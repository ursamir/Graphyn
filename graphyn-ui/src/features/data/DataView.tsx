import React from 'react'
import { RefreshCw, Upload } from 'lucide-react'
import {
  apiFetch,
  apiJson,
  apiUrl,
  fetchAuthenticatedBlobUrl,
  getApiToken,
} from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { EmptyState, ErrorBanner, KeyValue, LoadingBlock, PageHeader } from '../../components/ui'
import { formatExecutionLine, formatMergeToast } from '../../lib/format'

interface OutputProject {
  project: string
  versions: string[]
}
interface InputLabel {
  label: string
  file_count: number
}

export default function DataView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const [outputs, setOutputs] = React.useState<OutputProject[]>([])
  const [inputs, setInputs] = React.useState<InputLabel[]>([])
  const [mode, setMode] = React.useState<'outputs' | 'inputs' | 'ingest' | 'merge'>('outputs')
  const [project, setProject] = React.useState('')
  const [version, setVersion] = React.useState('')
  const [label, setLabel] = React.useState('')
  const [rows, setRows] = React.useState<Array<Record<string, unknown>>>([])
  const [stats, setStats] = React.useState<unknown>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  // ingest
  const [urls, setUrls] = React.useState('')
  const [ingestLabel, setIngestLabel] = React.useState('uploads')
  const [hfRepo, setHfRepo] = React.useState('')
  const [ingestLog, setIngestLog] = React.useState<string[]>([])

  // merge
  const [mergeSources, setMergeSources] = React.useState('')
  const [mergeTargetProject, setMergeTargetProject] = React.useState('')
  const [mergeTargetVersion, setMergeTargetVersion] = React.useState('v1')

  const loadSources = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const [out, inp] = await Promise.all([
        apiJson<OutputProject[]>('/data/outputs'),
        apiJson<InputLabel[]>('/data/inputs'),
      ])
      setOutputs(out)
      setInputs(inp)
      if (out[0]) {
        setProject((p) => p || out[0].project)
        setVersion((v) => v || out[0].versions[0] || '')
      }
      if (inp[0]) setLabel((l) => l || inp[0].label)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    void loadSources()
  }, [loadSources])

  React.useEffect(() => {
    const run = async () => {
      if (mode === 'outputs' && project && version) {
        try {
          const [data, st] = await Promise.all([
            apiJson<Array<Record<string, unknown>>>(
              `/data/outputs/${encodeURIComponent(project)}/${encodeURIComponent(version)}`,
            ),
            apiJson(
              `/data/outputs/${encodeURIComponent(project)}/${encodeURIComponent(version)}/stats`,
            ).catch(() => null),
          ])
          setRows(data)
          setStats(st)
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err))
        }
      } else if (mode === 'inputs' && label) {
        try {
          setRows(await apiJson(`/data/inputs/${encodeURIComponent(label)}`))
          setStats(null)
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err))
        }
      }
    }
    void run()
  }, [mode, project, version, label])

  const openFile = async (path: string, kind: 'files' | 'input-files') => {
    try {
      const objUrl = await fetchAuthenticatedBlobUrl(
        `/${kind}/${path.split('/').map(encodeURIComponent).join('/')}`,
      )
      window.open(objUrl, '_blank', 'noopener,noreferrer')
      setTimeout(() => URL.revokeObjectURL(objUrl), 60_000)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const upload = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.wav,.mp3,.m4a,.ogg,.webm,.flac'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const fd = new FormData()
      fd.append('file', file)
      try {
        const res = await apiFetch('/data/inputs/upload', { method: 'POST', body: fd })
        if (!res.ok) throw new Error(`Upload failed: HTTP ${res.status}`)
        const body = await res.json()
        pushToast(`Uploaded ${body.filename ?? file.name}`, 'success')
        await loadSources()
        setMode('inputs')
        setLabel('uploads')
      } catch (err) {
        pushToast(err instanceof Error ? err.message : String(err), 'error')
      }
    }
    input.click()
  }

  const streamJob = async (jobId: string, kind: 'url' | 'huggingface') => {
    const path = `/ingest/${kind}/${jobId}/stream`
    // EventSource can't send Authorization — fall back to fetch stream if token set
    if (getApiToken()) {
      const res = await apiFetch(path, { timeoutMs: 600000 })
      if (!res.ok || !res.body) throw new Error(`Stream failed: ${res.status}`)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''
        for (const part of parts) {
          const line = part.split('\n').find((l) => l.startsWith('data:'))
          if (!line) continue
          setIngestLog((l) => [...l, line.slice(5).trim()].slice(-100))
        }
      }
      return
    }
    await new Promise<void>((resolve, reject) => {
      const es = new EventSource(apiUrl(path))
      es.onmessage = (ev) => {
        setIngestLog((l) => [...l, ev.data].slice(-100))
        try {
          const data = JSON.parse(ev.data) as { type?: string }
          if (data.type === 'summary') {
            es.close()
            resolve()
          }
        } catch {
          /* ignore */
        }
      }
      es.onerror = () => {
        es.close()
        reject(new Error('Ingest stream error'))
      }
    })
  }

  const startUrlIngest = async () => {
    try {
      const list = urls.split('\n').map((u) => u.trim()).filter(Boolean)
      const res = await apiJson<{ job_id: string }>('/ingest/url', {
        method: 'POST',
        body: JSON.stringify({ urls: list, label: ingestLabel }),
      })
      setIngestLog([`job ${res.job_id} started`])
      await streamJob(res.job_id, 'url')
      pushToast('URL ingest complete', 'success')
      await loadSources()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const startHfIngest = async () => {
    try {
      const res = await apiJson<{ job_id: string }>('/ingest/huggingface', {
        method: 'POST',
        body: JSON.stringify({ repo_id: hfRepo, split: 'train', audio_col: 'audio' }),
      })
      setIngestLog([`job ${res.job_id} started`])
      await streamJob(res.job_id, 'huggingface')
      pushToast('HF ingest complete', 'success')
      await loadSources()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const doMerge = async () => {
    try {
      const sources = mergeSources
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
        .map((s) => {
          const [projectName, ver] = s.split(':')
          return { project: projectName, version: ver }
        })
      const res = await apiJson('/data/merge', {
        method: 'POST',
        body: JSON.stringify({
          sources,
          target_project: mergeTargetProject,
          target_version: mergeTargetVersion,
        }),
      })
      pushToast(formatMergeToast(res), 'success')
      await loadSources()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const versions = outputs.find((o) => o.project === project)?.versions ?? []

  return (
    <div className="h-full overflow-y-auto p-6 space-y-4">
      <PageHeader
        title="Data"
        description="Browse pipeline outputs, upload inputs, ingest URLs, and merge dataset versions."
        actions={
          <div className="flex gap-2">
            <button type="button" className="btn-secondary" onClick={upload}>
              <Upload className="h-3.5 w-3.5" /> Upload
            </button>
            <button type="button" className="btn-secondary" onClick={() => void loadSources()}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
          </div>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void loadSources()} />}

      <div className="flex flex-wrap gap-2">
        {(
          [
            ['outputs', 'Outputs'],
            ['inputs', 'Inputs'],
            ['ingest', 'Ingest'],
            ['merge', 'Merge'],
          ] as const
        ).map(([m, label]) => (
          <button key={m} type="button" className={mode === m ? 'btn-primary' : 'btn-secondary'} onClick={() => setMode(m)}>
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <LoadingBlock />
      ) : mode === 'ingest' ? (
        <div className="space-y-4">
          <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-2">
            <h3 className="text-sm font-semibold">URL ingest</h3>
            <textarea value={urls} onChange={(e) => setUrls(e.target.value)} rows={4} className="w-full rounded-lg border border-ink-200 p-2 text-sm" placeholder="one URL per line" />
            <input value={ingestLabel} onChange={(e) => setIngestLabel(e.target.value)} className="rounded-lg border border-ink-200 px-2 py-1 text-sm" />
            <button type="button" className="btn-primary" onClick={() => void startUrlIngest()}>Start URL ingest</button>
          </section>
          <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-2">
            <h3 className="text-sm font-semibold">HuggingFace ingest</h3>
            <input value={hfRepo} onChange={(e) => setHfRepo(e.target.value)} placeholder="org/dataset" className="w-full rounded-lg border border-ink-200 px-2 py-1 text-sm" />
            <button type="button" className="btn-primary" onClick={() => void startHfIngest()}>Start HF ingest</button>
          </section>
          <pre className="max-h-48 overflow-auto rounded-xl bg-ink-950 p-3 font-mono text-[11px] text-ink-100">
            {ingestLog.map((line) => formatExecutionLine(line).text).join('\n') || 'No ingest events yet.'}
          </pre>
        </div>
      ) : mode === 'merge' ? (
        <section className="rounded-2xl border border-ink-200 bg-white p-4 space-y-2">
          <h3 className="text-sm font-semibold">Merge datasets</h3>
          <p className="text-sm text-ink-500">Comma-separated project:version pairs combined into the target project version.</p>
          <input value={mergeSources} onChange={(e) => setMergeSources(e.target.value)} className="w-full rounded-lg border border-ink-200 px-2 py-1 text-sm" placeholder="project:version, other:v2" />
          <input value={mergeTargetProject} onChange={(e) => setMergeTargetProject(e.target.value)} className="w-full rounded-lg border border-ink-200 px-2 py-1 text-sm" placeholder="target project" />
          <input value={mergeTargetVersion} onChange={(e) => setMergeTargetVersion(e.target.value)} className="w-full rounded-lg border border-ink-200 px-2 py-1 text-sm" placeholder="target version" />
          <button type="button" className="btn-primary" onClick={() => void doMerge()}>Merge</button>
        </section>
      ) : (
        <>
          {mode === 'outputs' ? (
            <div className="flex flex-wrap gap-2">
              <select value={project} onChange={(e) => { setProject(e.target.value); setVersion(outputs.find((o) => o.project === e.target.value)?.versions[0] ?? '') }} className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm">
                {outputs.map((o) => <option key={o.project} value={o.project}>{o.project}</option>)}
              </select>
              <select value={version} onChange={(e) => setVersion(e.target.value)} className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm">
                {versions.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
          ) : (
            <select value={label} onChange={(e) => setLabel(e.target.value)} className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm">
              {inputs.map((i) => <option key={i.label} value={i.label}>{i.label} ({i.file_count})</option>)}
            </select>
          )}
          {stats != null && <KeyValue data={stats} />}
          {rows.length === 0 ? (
            <EmptyState
              title="No rows"
              description="Upload audio or ingest a dataset to see files here."
              action={
                <button type="button" className="btn-primary" onClick={upload}>
                  Upload a file
                </button>
              }
            />
          ) : (
            <div className="rounded-2xl border border-ink-200 bg-white">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-ink-100 text-[11px] uppercase text-ink-500">
                  <tr><th className="px-3 py-2">Path</th><th className="px-3 py-2">Meta</th><th className="px-3 py-2">Open</th></tr>
                </thead>
                <tbody>
                  {rows.slice(0, 200).map((r, i) => {
                    const path = String(r.path ?? '')
                    return (
                      <tr key={i} className="border-b border-ink-50">
                        <td className="px-3 py-2 font-mono text-[11px]">{path}</td>
                        <td className="px-3 py-2 text-[11px] text-ink-500">{String(r.split ?? r.label ?? '')}</td>
                        <td className="px-3 py-2">
                          <button type="button" className="text-accent-700 underline" onClick={() => void openFile(path, mode === 'outputs' ? 'files' : 'input-files')}>
                            open
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
