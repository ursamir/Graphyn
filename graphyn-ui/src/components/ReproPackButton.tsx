import React from 'react'
import { FileJson } from 'lucide-react'
import { apiJson } from '../api/client'
import { useAppStore } from '../store/appStore'

/**
 * Client-side meta export — JSON of run detail + trace + readiness.
 * Not a full frozen env / wheels pack (that needs a server endpoint).
 */
export function ReproPackButton({ runId }: { runId: string }) {
  const pushToast = useAppStore((s) => s.pushToast)
  const [busy, setBusy] = React.useState(false)

  const download = async () => {
    setBusy(true)
    try {
      const [run, trace, readiness] = await Promise.all([
        apiJson<Record<string, unknown>>(`/runs/${encodeURIComponent(runId)}`).catch(() => null),
        apiJson<Record<string, unknown>>(`/trace`, { query: { run_id: runId } }).catch(() => null),
        apiJson<Record<string, unknown>>('/system/readiness').catch(() => null),
      ])
      const pack = {
        schema: 'graphyn.repro_pack.v0',
        created_at: new Date().toISOString(),
        run_id: runId,
        note: 'Client-assembled meta JSON (run + trace + readiness). Not a frozen env or plugin wheels pack.',
        run,
        trace,
        readiness,
      }
      const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `graphyn-repro-${runId.slice(0, 8)}.json`
      a.click()
      URL.revokeObjectURL(a.href)
      pushToast('Exported run meta JSON', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      type="button"
      className="btn-quiet !px-2 !py-1 text-[11px]"
      disabled={busy || !runId}
      title="Download run + lineage + readiness as JSON (not a full environment freeze)"
      onClick={() => void download()}
    >
      <FileJson className="h-3.5 w-3.5" /> {busy ? 'Exporting…' : 'Export meta'}
    </button>
  )
}
