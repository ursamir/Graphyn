import React from 'react'
import { BadgeCheck, HelpCircle, KeyRound } from 'lucide-react'
import { WorkbenchPage } from '../../layout'
import { useAppStore } from '../../store/appStore'
import { notifyIdentityChanged, useMe } from '../../lib/identity'

/**
 * Access: who you are in the audit trail + API token settings.
 *
 * `GET /me` decides the mode: a named token (`actor_verified`) shows
 * "Signed in as <actor>" with a Verified badge and a read-only name (the
 * browser-local claimed name is irrelevant then). Otherwise the editable
 * "Your name in the audit trail" field (`graphyn.actor`, sent as `X-Actor`)
 * with a "Not verified" help tooltip. An older API (404) keeps the field only.
 */
export default function AccessView() {
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const { me } = useMe()
  const [actor, setActor] = React.useState(() => {
    try {
      return localStorage.getItem('graphyn.actor') || ''
    } catch {
      return ''
    }
  })

  const saveActor = () => {
    const v = actor.trim()
    try {
      const prev = localStorage.getItem('graphyn.actor') || ''
      if (v) localStorage.setItem('graphyn.actor', v)
      else localStorage.removeItem('graphyn.actor')
      if (prev !== v) notifyIdentityChanged()
    } catch {
      /* storage unavailable */
    }
  }

  const verified = me?.actorVerified === true

  return (
    <WorkbenchPage title="Access" description="Your identity and API token for this console.">
      <div className="w-full max-w-lg space-y-4">
        <section className="space-y-4 rounded-lg border border-ink-200 bg-white p-4">
          {verified ? (
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2 text-sm text-ink-800">
                <span>Signed in as</span>
                <span className="font-semibold text-ink-950">{me.actor}</span>
                <span
                  className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800 ring-1 ring-inset ring-emerald-200"
                  title="Your API token is mapped to this name by the administrator"
                >
                  <BadgeCheck className="h-3.5 w-3.5" /> Verified
                </span>
              </div>
              <label className="block text-[12px] text-ink-500">
                Name in the audit trail
                <input className="field-control mt-1 font-normal" value={me.actor} readOnly aria-readonly />
              </label>
              <p className="text-[12px] text-ink-500">
                Runs you start and model changes you make are recorded under this name. It comes from your API
                token, so it cannot be changed here.
              </p>
            </div>
          ) : (
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-ink-800">
                <span className="inline-flex items-center gap-1.5">
                  Your name in the audit trail
                  {me ? (
                    <span
                      className="inline-flex cursor-help items-center gap-1 text-[11px] font-normal text-ink-400"
                      title="Not verified — your administrator can give you a named token (GRAPHYN_API_TOKENS)"
                    >
                      <HelpCircle className="h-3.5 w-3.5" aria-hidden /> Not verified
                    </span>
                  ) : null}
                </span>
                <input
                  className="field-control mt-1.5 font-normal"
                  value={actor}
                  onChange={(e) => setActor(e.target.value)}
                  onBlur={saveActor}
                  placeholder="e.g. samir"
                  autoComplete="name"
                />
              </label>
              <p className="text-[12px] text-ink-500">
                Recorded as who started runs and changed models (shown as self-declared). Stored in this browser.
              </p>
            </div>
          )}
          <button type="button" className="btn-primary" onClick={() => setSettingsOpen(true)}>
            <KeyRound className="h-3.5 w-3.5" /> API token &amp; settings
          </button>
        </section>
      </div>
    </WorkbenchPage>
  )
}
