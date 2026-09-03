import React from 'react'
import { RefreshCw, Copy, Pencil } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import {
  ConfirmButton,
  CollapsibleJson,
  EmptyState,
  ErrorBanner,
  KeyValue,
  LoadingBlock,
  PageHeader,
  StatusBadge,
} from '../../components/ui'

interface Project {
  name: string
  status?: string
  [key: string]: unknown
}

type Tab = 'spec' | 'taxonomy' | 'contract' | 'versions' | 'snapshots' | 'diff'

const STATUSES = ['active', 'archived', 'draft', 'ready'] as const

export default function ProjectsView() {
  const pushToast = useAppStore((s) => s.pushToast)
  const [projects, setProjects] = React.useState<Project[] | null>(null)
  const [selected, setSelected] = React.useState<string | null>(null)
  const [tab, setTab] = React.useState<Tab>('versions')
  const [newName, setNewName] = React.useState('')
  const [renameTo, setRenameTo] = React.useState('')
  const [cloneTo, setCloneTo] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  const [spec, setSpec] = React.useState('')
  const [taxonomy, setTaxonomy] = React.useState('[]')
  const [contract, setContract] = React.useState('{}')
  const [versions, setVersions] = React.useState<unknown[]>([])
  const [versionFocus, setVersionFocus] = React.useState('')
  const [versionStats, setVersionStats] = React.useState<unknown>(null)
  const [versionSamples, setVersionSamples] = React.useState<unknown>(null)
  const [snapshots, setSnapshots] = React.useState<unknown[]>([])
  const [snapshotName, setSnapshotName] = React.useState('')
  const [diffA, setDiffA] = React.useState('')
  const [diffB, setDiffB] = React.useState('')
  const [diffResult, setDiffResult] = React.useState<unknown>(null)
  const [lineage, setLineage] = React.useState<unknown>(null)

  const load = React.useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      setProjects(await apiJson<Project[]>('/projects'))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setProjects([])
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  const open = async (name: string) => {
    setSelected(name)
    setRenameTo(name)
    setCloneTo(`${name}-copy`)
    setError(null)
    setVersionStats(null)
    setVersionSamples(null)
    setDiffResult(null)
    try {
      const [vers, sp, tax, con, snaps, lin] = await Promise.all([
        apiJson<unknown[]>(`/projects/${encodeURIComponent(name)}/versions`),
        apiJson<{ markdown?: string }>(`/projects/${encodeURIComponent(name)}/spec`).catch(() => ({
          markdown: '',
        })),
        apiJson(`/projects/${encodeURIComponent(name)}/taxonomy`).catch(() => []),
        apiJson(`/projects/${encodeURIComponent(name)}/contract`).catch(() => ({})),
        apiJson<unknown[]>(`/projects/${encodeURIComponent(name)}/snapshots`).catch(() => []),
        apiJson(`/projects/${encodeURIComponent(name)}/lineage`).catch(() => null),
      ])
      setVersions(vers)
      setSpec(sp?.markdown ?? '')
      setTaxonomy(JSON.stringify(tax, null, 2))
      setContract(JSON.stringify(con, null, 2))
      setSnapshots(Array.isArray(snaps) ? snaps : [])
      setLineage(lin)
      const first =
        typeof vers[0] === 'string'
          ? vers[0]
          : String((vers[0] as { version?: string } | undefined)?.version ?? '')
      setVersionFocus(first)
      setDiffA(first)
      setDiffB(typeof vers[1] === 'string' ? vers[1] : first)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const create = async () => {
    if (!newName.trim()) return
    try {
      await apiJson('/projects', { method: 'POST', body: JSON.stringify({ name: newName.trim() }) })
      pushToast(`Created ${newName}`, 'success')
      setNewName('')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const rename = async () => {
    if (!selected || !renameTo.trim()) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}`, {
        method: 'PATCH',
        body: JSON.stringify({ new_name: renameTo.trim() }),
      })
      pushToast(`Renamed to ${renameTo}`, 'success')
      await load()
      await open(renameTo.trim())
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const clone = async () => {
    if (!selected || !cloneTo.trim()) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}/clone`, {
        method: 'POST',
        body: JSON.stringify({ new_name: cloneTo.trim() }),
      })
      pushToast(`Cloned to ${cloneTo}`, 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const setStatus = async (status: string) => {
    if (!selected) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      })
      pushToast(`Status → ${status}`, 'success')
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const remove = async () => {
    if (!selected) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}`, {
        method: 'DELETE',
        body: JSON.stringify({ confirm: selected }),
      })
      pushToast(`Deleted ${selected}`, 'success')
      setSelected(null)
      await load()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const saveSpec = async () => {
    if (!selected) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}/spec`, {
        method: 'PUT',
        body: JSON.stringify({ markdown: spec }),
      })
      pushToast('Spec saved', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const saveTaxonomy = async () => {
    if (!selected) return
    try {
      const body = JSON.parse(taxonomy) as unknown
      await apiJson(`/projects/${encodeURIComponent(selected)}/taxonomy`, {
        method: 'PUT',
        body: JSON.stringify(body),
      })
      pushToast('Taxonomy saved', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const saveContract = async () => {
    if (!selected) return
    try {
      const body = JSON.parse(contract) as unknown
      await apiJson(`/projects/${encodeURIComponent(selected)}/contract`, {
        method: 'PUT',
        body: JSON.stringify(body),
      })
      pushToast('Contract saved', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const loadVersionDetail = async () => {
    if (!selected || !versionFocus) return
    try {
      const [st, samp] = await Promise.all([
        apiJson(
          `/projects/${encodeURIComponent(selected)}/versions/${encodeURIComponent(versionFocus)}/stats`,
        ),
        apiJson(
          `/projects/${encodeURIComponent(selected)}/versions/${encodeURIComponent(versionFocus)}/samples`,
          { query: { page: 1, page_size: 20 } },
        ).catch(() => null),
      ])
      setVersionStats(st)
      setVersionSamples(samp)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const restoreVersion = async () => {
    if (!selected || !versionFocus) return
    try {
      await apiJson(
        `/projects/${encodeURIComponent(selected)}/versions/${encodeURIComponent(versionFocus)}/restore`,
        { method: 'POST' },
      )
      pushToast(`Restored ${versionFocus}`, 'success')
      await open(selected)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const createSnapshot = async () => {
    if (!selected || !snapshotName.trim()) return
    try {
      await apiJson(`/projects/${encodeURIComponent(selected)}/snapshots`, {
        method: 'POST',
        body: JSON.stringify({ snapshot_name: snapshotName.trim() }),
      })
      pushToast(`Snapshot ${snapshotName} created`, 'success')
      setSnapshotName('')
      await open(selected)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const restoreSnapshot = async (name: string) => {
    if (!selected) return
    try {
      await apiJson(
        `/projects/${encodeURIComponent(selected)}/snapshots/${encodeURIComponent(name)}/restore`,
        { method: 'POST' },
      )
      pushToast(`Restored snapshot ${name}`, 'success')
      await open(selected)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const runDiff = async () => {
    if (!selected) return
    try {
      const res = await apiJson(`/projects/${encodeURIComponent(selected)}/diff`, {
        query: { version_a: diffA, version_b: diffB },
      })
      setDiffResult(res)
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const versionOptions = versions.map((v) =>
    typeof v === 'string' ? v : String((v as { version?: string }).version ?? JSON.stringify(v)),
  )

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-[320px_1fr]">
      <div className="overflow-y-auto border-r border-ink-200 p-4 space-y-3">
        <PageHeader
          title="Projects"
          description="Dataset projects live under workspace/datasets/output. Create, open, rename, clone, or delete a project here."
          actions={
            <button type="button" className="btn-secondary" onClick={() => void load()} aria-label="Refresh">
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          }
        />
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        <div className="flex gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="new-project"
            className="flex-1 rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
            onKeyDown={(e) => e.key === 'Enter' && void create()}
          />
          <button type="button" className="btn-primary" onClick={() => void create()}>
            Create
          </button>
        </div>
        {loading || projects == null ? (
          <LoadingBlock />
        ) : projects.length === 0 ? (
          <EmptyState
            title="No dataset projects"
            description="Nothing under workspace/datasets/output yet. Create a project to manage dataset versions."
            action={
              <button type="button" className="btn-primary" onClick={() => void create()}>
                Create project
              </button>
            }
          />
        ) : (
          <ul className="space-y-2">
            {projects.map((p) => (
              <li key={p.name}>
                <button
                  type="button"
                  onClick={() => void open(p.name)}
                  className={`w-full rounded-xl border px-3 py-2 text-left ${
                    selected === p.name ? 'border-accent-400 bg-accent-50' : 'border-ink-200 bg-white'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{p.name}</span>
                    {p.status && <StatusBadge status={String(p.status)} />}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="overflow-y-auto p-4 space-y-4">
        {!selected ? (
          <EmptyState title="Select a project" description="Open a dataset project to rename, clone, delete, or inspect versions." />
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="font-display text-lg font-bold">{selected}</h3>
                <div className="mt-2 flex flex-wrap gap-1">
                  {STATUSES.map((s) => (
                    <button key={s} type="button" className="btn-secondary" onClick={() => void setStatus(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
              <ConfirmButton label="Delete project" confirmLabel={`Delete ${selected}?`} danger onConfirm={() => void remove()} />
            </div>

            <div className="flex flex-wrap gap-2 rounded-xl border border-ink-200 bg-white p-3">
              <input
                value={renameTo}
                onChange={(e) => setRenameTo(e.target.value)}
                className="rounded-lg border border-ink-200 px-2 py-1 text-sm"
                aria-label="Rename to"
              />
              <button type="button" className="btn-secondary" onClick={() => void rename()}>
                <Pencil className="h-3.5 w-3.5" /> Rename
              </button>
              <input
                value={cloneTo}
                onChange={(e) => setCloneTo(e.target.value)}
                className="rounded-lg border border-ink-200 px-2 py-1 text-sm"
                aria-label="Clone as"
              />
              <button type="button" className="btn-secondary" onClick={() => void clone()}>
                <Copy className="h-3.5 w-3.5" /> Clone
              </button>
            </div>

            <div className="flex flex-wrap gap-1">
              {(
                [
                  ['versions', 'Versions'],
                  ['spec', 'Spec'],
                  ['taxonomy', 'Taxonomy'],
                  ['contract', 'Contract'],
                  ['snapshots', 'Snapshots'],
                  ['diff', 'Diff / lineage'],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={tab === id ? 'btn-primary' : 'btn-secondary'}
                  onClick={() => setTab(id)}
                >
                  {label}
                </button>
              ))}
            </div>

            {tab === 'spec' && (
              <section className="space-y-2">
                <p className="text-sm text-ink-500">Markdown description of what this dataset is for. Saved as the project spec.</p>
                <textarea
                  value={spec}
                  onChange={(e) => setSpec(e.target.value)}
                  rows={16}
                  className="w-full rounded-xl border border-ink-200 p-3 font-mono text-sm"
                />
                <button type="button" className="btn-primary" onClick={() => void saveSpec()}>
                  Save spec
                </button>
              </section>
            )}

            {tab === 'taxonomy' && (
              <section className="space-y-2">
                <p className="text-sm text-ink-500">JSON list or map of labels/classes this dataset uses (the taxonomy).</p>
                <textarea
                  value={taxonomy}
                  onChange={(e) => setTaxonomy(e.target.value)}
                  rows={16}
                  className="w-full rounded-xl border border-ink-200 p-3 font-mono text-sm"
                />
                <button type="button" className="btn-primary" onClick={() => void saveTaxonomy()}>
                  Save taxonomy
                </button>
              </section>
            )}

            {tab === 'contract' && (
              <section className="space-y-2">
                <p className="text-sm text-ink-500">JSON schema/contract for records in this project (fields, types, required keys).</p>
                <textarea
                  value={contract}
                  onChange={(e) => setContract(e.target.value)}
                  rows={16}
                  className="w-full rounded-xl border border-ink-200 p-3 font-mono text-sm"
                />
                <button type="button" className="btn-primary" onClick={() => void saveContract()}>
                  Save contract
                </button>
              </section>
            )}

            {tab === 'versions' && (
              <section className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <select
                    value={versionFocus}
                    onChange={(e) => setVersionFocus(e.target.value)}
                    className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
                  >
                    {versionOptions.map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="btn-secondary" onClick={() => void loadVersionDetail()}>
                    Load stats / samples
                  </button>
                  <ConfirmButton
                    label="Restore version"
                    confirmLabel={`Restore ${versionFocus}?`}
                    onConfirm={() => void restoreVersion()}
                  />
                </div>
                <KeyValue data={versions} empty="No versions." />
                {versionStats != null && <KeyValue data={versionStats} />}
                {versionSamples != null && <CollapsibleJson value={versionSamples} label="Samples" />}
              </section>
            )}

            {tab === 'snapshots' && (
              <section className="space-y-3">
                <div className="flex gap-2">
                  <input
                    value={snapshotName}
                    onChange={(e) => setSnapshotName(e.target.value)}
                    placeholder="snapshot-name"
                    className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
                  />
                  <button type="button" className="btn-primary" onClick={() => void createSnapshot()}>
                    Create snapshot
                  </button>
                </div>
                {snapshots.length === 0 ? (
                  <EmptyState title="No snapshots" />
                ) : (
                  <ul className="space-y-2">
                    {snapshots.map((s, i) => {
                      const name =
                        typeof s === 'string'
                          ? s
                          : String((s as { name?: string }).name ?? `snapshot-${i}`)
                      return (
                        <li
                          key={name}
                          className="flex items-center justify-between rounded-xl border border-ink-200 bg-white px-3 py-2"
                        >
                          <span className="font-mono text-sm">{name}</span>
                          <ConfirmButton
                            label="Restore"
                            confirmLabel={`Restore ${name}?`}
                            onConfirm={() => void restoreSnapshot(name)}
                          />
                        </li>
                      )
                    })}
                  </ul>
                )}
              </section>
            )}

            {tab === 'diff' && (
              <section className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <select
                    value={diffA}
                    onChange={(e) => setDiffA(e.target.value)}
                    className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
                  >
                    {versionOptions.map((v) => (
                      <option key={`a-${v}`} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                  <span className="self-center text-sm text-ink-500">vs</span>
                  <select
                    value={diffB}
                    onChange={(e) => setDiffB(e.target.value)}
                    className="rounded-lg border border-ink-200 px-2 py-1.5 text-sm"
                  >
                    {versionOptions.map((v) => (
                      <option key={`b-${v}`} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="btn-primary" onClick={() => void runDiff()}>
                    Diff
                  </button>
                </div>
                {diffResult != null && <KeyValue data={diffResult} />}
                <h4 className="text-sm font-semibold">Lineage</h4>
                <KeyValue data={lineage} empty="No lineage." />
              </section>
            )}
          </>
        )}
      </div>
    </div>
  )
}
