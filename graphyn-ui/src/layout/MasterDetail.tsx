/**
 * App-wide Master | Detail (or stacked Container | Content) pane — responsive.
 *
 * ── API ────────────────────────────────────────────────────────────────────
 *   <MasterDetail
 *     master={list} detail={detail}
 *     listLabel="runs"            // a11y + button text ("Runs")
 *     collapsible                  // user may hide the list (split mode)
 *     storageKey="graphyn.runs"    // per-page key; collapsed state persists at `${storageKey}.collapsed`
 *                                  //   (default: `graphyn.layout.md.<listLabel>`)
 *     defaultCollapsed={false}     // used until the user toggles once
 *     selectedKey={runId ?? null}  // selection id: closes the overlay list and drives phone list/detail
 *     onBack={() => clearSel()}    // phone: "‹ Runs" back button (optional; default just shows the list)
 *     widthKey / defaultSize / minSize / maxSize / orientation / *ClassName  // as before
 *   />
 *
 *   Import everything from `../../layout` (index.ts): MasterDetail,
 *   MasterDetailToggle, useMasterDetail (hook lives in masterDetailContext.ts).
 *   In the detail header render `<MasterDetailToggle />` (or build your own with
 *   `useMasterDetail()` → { mode, collapsed, setCollapsed, collapsible, isOverlay,
 *   listOpen, openList, closeList, toggleList, listLabel, inMasterDetail }).
 *   When a toggle is mounted, MasterDetail hides its built-in fallback controls.
 *
 * ── Rules (viewport width, lib/viewport.ts `masterDetailModeFor`) ────────────
 *   ≥ 1024  split   — list | detail; list collapsible by the USER only. The
 *                     collapsed state is persisted per page and never changed by
 *                     the page itself (e.g. switching detail tabs).
 *   768–1023 overlay — detail full width; list is an overlay drawer opened from
 *                     the toggle ("Runs ▾"); closes on selection / backdrop / Esc.
 *   < 768   stack   — list OR detail. List first (when `selectedKey` is null);
 *                     a back button in the detail returns to the list.
 *   Items in the list close the drawer on click when they match
 *   `[data-md-select]`, `li button`, `li a` or `[role=option]`; mark filter
 *   controls inside `<li>` with `data-md-keep-open` to opt out.
 */
import React from 'react'
import clsx from 'clsx'
import { ChevronLeft, ChevronDown, PanelLeftClose, PanelLeftOpen, List } from 'lucide-react'
import { SplitPane } from '../components/SplitPane'
import { LAYOUT_KEYS } from './keys'
import { useLayoutPrefs } from './useLayoutPrefs'
import {
  masterDetailModeFor,
  stackShowsDetail,
  useViewport,
} from '../lib/viewport'
import { MasterDetailContext, useMasterDetail, type MasterDetailContextValue } from './masterDetailContext'

type MasterDetailProps = {
  master: React.ReactNode
  detail: React.ReactNode
  /**
   * Per-page persistence key. The user's collapsed choice is stored at
   * `${storageKey}.collapsed`. Default: `graphyn.layout.md.<listLabel>`.
   */
  storageKey?: string
  /** Divider width key (rare). Default: shared app master width (LAYOUT_KEYS.master). */
  widthKey?: string
  defaultSize?: number
  minSize?: number
  maxSize?: number
  className?: string
  masterClassName?: string
  detailClassName?: string
  /** Force orientation; otherwise follows layout mode. */
  orientation?: 'horizontal' | 'vertical'
  /** Allow collapsing the master list to give detail more room. */
  collapsible?: boolean
  /** Initial collapsed state before the user has toggled on this page. */
  defaultCollapsed?: boolean
  /** Accessible name for the master list (collapse controls). */
  listLabel?: string
  /**
   * Current selection id (null = nothing selected). Changing it closes the
   * overlay list; on phones `null` shows the list and a value shows the detail.
   * Omit when the page has no selection concept (detail always shown).
   */
  selectedKey?: string | null
  /** Phone back button handler (e.g. clear the selection). */
  onBack?: () => void
}

function readCollapsed(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    if (v === '1') return true
    if (v === '0') return false
  } catch {
    /* ignore */
  }
  return fallback
}

function capitalize(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s
}

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'list'
}

const SELECT_TARGET = '[data-md-select], li button, li a, [role="option"]'

export function MasterDetail({
  master,
  detail,
  storageKey,
  widthKey,
  defaultSize = 360,
  minSize = 280,
  maxSize = 640,
  className,
  masterClassName,
  detailClassName,
  orientation: orientationProp,
  collapsible = false,
  defaultCollapsed = false,
  listLabel = 'list',
  selectedKey,
  onBack,
}: MasterDetailProps) {
  const { mode: layoutMode } = useLayoutPrefs()
  const { width } = useViewport()
  const mode = masterDetailModeFor(width)
  const stacked = layoutMode === 'container-content'
  const orientation = orientationProp ?? (stacked ? 'vertical' : 'horizontal')
  const sizeKey =
    widthKey ?? (orientation === 'vertical' ? LAYOUT_KEYS.stack : LAYOUT_KEYS.master)
  const collapsedKey = `${storageKey ?? `graphyn.layout.md.${slug(listLabel)}`}.collapsed`

  const [collapsedState, setCollapsedState] = React.useState(() =>
    readCollapsed(collapsedKey, defaultCollapsed),
  )
  const collapsed = collapsible && collapsedState
  const setCollapsed = React.useCallback(
    (next: boolean | ((prev: boolean) => boolean)) => {
      setCollapsedState((prev) => {
        const value = typeof next === 'function' ? next(prev) : next
        try {
          localStorage.setItem(collapsedKey, value ? '1' : '0')
        } catch {
          /* ignore */
        }
        return value
      })
    },
    [collapsedKey],
  )

  // Overlay drawer open (overlay mode) / list requested (stack mode).
  const [listOpen, setListOpen] = React.useState(false)
  const openList = React.useCallback(() => setListOpen(true), [])
  const closeList = React.useCallback(() => setListOpen(false), [])

  // Selection change closes the drawer / returns phone to the detail.
  const prevSelected = React.useRef(selectedKey)
  React.useEffect(() => {
    if (prevSelected.current === selectedKey) return
    prevSelected.current = selectedKey
    setListOpen(false)
  }, [selectedKey])

  // Leaving overlay/stack resets the transient drawer state.
  React.useEffect(() => {
    if (mode === 'split') setListOpen(false)
  }, [mode])

  React.useEffect(() => {
    if (mode !== 'overlay' || !listOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setListOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mode, listOpen])

  const toggleList = React.useCallback(() => {
    if (mode === 'split') {
      if (collapsible) setCollapsed((c) => !c)
    } else if (mode === 'overlay') setListOpen((o) => !o)
    else setListOpen(true)
  }, [mode, collapsible, setCollapsed])

  const onBackRef = React.useRef(onBack)
  React.useEffect(() => {
    onBackRef.current = onBack
  }, [onBack])
  const back = React.useCallback(() => {
    onBackRef.current?.()
    setListOpen(true)
  }, [])

  const [toggleCount, setToggleCount] = React.useState(0)
  const registerToggle = React.useCallback(() => {
    setToggleCount((n) => n + 1)
    return () => setToggleCount((n) => n - 1)
  }, [])
  const hasCustomToggle = toggleCount > 0

  const hasSelection = selectedKey === undefined ? undefined : selectedKey !== null
  const stackDetail = stackShowsDetail(hasSelection, listOpen)
  const effectiveListOpen = mode === 'stack' ? !stackDetail : mode === 'overlay' ? listOpen : false

  const ctx = React.useMemo<MasterDetailContextValue>(
    () => ({
      inMasterDetail: true,
      mode,
      collapsed,
      setCollapsed,
      collapsible,
      isOverlay: mode !== 'split',
      listOpen: effectiveListOpen,
      openList,
      closeList,
      toggleList,
      back,
      listLabel,
      registerToggle,
    }),
    [mode, collapsed, setCollapsed, collapsible, effectiveListOpen, openList, closeList, toggleList, back, listLabel, registerToggle],
  )

  const onMasterClick = (e: React.MouseEvent) => {
    if (mode === 'split') return
    const target = e.target as HTMLElement | null
    if (!target?.closest) return
    if (target.closest('[data-md-keep-open]')) return
    if (!target.closest(SELECT_TARGET)) return
    // Let the page's own click handler update the selection first.
    window.setTimeout(() => setListOpen(false), 0)
  }

  const detailPaneClass = clsx(
    'min-h-0 min-w-0 flex-1 space-y-2 overflow-y-auto p-3 [scrollbar-gutter:stable]',
    detailClassName,
  )

  /* ── Narrow: overlay drawer or phone stack ─────────────────────────────── */
  if (mode !== 'split') {
    const showDetail = mode === 'overlay' || stackDetail
    const fallbackBar = !hasCustomToggle ? (
      <div className="flex shrink-0 items-center gap-1 border-b border-ink-200/80 bg-white px-2 py-1">
        <MasterDetailToggleButton ctx={ctx} />
      </div>
    ) : null
    return (
      <MasterDetailContext.Provider value={ctx}>
        <div
          className={clsx('relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden', className)}
          data-md-mode={mode}
        >
          <div className={clsx('flex min-h-0 min-w-0 flex-1 flex-col', !showDetail && 'hidden')}>
            {fallbackBar}
            <div className={detailPaneClass}>{detail}</div>
          </div>
          {mode === 'overlay' && listOpen ? (
            <button
              type="button"
              aria-label={`Close ${listLabel}`}
              className="absolute inset-0 z-30 cursor-default bg-ink-950/25"
              onClick={closeList}
            />
          ) : null}
          <div
            role={mode === 'overlay' ? 'dialog' : undefined}
            aria-label={capitalize(listLabel)}
            aria-hidden={!effectiveListOpen}
            className={clsx(
              'min-h-0 overflow-y-auto bg-white',
              mode === 'overlay'
                ? 'absolute inset-y-0 left-0 z-40 w-[min(22rem,88%)] border-r border-ink-200 shadow-xl'
                : 'flex-1',
              !effectiveListOpen && 'hidden',
              stacked ? 'px-3 py-2' : 'p-3',
              masterClassName,
            )}
            onClickCapture={onMasterClick}
          >
            {mode === 'overlay' ? (
              <div className="mb-1 flex items-center justify-between gap-2" data-md-keep-open>
                <span className="text-[12px] font-semibold text-ink-700">{capitalize(listLabel)}</span>
                <button
                  type="button"
                  className="btn-quiet !px-1.5 !py-1"
                  aria-label={`Hide ${listLabel}`}
                  title={`Hide ${listLabel}`}
                  onClick={closeList}
                >
                  <PanelLeftClose className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : null}
            {master}
          </div>
        </div>
      </MasterDetailContext.Provider>
    )
  }

  /* ── Split (≥1024) ─────────────────────────────────────────────────────── */
  const sizeDefaults =
    orientation === 'vertical'
      ? { defaultSize: defaultSize === 360 ? 220 : defaultSize, minSize: Math.min(minSize, 120), maxSize: 420 }
      : { defaultSize, minSize, maxSize }
  const horizontalCollapsible = collapsible && orientation === 'horizontal'

  if (horizontalCollapsible && collapsed) {
    return (
      <MasterDetailContext.Provider value={ctx}>
        <div className={clsx('flex h-full min-h-0', className)} data-md-mode="split-collapsed">
          {!hasCustomToggle ? (
            <div className="flex w-9 shrink-0 flex-col items-center border-r border-ink-200/80 bg-white/60 py-2">
              <button
                type="button"
                className="btn-quiet !px-1.5 !py-1.5"
                aria-label={`Show ${listLabel}`}
                title={`Show ${listLabel}`}
                onClick={() => setCollapsed(false)}
              >
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            </div>
          ) : null}
          <div className={clsx('h-full', detailPaneClass)}>{detail}</div>
        </div>
      </MasterDetailContext.Provider>
    )
  }

  return (
    <MasterDetailContext.Provider value={ctx}>
      <SplitPane
        className={clsx('h-full min-h-0', className)}
        orientation={orientation}
        storageKey={sizeKey}
        defaultSize={sizeDefaults.defaultSize}
        minSize={sizeDefaults.minSize}
        maxSize={sizeDefaults.maxSize}
        paneOverflow="hidden"
      >
        {[
          <div
            key="master"
            className={clsx(
              'relative h-full min-h-0 overflow-y-auto bg-white [scrollbar-gutter:stable]',
              stacked ? 'px-3 py-2' : 'p-3',
              horizontalCollapsible && !hasCustomToggle && 'pr-9',
              masterClassName,
            )}
          >
            {horizontalCollapsible && !hasCustomToggle ? (
              <button
                type="button"
                className="btn-quiet absolute right-1.5 top-1.5 z-[1] !px-1.5 !py-1"
                aria-label={`Hide ${listLabel}`}
                title={`Hide ${listLabel}`}
                onClick={() => setCollapsed(true)}
              >
                <PanelLeftClose className="h-3.5 w-3.5" />
              </button>
            ) : null}
            {master}
          </div>,
          <div key="detail" className={clsx('h-full', detailPaneClass)}>
            {detail}
          </div>,
        ]}
      </SplitPane>
    </MasterDetailContext.Provider>
  )
}

function MasterDetailToggleButton({
  ctx,
  onBack,
  className,
  label,
}: {
  ctx: MasterDetailContextValue
  onBack?: () => void
  className?: string
  label?: string
}) {
  const name = label ?? capitalize(ctx.listLabel)
  if (!ctx.inMasterDetail) return null
  if (ctx.mode === 'stack') {
    return (
      <button
        type="button"
        className={clsx('btn-quiet !px-1.5 !py-1 text-[12px]', className)}
        aria-label={`Back to ${ctx.listLabel}`}
        title={`Back to ${ctx.listLabel}`}
        onClick={() => {
          if (onBack) {
            onBack()
            ctx.openList()
          } else ctx.back()
        }}
      >
        <ChevronLeft className="h-3.5 w-3.5" />
        <span>{name}</span>
      </button>
    )
  }
  if (ctx.mode === 'overlay') {
    return (
      <button
        type="button"
        className={clsx('btn-quiet !px-1.5 !py-1 text-[12px]', className)}
        aria-expanded={ctx.listOpen}
        aria-label={ctx.listOpen ? `Hide ${ctx.listLabel}` : `Show ${ctx.listLabel}`}
        title={ctx.listOpen ? `Hide ${ctx.listLabel}` : `Show ${ctx.listLabel}`}
        onClick={ctx.toggleList}
      >
        <List className="h-3.5 w-3.5" />
        <span>{name}</span>
        <ChevronDown className="h-3 w-3 opacity-60" />
      </button>
    )
  }
  if (!ctx.collapsible) return null
  return (
    <button
      type="button"
      className={clsx('btn-quiet !px-1.5 !py-1', className)}
      aria-label={ctx.collapsed ? `Show ${ctx.listLabel}` : `Hide ${ctx.listLabel}`}
      title={ctx.collapsed ? `Show ${ctx.listLabel}` : `Hide ${ctx.listLabel}`}
      onClick={ctx.toggleList}
    >
      {ctx.collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
    </button>
  )
}

/**
 * Drop-in list toggle for a detail header: split → hide/show icon (when
 * collapsible), overlay → "Runs ▾" drawer button, stack → "‹ Runs" back button.
 * Mounting it hides MasterDetail's built-in fallback controls. Renders nothing
 * outside a MasterDetail.
 */
export function MasterDetailToggle({
  className,
  label,
  onBack,
}: {
  className?: string
  /** Button text in overlay/stack mode (default: capitalised listLabel). */
  label?: string
  /** Phone back handler; overrides MasterDetail's `onBack` for this button. */
  onBack?: () => void
}) {
  const ctx = useMasterDetail()
  const { registerToggle, inMasterDetail } = ctx
  React.useLayoutEffect(() => (inMasterDetail ? registerToggle() : undefined), [inMasterDetail, registerToggle])
  return <MasterDetailToggleButton ctx={ctx} onBack={onBack} className={className} label={label} />
}
