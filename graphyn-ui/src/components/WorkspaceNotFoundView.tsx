import { FolderX } from 'lucide-react'
import { navigatePath } from '../routes/parsePath'
import { paths } from '../routes/paths'
import { useAppStore } from '../store/appStore'

/**
 * `/workspaces/<id>/…` where `<id>` does not exist (GET /projects/<id> → 404).
 * Replaces the full dashboard that used to render for any id — with Open
 * Editor enabled and the bogus id saved as the active/recent workspace.
 * Every workspace-scoped route (editor/runs/models/ship/datasets) under an
 * invalid id renders this same view.
 */
export function WorkspaceNotFoundView({
  workspaceId,
  fallback,
}: {
  workspaceId: string
  /** Most recent workspace that still exists, if any. */
  fallback?: string | null
}) {
  const setView = useAppStore((s) => s.setView)
  const go = (path: string) => {
    setView('projects')
    navigatePath(path)
  }
  return (
    <div className="flex h-full items-center justify-center overflow-y-auto p-6" data-testid="workspace-not-found">
      <div className="empty-state-shell mx-auto max-w-md py-10">
        <div
          className="mb-3 flex h-10 w-10 items-center justify-center rounded-2xl border border-ink-200/60 bg-white text-ink-400 shadow-sm"
          aria-hidden
        >
          <FolderX className="h-5 w-5" strokeWidth={1.75} />
        </div>
        <h1 className="text-type-section tracking-tight text-ink-900">Workspace not found</h1>
        <p className="mt-2 text-type-body leading-relaxed text-ink-500">
          There is no workspace named{' '}
          <code className="break-all rounded bg-ink-100 px-1 py-0.5 font-mono text-[12px] text-ink-800">
            {workspaceId}
          </code>
          . It may have been deleted or renamed.
        </p>
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {fallback ? (
            <button type="button" className="btn-primary" onClick={() => go(paths.workspace(fallback))}>
              Open {fallback}
            </button>
          ) : null}
          <button
            type="button"
            className={fallback ? 'btn-secondary' : 'btn-primary'}
            onClick={() => go(paths.workspaces())}
          >
            All workspaces
          </button>
        </div>
      </div>
    </div>
  )
}
