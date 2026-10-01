/**
 * Request de-duplication for endpoints several components read (pending
 * proposals badge + Agent inbox, notifications, run existence checks).
 *
 * `sharedFetch(key, fn)` returns the in-flight promise for `key` when one is
 * pending, or a result younger than `maxAgeMs`; otherwise it calls `fn`.
 * `fresh: true` skips the age cache (but still joins an in-flight request and
 * becomes the in-flight request others join) — use it right after a mutation.
 */

type Entry = { promise: Promise<unknown>; at: number; settled: boolean }

const entries = new Map<string, Entry>()

export function sharedFetch<T>(
  key: string,
  fn: () => Promise<T>,
  opts: { maxAgeMs?: number; fresh?: boolean } = {},
): Promise<T> {
  const { maxAgeMs = 2000, fresh = false } = opts
  const cur = entries.get(key)
  if (cur && !cur.settled) return cur.promise as Promise<T>
  if (cur && !fresh && Date.now() - cur.at < maxAgeMs) return cur.promise as Promise<T>
  const entry: Entry = { promise: Promise.resolve(), at: Date.now(), settled: false }
  const promise = fn().then(
    (v) => {
      entry.settled = true
      entry.at = Date.now()
      return v
    },
    (err: unknown) => {
      entry.settled = true
      // Never cache failures.
      if (entries.get(key) === entry) entries.delete(key)
      throw err
    },
  )
  entry.promise = promise
  entries.set(key, entry)
  return promise
}

/** Drop a cached result (e.g. after a mutation the caller cannot `fresh`-refetch). */
export function invalidateShared(key: string) {
  entries.delete(key)
}
