import React from 'react'
import { Search, X } from 'lucide-react'
import { useAppStore, type AppView } from '../store/appStore'
import { apiJson } from '../api/client'
import { shortRunId } from '../lib/format'

type PaletteItem = {
  id: string
  label: string
  hint?: string
  group: string
  keywords?: string
  run: () => void
}

const VIEW_JUMPS: Array<{ id: AppView; label: string; keywords?: string }> = [
  { id: 'projects', label: 'Home', keywords: 'home workspace projects j overview' },
  { id: 'builder', label: 'Editor', keywords: 'builder canvas pipeline b' },
  { id: 'runs', label: 'Runs', keywords: 'runs history r' },
  { id: 'data', label: 'Datasets', keywords: 'datasets inputs outputs d library' },
  { id: 'artifacts', label: 'Artifacts', keywords: 'artifacts files a browse registry' },
  { id: 'templates', label: 'Templates', keywords: 'starter build t' },
  { id: 'proposals', label: 'Proposals', keywords: 'pr agent p' },
  { id: 'plugins', label: 'Library · Plugins', keywords: 'catalog library plugins l' },
  { id: 'edge', label: 'Edge package', keywords: 'tflite deploy g edge' },
  { id: 'workers', label: 'Worker fleet', keywords: 'distributed gpu w workers fleet' },
  { id: 'secrets', label: 'Secrets', keywords: 'credentials k' },
  { id: 'system', label: 'Ops', keywords: 'health schedules admin s system ops' },
]

function fuzzyScore(query: string, text: string): number {
  const q = query.trim().toLowerCase()
  if (!q) return 1
  const t = text.toLowerCase()
  if (t === q) return 100
  if (t.startsWith(q)) return 80
  if (t.includes(q)) return 60
  // subsequence match
  let ti = 0
  for (let qi = 0; qi < q.length; qi++) {
    const ch = q[qi]
    const found = t.indexOf(ch, ti)
    if (found < 0) return 0
    ti = found + 1
  }
  return 30
}

function isTypingTarget(el: EventTarget | null): boolean {
  if (!el || !(el instanceof HTMLElement)) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

export function CommandPalette({
  open,
  onClose,
  onOpenChange,
}: {
  open: boolean
  onClose: () => void
  /** Optional controlled setter when parent also owns open state via shortcut */
  onOpenChange?: (open: boolean) => void
}) {
  const setView = useAppStore((s) => s.setView)
  const setFocusRunsTab = useAppStore((s) => s.setFocusRunsTab)
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const closeProject = useAppStore((s) => s.closeProject)
  const openRun = useAppStore((s) => s.openRun)
  const openProject = useAppStore((s) => s.openProject)
  const openData = useAppStore((s) => s.openData)
  const openArtifacts = useAppStore((s) => s.openArtifacts)
  const openEdge = useAppStore((s) => s.openEdge)
  const lastRunId = useAppStore((s) => s.lastRunId)
  const activeProject = useAppStore((s) => s.activeProject)

  const [query, setQuery] = React.useState('')
  const [activeIdx, setActiveIdx] = React.useState(0)
  const [projects, setProjects] = React.useState<Array<{ name: string }>>([])
  const [recentRuns, setRecentRuns] = React.useState<
    Array<{ run_id: string; status?: string; graph_name?: string; project?: string }>
  >([])
  const inputRef = React.useRef<HTMLInputElement | null>(null)

  const setOpen = React.useCallback(
    (next: boolean) => {
      if (onOpenChange) onOpenChange(next)
      else if (!next) onClose()
    },
    [onClose, onOpenChange],
  )

  React.useEffect(() => {
    if (!open) {
      setQuery('')
      setActiveIdx(0)
      return
    }
    const t = window.setTimeout(() => inputRef.current?.focus(), 0)
    let cancelled = false
    void (async () => {
      try {
        const [plist, runs] = await Promise.all([
          apiJson<Array<{ name: string }>>('/projects').catch(() => []),
          apiJson<Array<{ run_id: string; status?: string; graph_name?: string; project?: string }>>(
            '/runs',
            { query: { limit: 12, offset: 0, ...(activeProject ? { project: activeProject } : {}) } },
          ).catch(() => []),
        ])
        if (cancelled) return
        setProjects(Array.isArray(plist) ? plist : [])
        setRecentRuns(Array.isArray(runs) ? runs : [])
      } catch {
        if (!cancelled) {
          setProjects([])
          setRecentRuns([])
        }
      }
    })()
    return () => {
      cancelled = true
      window.clearTimeout(t)
    }
  }, [open, activeProject])

  const goView = React.useCallback(
    (id: AppView) => {
      setView(id)
      window.history.replaceState(null, '', `#/${id}`)
      setOpen(false)
    },
    [setView, setOpen],
  )

  const items = React.useMemo((): PaletteItem[] => {
    const out: PaletteItem[] = []
    if (activeProject) {
      out.push({
        id: 'workspace:switch',
        label: 'Switch project',
        hint: 'Show picker',
        group: 'Workspace',
        keywords: 'switch change workspace leave picker',
        run: () => {
          setView('projects')
          window.history.replaceState(null, '', '#/projects')
          window.dispatchEvent(new HashChangeEvent('hashchange'))
          setOpen(false)
        },
      })
      out.push({
        id: 'workspace:leave',
        label: 'Leave workspace',
        hint: activeProject,
        group: 'Workspace',
        keywords: 'close leave clear exit workspace',
        run: () => {
          closeProject()
          setView('projects')
          window.history.replaceState(null, '', '#/projects')
          window.dispatchEvent(new HashChangeEvent('hashchange'))
          setOpen(false)
        },
      })
      out.push({
        id: 'workspace:overview',
        label: 'Home',
        hint: activeProject,
        group: 'Workspace',
        keywords: 'overview home project',
        run: () => {
          openProject(activeProject)
          setOpen(false)
        },
      })
      out.push({
        id: 'workspace:data',
        label: 'Datasets',
        hint: activeProject,
        group: 'Workspace',
        keywords: 'data datasets library',
        run: () => {
          openData({ project: activeProject })
          setOpen(false)
        },
      })
      out.push({
        id: 'workspace:files',
        label: 'Artifacts',
        hint: activeProject,
        group: 'Workspace',
        keywords: 'artifacts files browse',
        run: () => {
          openArtifacts({ project: activeProject })
          setOpen(false)
        },
      })
      out.push({
        id: 'workspace:edge',
        label: 'Edge package',
        hint: activeProject,
        group: 'Workspace',
        keywords: 'edge tflite deploy package',
        run: () => {
          openEdge({ project: activeProject })
          setOpen(false)
        },
      })
    }
    out.push({
      id: 'runs:lineage',
      label: 'Runs → Lineage',
      hint: '#/trace',
      group: 'Runs panels',
      keywords: 'lineage trace provenance deep link o',
      run: () => goView('trace'),
    })
    out.push({
      id: 'runs:compare',
      label: 'Runs → Compare runs',
      hint: '#/runs?tab=compare',
      group: 'Runs panels',
      keywords: 'compare experiments metrics e',
      run: () => {
        setFocusRunsTab('compare')
        goView('runs')
        window.history.replaceState(null, '', '#/runs?tab=compare')
      },
    })
    for (const v of VIEW_JUMPS) {
      out.push({
        id: `view:${v.id}`,
        label: v.label,
        hint: `#/${v.id}`,
        group: 'Views',
        keywords: v.keywords,
        run: () => goView(v.id),
      })
    }
    if (lastRunId) {
      out.push({
        id: `run:last`,
        label: `Last run ${shortRunId(lastRunId)}`,
        hint: lastRunId,
        group: 'Runs',
        keywords: 'last recent',
        run: () => {
          openRun(lastRunId)
          setOpen(false)
        },
      })
    }
    for (const r of recentRuns.slice(0, 8)) {
      out.push({
        id: `run:${r.run_id}`,
        label: `${shortRunId(r.run_id)}${r.graph_name ? ` · ${r.graph_name}` : ''}`,
        hint: r.status || r.project || undefined,
        group: 'Runs',
        keywords: `${r.run_id} ${r.graph_name || ''} ${r.project || ''} ${r.status || ''}`,
        run: () => {
          openRun(r.run_id)
          setOpen(false)
        },
      })
    }
    for (const p of projects.slice(0, 20)) {
      out.push({
        id: `project:${p.name}`,
        label: p.name,
        hint: 'Open workspace',
        group: 'Projects',
        keywords: `project workspace ${p.name}`,
        run: () => {
          setActiveProject(p.name)
          openProject(p.name)
          setOpen(false)
        },
      })
    }
    return out
  }, [goView, lastRunId, recentRuns, projects, openRun, openProject, setActiveProject, setOpen, activeProject, closeProject, setView, openArtifacts, openEdge, setFocusRunsTab])

  const filtered = React.useMemo(() => {
    const scored = items
      .map((item) => {
        const hay = `${item.label} ${item.hint || ''} ${item.keywords || ''} ${item.group}`
        return { item, score: fuzzyScore(query, hay) }
      })
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
    return scored.map((x) => x.item)
  }, [items, query])

  React.useEffect(() => {
    setActiveIdx(0)
  }, [query, open])

  React.useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        setOpen(false)
        return
      }
      if (e.key === 'Tab') {
        const root = document.getElementById('command-palette-dialog')
        if (!root) return
        const focusables = root.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        )
        if (focusables.length === 0) return
        const first = focusables[0]
        const last = focusables[focusables.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
        return
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveIdx((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0)))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIdx((i) => Math.max(i - 1, 0))
        return
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        const item = filtered[activeIdx]
        if (item) item.run()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, filtered, activeIdx, setOpen])

  if (!open) return null

  const groups = Array.from(new Set(filtered.map((i) => i.group)))

  return (
    <div
      className="fixed inset-0 z-[130] flex items-start justify-center bg-ink-950/40 p-4 pt-[12vh] backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="command-palette-title"
      onClick={() => setOpen(false)}
    >
      <div
        id="command-palette-dialog"
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-ink-200 bg-white shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-ink-100 px-3 py-2.5">
          <Search className="h-4 w-4 shrink-0 text-ink-400" />
          <input
            ref={inputRef}
            id="command-palette-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Jump to view, project, or run…"
            className="min-w-0 flex-1 bg-transparent text-[14px] text-ink-900 outline-none placeholder:text-ink-400"
            aria-labelledby="command-palette-title"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="hidden rounded border border-ink-200 bg-ink-50 px-1.5 py-0.5 font-mono text-[10px] text-ink-500 sm:inline">
            Esc
          </kbd>
          <button type="button" className="btn-icon" aria-label="Close command palette" onClick={() => setOpen(false)}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <h2 id="command-palette-title" className="sr-only">
          Command palette
        </h2>
        <ul className="max-h-[50vh] overflow-y-auto py-1" role="listbox">
          {filtered.length === 0 ? (
            <li className="px-4 py-6 text-center text-[13px] text-ink-500">No matches</li>
          ) : (
            groups.map((group) => {
              const groupItems = filtered.filter((i) => i.group === group)
              return (
                <li key={group} role="presentation">
                  <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                    {group}
                  </div>
                  <ul>
                    {groupItems.map((item) => {
                      const idx = filtered.indexOf(item)
                      const active = idx === activeIdx
                      return (
                        <li key={item.id} role="option" aria-selected={active}>
                          <button
                            type="button"
                            className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-[13px] ${
                              active ? 'bg-accent-50 text-accent-950' : 'text-ink-800 hover:bg-ink-50'
                            }`}
                            onMouseEnter={() => setActiveIdx(idx)}
                            onClick={() => item.run()}
                          >
                            <span className="min-w-0 truncate font-medium">{item.label}</span>
                            {item.hint ? (
                              <span className="shrink-0 truncate font-mono text-[11px] text-ink-400">{item.hint}</span>
                            ) : null}
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </li>
              )
            })
          )}
        </ul>
        <div className="border-t border-ink-100 px-3 py-2 text-[11px] text-ink-400">
          ↑↓ navigate · Enter open · Esc close · ⌘/Ctrl+K or / to open
        </div>
      </div>
    </div>
  )
}

/** Global Cmd/Ctrl+K and / (when not typing) — call from App. */
export function useCommandPaletteHotkeys(
  open: boolean,
  setOpen: (open: boolean) => void,
  blocked: boolean,
) {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (blocked) return
      if (open) return
      const metaK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k'
      const slash = e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey
      if (metaK) {
        e.preventDefault()
        setOpen(true)
        return
      }
      if (slash && !isTypingTarget(e.target)) {
        e.preventDefault()
        setOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, setOpen, blocked])
}
