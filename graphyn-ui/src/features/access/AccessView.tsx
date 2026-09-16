import React from 'react'
import { KeyRound, Users } from 'lucide-react'
import { PageHeader, EmptyState } from '../../components/ui'
import { useAppStore } from '../../store/appStore'

/** Access / RBAC surface — product shell; full IAM needs backend roles (Phase C). */
export default function AccessView() {
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const [actor, setActor] = React.useState(() => localStorage.getItem('graphyn.actor') || '')

  const saveActor = () => {
    const v = actor.trim()
    if (v) localStorage.setItem('graphyn.actor', v)
    else localStorage.removeItem('graphyn.actor')
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6 space-y-4">
      <PageHeader
        title="Access"
        description="Actors, tokens, and roles. Full RBAC lands with the multi-user API; today you set the actor identity and API token."
      />
      <div className="max-w-lg space-y-4 rounded-2xl border border-ink-200 bg-white p-5 shadow-sm">
        <label className="block text-sm text-ink-700">
          Actor name <span className="text-ink-400">(sent as X-Actor on mutations)</span>
          <input
            className="field-control mt-1.5"
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            onBlur={saveActor}
            placeholder="e.g. samir / ci-bot"
          />
        </label>
        <p className="text-[12px] text-ink-500">
          Saved to <code className="font-mono text-[11px]">graphyn.actor</code> in localStorage. Roles
          (admin / prod-approve / secret-write) are pending the multi-user Access API.
        </p>
        <button type="button" className="btn-primary" onClick={() => setSettingsOpen(true)}>
          <KeyRound className="h-3.5 w-3.5" /> API token &amp; Settings
        </button>
      </div>
      <EmptyState
        title="Roles coming with multi-user API"
        description="Prod approve, admin Ops, and secret write will gate on roles once Access APIs ship. Actor chips already flow into audit."
        action={
          <div className="inline-flex items-center gap-2 text-sm text-ink-500">
            <Users className="h-4 w-4" /> Plan id C4
          </div>
        }
      />
    </div>
  )
}
