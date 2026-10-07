/** Types + tiny helpers for Admin → Access (users, roles, tokens, members). */

export const ROLE_OPTIONS = [
  { id: 'admin', hint: 'Everything, including users and system settings' },
  { id: 'operator', hint: 'Run pipelines, manage workers, plugins and credentials' },
  { id: 'builder', hint: 'Build and run pipelines' },
  { id: 'approver', hint: 'Approve gates and promotions' },
  { id: 'auditor', hint: 'Read everything, including the audit log' },
  { id: 'viewer', hint: 'Read only (per-project roles add more)' },
] as const

export const PROJECT_ROLE_OPTIONS = ['owner', 'builder', 'approver', 'viewer'] as const

export type UserRow = {
  id: string
  username: string
  display_name: string
  roles: string[]
  approver_roles: string[]
  disabled: boolean
  created_at: string | null
  created_by: string | null
  last_login_at: string | null
  memberships: Record<string, string>
}

export type CredentialRow = {
  id: string
  kind: string
  name: string
  created_at: string | null
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  created_by: string | null
  active: boolean
}

export type MemberRow = {
  user_id: string
  username: string
  display_name: string
  role: string
  added_at: string | null
  added_by: string | null
}

/** "a, b ,,c" → ["a","b","c"] */
export function splitList(raw: string): string[] {
  return raw
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)
}

/** Strip the generic 401 prefix the API client adds; keep the server's reason. */
export function cleanError(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err)
  return msg.replace(/^Unauthorized — set API token in Settings\. \((.*)\)$/, '$1')
}
