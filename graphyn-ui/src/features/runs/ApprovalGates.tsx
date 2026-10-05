/**
 * Approval cards on a run's Overview (`hitl_approve` gates):
 * `GET /runs/{id}/gates` (polled every 3 s while a gate is pending) and
 * `POST /runs/{id}/gates/{node_id}/decision {decision, comment?, role?}`.
 * Pending gates get a card (prompt · waiting since · expires · roles · reason
 * field · Reject / Approve); decided gates collapse to one line with the
 * approver (`ActorName`, verified tick) and outcome. Renders nothing when the
 * run has no gates or the API predates gates (404 route).
 */
import React from 'react'
import clsx from 'clsx'
import { ShieldQuestion } from 'lucide-react'
import { ApiError, apiJson } from '../../api/client'
import { apiErrorCode } from '../../api/errorCode'
import { ActorName } from '../../components/ActorName'
import { formatRelativeTime } from '../../lib/format'
import { isAwaitingApproval } from '../../lib/runStatus'
import { usePolling } from '../../lib/usePolling'
import { useAppStore } from '../../store/appStore'
import { formatAbsoluteLocal, formatUtc } from './runRecord'
import { gateCardState, gateErrorText, gateTitle, parseGates, type Gate, type GatesPayload } from './gates'

function GateCard({
  runId,
  gate,
  title,
  onDecided,
}: {
  runId: string
  gate: Gate
  title: string
  onDecided: () => void
}) {
  const pushToast = useAppStore((s) => s.pushToast)
  const [comment, setComment] = React.useState('')
  const [role, setRole] = React.useState(gate.approverRoles.length === 1 ? gate.approverRoles[0] : '')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState('')
  const st = gateCardState(gate, comment, role, busy)
  const blocked = Boolean(st.disabledReason)

  const decide = async (decision: 'approve' | 'reject') => {
    setBusy(true)
    setError('')
    try {
      await apiJson(`/runs/${encodeURIComponent(runId)}/gates/${encodeURIComponent(gate.nodeId)}/decision`, {
        method: 'POST',
        body: JSON.stringify({
          decision,
          ...(comment.trim() ? { comment: comment.trim() } : {}),
          ...(role.trim() ? { role: role.trim() } : {}),
        }),
      })
      pushToast(decision === 'approve' ? `Approved “${title}”` : `Rejected “${title}”`, 'success')
      onDecided()
    } catch (err) {
      const code = apiErrorCode(err)
      const msg = gateErrorText(code, err instanceof Error ? err.message : String(err))
      if (err instanceof ApiError && err.status === 409) {
        pushToast(msg, 'info')
        onDecided()
      } else setError(msg)
    } finally {
      setBusy(false)
    }
  }

  const fieldId = `gate-comment-${gate.nodeId}`
  return (
    <section
      aria-label={`Approval: ${title}`}
      className="rounded-xl border border-violet-200 bg-white px-3 py-2.5 shadow-sm"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <ShieldQuestion className="h-4 w-4 shrink-0 text-violet-700" aria-hidden />
        <h3 className="min-w-0 truncate text-[13px] font-semibold text-ink-950" title={gate.nodeId}>
          {title}
        </h3>
        <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[11px] font-semibold text-violet-900 ring-1 ring-inset ring-violet-200">
          {st.headline}
        </span>
      </div>
      {gate.prompt ? (
        <p className="mt-1.5 whitespace-pre-wrap break-words text-[12.5px] leading-snug text-ink-800">{gate.prompt}</p>
      ) : null}
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-500">
        {gate.waitingSince ? (
          <span title={formatUtc(gate.waitingSince)}>Waiting since {formatRelativeTime(gate.waitingSince)}</span>
        ) : null}
        {gate.expiresAt ? (
          <span title={formatUtc(gate.expiresAt)}>
            Expires {formatRelativeTime(gate.expiresAt)}
            <span className="text-ink-400"> — then rejected automatically</span>
          </span>
        ) : null}
        {gate.approverRoles.length ? <span>Approver roles: {gate.approverRoles.join(', ')}</span> : null}
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
        <div className="min-w-0 space-y-1.5">
          {st.needsRole && gate.approverRoles.length > 1 ? (
            <label className="block text-[12px] text-ink-700">
              <span className="font-medium">Approve as</span>
              <select className="field-control mt-1" value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="">Select role…</option>
                {gate.approverRoles.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label htmlFor={fieldId} className="block text-[12px] text-ink-700">
            <span className="font-medium">{gate.reasonRequired ? 'Reason' : 'Comment'}</span>
            {gate.reasonRequired ? <span className="text-rose-600"> *</span> : <span className="text-ink-400"> (optional)</span>}
          </label>
          <textarea
            id={fieldId}
            rows={2}
            maxLength={4000}
            className="field-control text-[12.5px]"
            placeholder={gate.reasonRequired ? 'Why approve or reject? Required for this gate.' : 'Optional note'}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            className="btn-secondary"
            disabled={busy || blocked}
            title={st.disabledReason || 'Reject — the run follows the rejected branch'}
            onClick={() => void decide('reject')}
          >
            Reject
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={busy || blocked}
            title={st.disabledReason || 'Approve — the run continues'}
            onClick={() => void decide('approve')}
          >
            {busy ? 'Sending…' : 'Approve'}
          </button>
        </div>
      </div>
      {error ? (
        <p className="mt-1 text-[11.5px] font-medium text-rose-700" role="alert">
          {error}
        </p>
      ) : null}
      <p className="mt-1 text-[10.5px] text-ink-400">Your decision is recorded with your identity; the comment is kept as a fingerprint.</p>
    </section>
  )
}

function DecidedGateRow({ gate, title }: { gate: Gate; title: string }) {
  const st = gateCardState(gate, '')
  const d = gate.decision
  return (
    <li className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 px-3 py-1.5 text-[12px] text-ink-700">
      <span className="min-w-0 truncate font-medium text-ink-900" title={gate.nodeId}>
        {title}
      </span>
      <span className="text-ink-300">·</span>
      <span
        className={clsx(
          st.tone === 'bad' && 'rounded-full bg-rose-50 px-1.5 text-[11px] font-semibold text-rose-800 ring-1 ring-inset ring-rose-200',
          st.tone !== 'bad' && 'text-ink-600',
        )}
      >
        {st.headline}
      </span>
      {d?.approver ? (
        <>
          <span className="text-ink-400">by</span>
          <ActorName actor={d.approver} verified={d.actorVerified} compact />
          {d.role ? <span className="text-ink-500">as {d.role}</span> : null}
        </>
      ) : null}
      {d?.decidedAt ? (
        <span className="text-ink-500" title={formatUtc(d.decidedAt)}>
          · {formatAbsoluteLocal(d.decidedAt)}
        </span>
      ) : null}
      {d?.source && d.source !== 'api' ? <span className="text-ink-400">· via {d.source}</span> : null}
      {d?.commentSha256 ? (
        <span className="font-mono text-[10px] text-ink-400" title={`Comment sha256 ${d.commentSha256}`}>
          · comment {d.commentSha256.slice(0, 8)}
        </span>
      ) : null}
    </li>
  )
}

export function ApprovalGates({
  runId,
  runStatus,
  labelFor,
  onDecided,
}: {
  runId: string
  runStatus: string
  labelFor?: (nodeId: string) => string | undefined
  /** Refresh the run (status / logs) after a decision. */
  onDecided?: () => void
}) {
  const [data, setData] = React.useState<GatesPayload | null>(null)
  const [unsupported, setUnsupported] = React.useState(false)
  const seqRef = React.useRef(0)

  const load = React.useCallback(async () => {
    if (!runId) return
    const seq = ++seqRef.current
    try {
      const raw = await apiJson<unknown>(`/runs/${encodeURIComponent(runId)}/gates`, { retries: 0 })
      if (seq !== seqRef.current) return
      setData(parseGates(raw))
      setUnsupported(false)
    } catch (err) {
      if (seq !== seqRef.current) return
      if (err instanceof ApiError && err.status === 404) setUnsupported(true)
      setData(null)
    }
  }, [runId])

  React.useEffect(() => {
    setData(null)
    setUnsupported(false)
  }, [runId])

  const awaiting = isAwaitingApproval(runStatus) || Boolean(data?.awaitingApproval)
  // Immediate load on run / status change; 3 s poll only while a gate waits.
  usePolling(load, 3000, { enabled: !unsupported && awaiting, resetKey: `${runId}:${runStatus}` })
  React.useEffect(() => {
    if (!awaiting) void load()
  }, [awaiting, load, runStatus])

  if (unsupported || !data) return null
  const pending = data.gates.filter((g) => g.pending)
  const decided = data.gates.filter((g) => !g.pending && g.status !== 'not_reached' && g.status !== 'unknown')
  if (!pending.length && !decided.length) return null
  const after = () => {
    void load()
    onDecided?.()
  }
  return (
    <div className="space-y-2" aria-label="Approvals">
      {pending.map((g) => (
        <GateCard key={g.nodeId} runId={runId} gate={g} title={gateTitle(g, labelFor)} onDecided={after} />
      ))}
      {decided.length ? (
        <div className="rounded-xl border border-ink-200 bg-white">
          <div className="px-3 pt-2 text-[12px] font-semibold text-ink-700">Approvals</div>
          <ul className="divide-y divide-ink-50">
            {decided.map((g) => (
              <DecidedGateRow key={g.nodeId} gate={g} title={gateTitle(g, labelFor)} />
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
