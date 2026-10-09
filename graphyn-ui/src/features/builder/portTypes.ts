/**
 * Port type labels and wire-time compatibility (F19 / F-22).
 *
 * The backend publishes canonical labels such as
 * `builtins.list[app.models.audio_sample.AudioSample]` or `builtins.object | None`;
 * people should read `list[AudioSample]` and `any`.
 */

/** Backend answer from `GET /nodes/check-connection`. */
export type ConnectionCheck = {
  compatible: boolean
  source_type?: string | null
  target_type?: string | null
  reason?: string | null
}

const DOTTED = /[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*)+/g

/** `builtins.list[app.x.AudioSample] | None` → `list[AudioSample] | None`; `object` → `any`. */
export function shortTypeLabel(label?: string | null): string {
  if (!label) return ''
  const short = label
    .replace(DOTTED, (m) => m.slice(m.lastIndexOf('.') + 1))
    .replace(/\bobject\b/g, 'any')
    .replace(/\bAny\b/g, 'any')
  // `any | None` is still just "any".
  return /^any( \| None)?$/.test(short) || /^None \| any$/.test(short) ? 'any' : short
}

/** Toast text when the backend refuses a connection, or null when the wire is allowed. */
export function connectionRefusal(check: ConnectionCheck | null | undefined): string | null {
  if (!check || check.compatible !== false) return null
  if (check.source_type && check.target_type) {
    return `Can't connect: this output is ${shortTypeLabel(check.source_type)}, but the input expects ${shortTypeLabel(check.target_type)}.`
  }
  return `Can't connect: ${check.reason ?? 'these ports are not compatible.'}`
}
