/**
 * Who am I to the API (`GET /me`) + how an actor reads everywhere (Access,
 * header, run header / record, audit, Models "Used in").
 *
 * Contract: `GET /api/v1/me` → `{actor, actor_verified, token_mapped,
 * claimed_actor|null, auth_configured, token_map_configured}`. Older API
 * containers answer 404 → `fetchMe()` resolves null and callers hide the
 * verified-identity UI (the browser-local name field keeps working).
 *
 * Actor kinds:
 * - verified — a named API token mapped to this actor (`actor_verified: true`)
 * - self-declared — name from the `X-Actor` header only (`actor_verified: false`)
 * - unidentified — empty / "unidentified" / generic "api" / "anonymous"
 * - unknown — old records without `actor_verified`: just the name, no claim
 */
import React from 'react'
import { ApiError, apiJson } from '../api/client'
import { invalidateShared, sharedFetch } from './sharedFetch'

type Rec = Record<string, unknown>

function asRec(v: unknown): Rec | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null
}

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : typeof v === 'number' ? String(v) : ''
}

export type MeInfo = {
  actor: string
  actorVerified: boolean
  tokenMapped: boolean
  claimedActor: string
  authConfigured: boolean
  tokenMapConfigured: boolean
}

/** Parse `GET /me`; null when the body is not an object. */
export function parseMe(raw: unknown): MeInfo | null {
  const r = asRec(raw)
  if (!r) return null
  return {
    actor: str(r.actor),
    actorVerified: r.actor_verified === true,
    tokenMapped: r.token_mapped === true,
    claimedActor: str(r.claimed_actor),
    authConfigured: r.auth_configured === true,
    tokenMapConfigured: r.token_map_configured === true,
  }
}

const GENERIC_ACTORS = new Set(['', 'unidentified', 'api', 'anonymous', 'unknown', 'none', 'null'])

/** True for an empty / generic actor ("unidentified", "api", …). */
export function isUnidentifiedActor(actor: unknown): boolean {
  return GENERIC_ACTORS.has(str(actor).toLowerCase())
}

export type ActorKind = 'verified' | 'self-declared' | 'unidentified' | 'unknown'

export type ActorDisplay = {
  /** Visible name ("Unidentified" for generic actors). */
  name: string
  kind: ActorKind
  /** Short muted suffix ("(self-declared)") or ''. */
  suffix: string
  /** Tooltip: how the name was established (+ the claimed name when it differs). */
  title: string
}

/**
 * One display rule for an actor. `actorVerified` undefined/null = the record
 * predates verified identities (shown as the plain name, no suffix).
 */
export function actorDisplay(input: {
  actor: unknown
  actorVerified?: unknown
  claimedActor?: unknown
}): ActorDisplay {
  const actor = str(input.actor)
  const claimed = str(input.claimedActor)
  if (isUnidentifiedActor(actor)) {
    return {
      name: 'Unidentified',
      kind: 'unidentified',
      suffix: '',
      title: claimed
        ? `No verified identity — the caller claimed "${claimed}"`
        : 'No name was recorded — the caller used no named token and sent no name',
    }
  }
  const claimNote = claimed && claimed !== actor ? ` · claimed "${claimed}"` : ''
  if (input.actorVerified === true) {
    return { name: actor, kind: 'verified', suffix: '', title: `Verified — named API token${claimNote}` }
  }
  if (input.actorVerified === false) {
    return {
      name: actor,
      kind: 'self-declared',
      suffix: '(self-declared)',
      title: `Self-declared name (not backed by a named API token)${claimNote}`,
    }
  }
  return { name: actor, kind: 'unknown', suffix: '', title: actor }
}

/** `GET /me` (shared across components, cached 60 s). Resolves null on 404 / 405 (older API). */
export async function fetchMe(opts: { fresh?: boolean } = {}): Promise<MeInfo | null> {
  return sharedFetch(
    'me',
    async () => {
      try {
        return parseMe(await apiJson<unknown>('/me', { retries: 0, timeoutMs: 10000 }))
      } catch (err) {
        if (err instanceof ApiError && (err.status === 404 || err.status === 405)) return null
        throw err
      }
    },
    { maxAgeMs: 60_000, fresh: opts.fresh },
  )
}

/** Drop the cached `/me` (after the token or name changes). */
export function invalidateMe() {
  invalidateShared('me')
}

/**
 * Current identity. `me` is null while loading, on an older API (404) or on
 * error (`available` false); `refresh()` refetches (e.g. after Settings save).
 */
export function useMe(): { me: MeInfo | null; loaded: boolean; refresh: () => void } {
  const [me, setMe] = React.useState<MeInfo | null>(null)
  const [loaded, setLoaded] = React.useState(false)
  const [tick, setTick] = React.useState(0)
  React.useEffect(() => {
    let alive = true
    fetchMe({ fresh: tick > 0 })
      .then((m) => {
        if (alive) setMe(m)
      })
      .catch(() => {
        if (alive) setMe(null)
      })
      .finally(() => {
        if (alive) setLoaded(true)
      })
    return () => {
      alive = false
    }
  }, [tick])
  React.useEffect(() => {
    const onChange = () => setTick((t) => t + 1)
    window.addEventListener(IDENTITY_CHANGED_EVENT, onChange)
    return () => window.removeEventListener(IDENTITY_CHANGED_EVENT, onChange)
  }, [])
  const refresh = React.useCallback(() => setTick((t) => t + 1), [])
  return { me, loaded, refresh }
}

/** Fired after the API token or the self-declared name changes. */
export const IDENTITY_CHANGED_EVENT = 'graphyn:identity-changed'

export function notifyIdentityChanged() {
  invalidateMe()
  try {
    window.dispatchEvent(new Event(IDENTITY_CHANGED_EVENT))
  } catch {
    /* non-browser */
  }
}
