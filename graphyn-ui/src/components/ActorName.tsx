/**
 * Actor name with its identity proof: verified tick (named API token),
 * muted "(self-declared)", or muted "Unidentified". Tooltip carries how the
 * name was established and the claimed name when it differs.
 */
import clsx from 'clsx'
import { BadgeCheck } from 'lucide-react'
import { actorDisplay } from '../lib/identity'

export function ActorName({
  actor,
  verified,
  claimed,
  className,
  compact = false,
  bold = false,
}: {
  actor: unknown
  verified?: unknown
  claimed?: unknown
  className?: string
  /** Hide the "(self-declared)" word (tooltip still says it). */
  compact?: boolean
  bold?: boolean
}) {
  const d = actorDisplay({ actor, actorVerified: verified, claimedActor: claimed })
  if (d.kind === 'unidentified') {
    return (
      <span className={clsx('text-ink-400', className)} title={d.title}>
        {d.name}
      </span>
    )
  }
  return (
    <span className={clsx('inline-flex min-w-0 items-center gap-0.5 align-middle', className)} title={d.title}>
      <span className={clsx('truncate', bold && 'font-medium')}>{d.name}</span>
      {d.kind === 'verified' ? (
        <BadgeCheck className="h-3.5 w-3.5 shrink-0 text-emerald-600" aria-label="verified" />
      ) : null}
      {d.suffix && !compact ? <span className="shrink-0 text-ink-400">{d.suffix}</span> : null}
    </span>
  )
}
