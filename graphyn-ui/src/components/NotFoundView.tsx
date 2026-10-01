import { Compass } from 'lucide-react'
import { navigatePath, suggestRouteFor } from '../routes/parsePath'
import { paths } from '../routes/paths'
import { useAppStore } from '../store/appStore'

/**
 * Unknown URL (e.g. `/plugins`, `/credentials`). Replaces the old silent
 * redirect to Home: say the page does not exist, show the path, and offer
 * Home plus the closest real route.
 */
export function NotFoundView({ pathname }: { pathname: string }) {
  const activeProject = useAppStore((s) => s.activeProject)
  const suggestion = suggestRouteFor(pathname, activeProject)
  const home = activeProject ? paths.workspace(activeProject) : paths.workspaces()
  const go = (path: string) => navigatePath(path)
  return (
    <div className="flex h-full items-center justify-center overflow-y-auto p-6" data-testid="not-found">
      <div className="empty-state-shell mx-auto max-w-md py-10">
        <div
          className="mb-3 flex h-10 w-10 items-center justify-center rounded-2xl border border-ink-200/60 bg-white text-ink-400 shadow-sm"
          aria-hidden
        >
          <Compass className="h-5 w-5" strokeWidth={1.75} />
        </div>
        <h1 className="text-type-section tracking-tight text-ink-900">Page not found</h1>
        <p className="mt-2 text-type-body leading-relaxed text-ink-500">
          Nothing lives at{' '}
          <code className="break-all rounded bg-ink-100 px-1 py-0.5 font-mono text-[12px] text-ink-800">
            {pathname}
          </code>
          .
        </p>
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {suggestion && suggestion.path !== home ? (
            <button type="button" className="btn-primary" onClick={() => go(suggestion.path)}>
              Go to {suggestion.label}
            </button>
          ) : null}
          <button
            type="button"
            className={suggestion && suggestion.path !== home ? 'btn-secondary' : 'btn-primary'}
            onClick={() => go(home)}
          >
            {activeProject ? `Home · ${activeProject}` : 'Workspaces'}
          </button>
        </div>
        {suggestion && suggestion.path !== home ? (
          <p className="mt-3 text-[11px] text-ink-400">
            Did you mean <code className="font-mono">{suggestion.path}</code>?
          </p>
        ) : null}
      </div>
    </div>
  )
}
