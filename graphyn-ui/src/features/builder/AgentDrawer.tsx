import React from 'react'
import { Inbox, Sparkles, X } from 'lucide-react'
import { apiJson } from '../../api/client'
import { useAppStore } from '../../store/appStore'
import { emptyGraph } from '../../types/graph'

const SAVE_AFTER_LOAD_KEY = 'graphyn.builder.saveAfterProposalLoad'

function readSaveAfterLoad(): boolean {
  try {
    return localStorage.getItem(SAVE_AFTER_LOAD_KEY) === '1'
  } catch {
    return false
  }
}

function writeSaveAfterLoad(value: boolean) {
  try {
    localStorage.setItem(SAVE_AFTER_LOAD_KEY, value ? '1' : '0')
  } catch {
    /* ignore */
  }
}

type AgentDrawerProps = {
  open: boolean
  onClose: () => void
}

export default function AgentDrawer({ open, onClose }: AgentDrawerProps) {
  const pushToast = useAppStore((s) => s.pushToast)
  const pendingProposalCount = useAppStore((s) => s.pendingProposalCount)
  const setPendingProposalCount = useAppStore((s) => s.setPendingProposalCount)
  const openProposals = useAppStore((s) => s.openProposals)

  const [prompt, setPrompt] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [saveAfterLoad, setSaveAfterLoad] = React.useState(readSaveAfterLoad)

  if (!open) return null

  const onPropose = async () => {
    const summary = prompt.trim()
    if (!summary) {
      pushToast('Enter a prompt for the proposal', 'error')
      return
    }
    setBusy(true)
    try {
      const stub = emptyGraph('agent-proposal')
      stub.metadata = {
        ...stub.metadata,
        description: summary.slice(0, 500),
        tags: [...(stub.metadata.tags || []), 'agent-inbox'],
      }
      await apiJson('/proposals', {
        method: 'POST',
        body: JSON.stringify({
          summary: summary.slice(0, 280),
          graph: stub,
          actor: 'ui-builder-agent',
        }),
      })
      pushToast('Proposal created — review in Agent inbox', 'success')
      setPrompt('')
      setPendingProposalCount(pendingProposalCount + 1)
      try {
        const data = await apiJson<{ proposals: unknown[] }>('/proposals?status=pending')
        setPendingProposalCount(Array.isArray(data.proposals) ? data.proposals.length : pendingProposalCount + 1)
      } catch {
        /* keep optimistic count */
      }
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="absolute inset-y-0 right-0 z-30 flex w-[min(100%,340px)] flex-col border-l border-ink-200 bg-white shadow-soft">
      <div className="flex items-start justify-between gap-2 border-b border-ink-100 px-3 py-2">
        <div className="min-w-0">
          <div className="text-type-meta font-semibold uppercase tracking-wide text-ink-400">Agent</div>
          <div className="text-sm font-semibold text-ink-950">Propose a graph</div>
          <div className="text-[11px] text-ink-400">Creates a stub proposal for inbox review</div>
        </div>
        <button type="button" className="btn-icon" aria-label="Close agent panel" onClick={onClose}>
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
        <label className="block text-[12px] text-ink-700">
          <span className="font-medium">Prompt</span>
          <textarea
            className="field-control mt-1 min-h-[7rem] text-[12px] leading-5"
            placeholder="Describe the pipeline you want…"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
        </label>

        <button
          type="button"
          className="btn-primary w-full"
          disabled={busy}
          onClick={() => void onPropose()}
        >
          <Sparkles className="h-3.5 w-3.5" />
          {busy ? 'Proposing…' : 'Propose'}
        </button>

        <div className="rounded-lg border border-ink-100 bg-ink-50/70 px-2.5 py-2 text-[11px] text-ink-600">
          <div className="font-medium text-ink-800">
            {pendingProposalCount} pending proposal{pendingProposalCount === 1 ? '' : 's'}
          </div>
          <button
            type="button"
            className="mt-1.5 inline-flex items-center gap-1.5 text-[11px] font-medium text-accent-800 hover:underline"
            onClick={() => {
              openProposals()
              onClose()
            }}
          >
            <Inbox className="h-3.5 w-3.5" /> Open inbox
          </button>
        </div>

        <label className="flex items-start gap-2 text-[11px] leading-snug text-ink-600">
          <input
            type="checkbox"
            className="mt-0.5 h-3.5 w-3.5 rounded border-ink-300"
            checked={saveAfterLoad}
            onChange={(e) => {
              const next = e.target.checked
              setSaveAfterLoad(next)
              writeSaveAfterLoad(next)
            }}
          />
          <span>
            Save to project after load — Accept still happens in Agent inbox; after Accept loads the
            graph into the Editor, use Save (preference remembered for a future Accept &amp; save
            path).
          </span>
        </label>
      </div>
    </div>
  )
}
