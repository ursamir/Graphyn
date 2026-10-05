/**
 * Approval gates (`hitl_approve` nodes) of a run: parsing of
 * `GET /runs/{id}/gates` and the per-card UI state. Pure + unit-tested
 * (gates.test.ts). Every field is optional so older APIs degrade.
 */

export type GateStatus =
  | 'not_reached'
  | 'pending'
  | 'decided'
  | 'approved'
  | 'rejected'
  | 'expired'
  | 'unattended'
  | 'unknown'

export type GateDecision = {
  approved: boolean | null
  approver: string
  role: string
  decidedAt: string
  actorVerified: boolean | null
  source: string
  commentSha256: string
}

export type Gate = {
  nodeId: string
  gateId: string
  label: string
  prompt: string
  status: GateStatus
  pending: boolean
  requestId: string
  requestedAt: string
  waitingSince: string
  timeoutS: number | null
  expiresAt: string
  approverRoles: string[]
  reasonRequired: boolean
  decision: GateDecision | null
  outcome: string
}

export type GatesPayload = { runId: string; runStatus: string; awaitingApproval: boolean; gates: Gate[] }

type Rec = Record<string, unknown>
const rec = (v: unknown): Rec | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null)
const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : v == null ? '' : String(v))
const boolOrNull = (v: unknown): boolean | null => (typeof v === 'boolean' ? v : null)

const STATUSES = new Set<GateStatus>(['not_reached', 'pending', 'decided', 'approved', 'rejected', 'expired', 'unattended'])

export function parseGate(raw: unknown): Gate | null {
  const r = rec(raw)
  if (!r) return null
  const nodeId = str(r.node_id)
  if (!nodeId) return null
  const st = str(r.status).toLowerCase() as GateStatus
  const d = rec(r.decision)
  const timeout = Number(r.timeout_s)
  return {
    nodeId,
    gateId: str(r.gate_id),
    label: str(r.label),
    prompt: str(r.prompt),
    status: STATUSES.has(st) ? st : 'unknown',
    pending: Boolean(r.pending) || st === 'pending',
    requestId: str(r.request_id),
    requestedAt: str(r.requested_at),
    waitingSince: str(r.waiting_since) || str(r.requested_at),
    timeoutS: Number.isFinite(timeout) ? timeout : null,
    expiresAt: str(r.expires_at),
    approverRoles: Array.isArray(r.approver_roles) ? r.approver_roles.map(str).filter(Boolean) : [],
    reasonRequired: Boolean(r.reason_required),
    decision: d
      ? {
          approved: boolOrNull(d.approved),
          approver: str(d.approver),
          role: str(d.role),
          decidedAt: str(d.decided_at),
          actorVerified: boolOrNull(d.actor_verified),
          source: str(d.source),
          commentSha256: str(d.comment_sha256),
        }
      : null,
    outcome: str(r.outcome),
  }
}

export function parseGates(raw: unknown): GatesPayload {
  const r = rec(raw) || {}
  const gates = (Array.isArray(r.gates) ? r.gates : []).map(parseGate).filter((g): g is Gate => g !== null)
  return {
    runId: str(r.run_id),
    runStatus: str(r.run_status),
    awaitingApproval: Boolean(r.awaiting_approval) || gates.some((g) => g.pending),
    gates,
  }
}

export type GateCardState = {
  /** Pending and actionable (Approve / Reject shown). */
  canDecide: boolean
  /** Comment is required and still empty → buttons disabled. */
  needsComment: boolean
  /** Role field shown (the gate restricts approver roles). */
  needsRole: boolean
  /** Short headline ("Waiting for approval", "Approved", "Rejected", "Expired", …). */
  headline: string
  tone: 'pending' | 'ok' | 'bad' | 'muted'
  /** Reason the buttons are disabled (tooltip), or ''. */
  disabledReason: string
}

/** UI state of one approval card given the current comment / role text. */
export function gateCardState(gate: Gate, comment: string, role = '', busy = false): GateCardState {
  const approved =
    gate.status === 'approved' ||
    gate.status === 'unattended' ||
    (gate.status === 'decided' && gate.decision?.approved === true) ||
    /approv/i.test(gate.outcome)
  const rejected =
    gate.status === 'rejected' ||
    (gate.status === 'decided' && gate.decision?.approved === false) ||
    /reject/i.test(gate.outcome)
  const canDecide = gate.pending
  const needsComment = canDecide && gate.reasonRequired && !comment.trim()
  const needsRole = canDecide && gate.approverRoles.length > 0
  const roleMissing = needsRole && !role.trim()
  let headline = 'Not reached yet'
  let tone: GateCardState['tone'] = 'muted'
  if (canDecide) {
    headline = 'Waiting for approval'
    tone = 'pending'
  } else if (gate.status === 'expired') {
    headline = 'Expired — no decision in time'
    tone = 'bad'
  } else if (gate.status === 'unattended') {
    headline = 'Passed unattended'
    tone = 'ok'
  } else if (approved) {
    headline = 'Approved'
    tone = 'ok'
  } else if (rejected) {
    headline = 'Rejected'
    tone = 'bad'
  } else if (gate.status === 'decided') {
    headline = 'Decided'
  }
  return {
    canDecide,
    needsComment,
    needsRole,
    headline,
    tone,
    disabledReason: busy
      ? 'Sending…'
      : needsComment
        ? 'A reason is required for this gate'
        : roleMissing
          ? 'Pick the role you approve as'
          : '',
  }
}

/** Gate title: label, else prompt's first line, else the node id. */
export function gateTitle(gate: Gate, labelFor?: (nodeId: string) => string | undefined): string {
  // A backend path-suffixed label ("Hitl approve · Path C") loses to the run view's step name.
  const pathy = /\s·\sPath [A-Z]\b/.test(gate.label || '')
  if (gate.label && !pathy) return gate.label
  return labelFor?.(gate.nodeId) || (gate.label ? gate.label.replace(/\s·\sPath [A-Z].*$/, '') : '') || gate.nodeId
}

/** Readable message for a decision error (409 / 422 codes). */
export function gateErrorText(code: string | null, fallback: string): string {
  switch (code) {
    case 'gate_not_pending':
      return 'This gate is no longer waiting for a decision — refreshing.'
    case 'gate_already_decided':
      return 'Someone already decided this gate — refreshing.'
    default:
      return fallback
  }
}
