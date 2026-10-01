/**
 * Client-side workspace name rule — mirrors the server's ProjectManager
 * `_validate_name` (letters, digits, hyphens, underscores; 1–128 chars).
 */

export const WORKSPACE_NAME_MAX = 128
export const WORKSPACE_NAME_RE = /^[A-Za-z0-9_-]{1,128}$/
export const WORKSPACE_NAME_HINT = 'Letters, digits, hyphens and underscores only (1–128 characters).'

/** `null` when valid; otherwise a short inline message. Empty input → null (nothing typed yet). */
export function workspaceNameError(raw: string): string | null {
  const name = raw.trim()
  if (!name) return null
  if (name.length > WORKSPACE_NAME_MAX) return `Too long — ${name.length}/${WORKSPACE_NAME_MAX} characters.`
  if (!WORKSPACE_NAME_RE.test(name)) {
    const bad = Array.from(new Set(name.replace(/[A-Za-z0-9_-]/g, '').split(''))).map((c) =>
      c === ' ' ? 'space' : c,
    )
    return `Not allowed: ${bad.join(' ')}. ${WORKSPACE_NAME_HINT}`
  }
  return null
}

export function isValidWorkspaceName(raw: string): boolean {
  const name = raw.trim()
  return Boolean(name) && WORKSPACE_NAME_RE.test(name)
}

/**
 * Server errors speak "project" (the API resource); the console calls the
 * concept a workspace. Rephrase the common ones for user-facing toasts.
 */
export function workspaceErrorMessage(message: string): string {
  if (/invalid project name/i.test(message)) {
    const m = /invalid project name\s+(['"])(.*?)\1/i.exec(message)
    return `Invalid workspace name${m ? ` “${m[2]}”` : ''}. ${WORKSPACE_NAME_HINT}`
  }
  const nf = /project\s+'([^']+)'\s+not found/i.exec(message)
  if (nf) return `Workspace “${nf[1]}” not found.`
  const exists = /project\s+'?([^'\s]+)'?\s+already exists/i.exec(message)
  if (exists) return `Workspace “${exists[1]}” already exists.`
  return message.replace(/\bproject\b/g, 'workspace').replace(/\bProject\b/g, 'Workspace')
}
