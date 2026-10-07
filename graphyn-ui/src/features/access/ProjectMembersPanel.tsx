import React from 'react'
import { apiJson } from '../../api/client'
import { unwrapList } from '../../api/unwrapList'
import { ConfirmButton, ErrorBanner } from '../../components/ui'
import { useAppStore } from '../../store/appStore'
import { PROJECT_ROLE_OPTIONS, cleanError, type MemberRow, type UserRow } from './accessApi'

/**
 * Per-project membership: users only see projects they belong to (admins,
 * operators and auditors see all). Owners and user admins manage members.
 */
export function ProjectMembersPanel({ canListUsers }: { canListUsers: boolean }) {
  const pushToast = useAppStore((s) => s.pushToast)
  const activeProject = useAppStore((s) => s.activeProject)
  const [projects, setProjects] = React.useState<string[]>([])
  const [project, setProject] = React.useState<string>(activeProject || '')
  const [members, setMembers] = React.useState<MemberRow[] | null>(null)
  const [users, setUsers] = React.useState<UserRow[]>([])
  const [addUser, setAddUser] = React.useState('')
  const [addRole, setAddRole] = React.useState<string>('builder')
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    apiJson('/projects')
      .then((raw) => {
        const names = unwrapList<{ name: string } | string>(raw)
          .map((p) => (typeof p === 'string' ? p : p.name))
          .filter(Boolean)
        setProjects(names)
        setProject((cur) => cur || names[0] || '')
      })
      .catch((err) => setError(cleanError(err)))
    if (canListUsers) {
      apiJson<UserRow[]>('/users')
        .then(setUsers)
        .catch(() => setUsers([]))
    }
  }, [canListUsers])

  const load = React.useCallback(async () => {
    if (!project) return
    try {
      setMembers(await apiJson<MemberRow[]>(`/projects/${encodeURIComponent(project)}/members`))
      setError(null)
    } catch (err) {
      setMembers(null)
      setError(cleanError(err))
    }
  }, [project])
  React.useEffect(() => {
    void load()
  }, [load])

  const setRole = async (userId: string, role: string) => {
    try {
      setMembers(
        await apiJson<MemberRow[]>(`/projects/${encodeURIComponent(project)}/members/${encodeURIComponent(userId)}`, {
          method: 'PUT',
          body: JSON.stringify({ role }),
        }),
      )
      pushToast('Membership saved', 'success')
    } catch (err) {
      setError(cleanError(err))
    }
  }

  const candidates = users.filter((u) => !(members ?? []).some((m) => m.user_id === u.id))

  return (
    <div className="w-full max-w-3xl space-y-4">
      {error ? <ErrorBanner message={error} onDismiss={() => setError(null)} /> : null}
      <label className="block max-w-xs text-[12px] text-ink-600">
        Project
        <select className="field-control mt-1" value={project} onChange={(e) => setProject(e.target.value)}>
          {projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>
      <section className="space-y-3 rounded-lg border border-ink-200 bg-white p-4">
        <ul className="divide-y divide-ink-100 text-[13px]">
          {(members ?? []).map((m) => (
            <li key={m.user_id} className="flex flex-wrap items-center gap-2 py-1.5">
              <span className="font-medium text-ink-900">{m.username}</span>
              {m.added_by ? <span className="text-[11px] text-ink-400">added by {m.added_by}</span> : null}
              <select
                className="field-control ml-auto w-32"
                aria-label={`Role of ${m.username}`}
                value={m.role}
                onChange={(e) => void setRole(m.user_id, e.target.value)}
              >
                {PROJECT_ROLE_OPTIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <ConfirmButton
                label="Remove"
                danger
                onConfirm={() =>
                  void apiJson<MemberRow[]>(
                    `/projects/${encodeURIComponent(project)}/members/${encodeURIComponent(m.user_id)}`,
                    { method: 'DELETE' },
                  )
                    .then(setMembers)
                    .catch((err) => setError(cleanError(err)))
                }
              />
            </li>
          ))}
          {members && members.length === 0 ? (
            <li className="py-1.5 text-[12px] text-ink-500">
              No members yet — only admins, operators and auditors can see this project.
            </li>
          ) : null}
        </ul>
        {canListUsers ? (
          <div className="flex flex-wrap items-end gap-2 border-t border-ink-100 pt-3">
            <label className="block flex-1 text-[12px] text-ink-600">
              Add user
              <select className="field-control mt-1" value={addUser} onChange={(e) => setAddUser(e.target.value)}>
                <option value="">Choose a user…</option>
                {candidates.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username}
                  </option>
                ))}
              </select>
            </label>
            <label className="block w-32 text-[12px] text-ink-600">
              Role
              <select className="field-control mt-1" value={addRole} onChange={(e) => setAddRole(e.target.value)}>
                {PROJECT_ROLE_OPTIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn-primary"
              disabled={!addUser || !project}
              onClick={() => {
                void setRole(addUser, addRole)
                setAddUser('')
              }}
            >
              Add member
            </button>
          </div>
        ) : null}
      </section>
    </div>
  )
}
