import React from 'react'
import { Download } from 'lucide-react'
import { apiJson } from '../api/client'
import { useAppStore } from '../store/appStore'

/**
 * Client-side “repro pack” — downloads JSON of run meta + trace + catalog versions.
 * Full env freeze ZIP is needs-API (B7); this is the product-shaped interim.
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
        note: 'Client-assembled pack. Full frozen env/plugin wheels need a server endpoint (plan B7).',
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
      pushToast('Repro pack downloaded (meta JSON)', 'success')
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <button type="button" className="btn-secondary" disabled={busy || !runId} onClick={() => void download()}>
      <Download className="h-3.5 w-3.5" /> Repro pack
    </button>
  )
}
