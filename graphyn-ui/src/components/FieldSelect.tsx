/**
 * Accessible field select — custom menu so long option labels are not clipped
 * by sticky/overflow parents (native <select> looked broken in Ship/Runs).
 */
import React from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown } from 'lucide-react'
import clsx from 'clsx'

export type FieldSelectOption = {
  value: string
  label: string
  /** Secondary line under the label (mono paths, status, …). */
  description?: string
  disabled?: boolean
}

type FieldSelectProps = {
  value: string
  onChange: (value: string) => void
  options: FieldSelectOption[]
  placeholder?: string
  /** Shown as the empty option; selecting it calls onChange(''). */
  allowEmpty?: boolean
  emptyLabel?: string
  disabled?: boolean
  className?: string
  triggerClassName?: string
  mono?: boolean
  'aria-label'?: string
  id?: string
}

type MenuPos = { top: number; left: number; width: number; maxHeight: number }

export function FieldSelect({
  value,
  onChange,
  options,
  placeholder = 'Select…',
  allowEmpty = true,
  emptyLabel,
  disabled = false,
  className,
  triggerClassName,
  mono = false,
  'aria-label': ariaLabel,
  id,
}: FieldSelectProps) {
  const [open, setOpen] = React.useState(false)
  const [pos, setPos] = React.useState<MenuPos | null>(null)
  const [activeIdx, setActiveIdx] = React.useState(0)
  const triggerRef = React.useRef<HTMLButtonElement>(null)
  const listRef = React.useRef<HTMLUListElement>(null)

  const items = React.useMemo(() => {
    const rows: FieldSelectOption[] = []
    if (allowEmpty) {
      rows.push({ value: '', label: emptyLabel || placeholder })
    }
    rows.push(...options)
    return rows
  }, [allowEmpty, emptyLabel, placeholder, options])

  const selected = items.find((o) => o.value === value) ?? null
  const triggerLabel = selected?.label || placeholder

  const updatePos = React.useCallback(() => {
    const el = triggerRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const pad = 8
    const spaceBelow = window.innerHeight - r.bottom - pad
    const spaceAbove = r.top - pad
    const preferBelow = spaceBelow >= 160 || spaceBelow >= spaceAbove
    const maxHeight = Math.min(280, Math.max(120, preferBelow ? spaceBelow : spaceAbove))
    setPos({
      top: preferBelow ? r.bottom + 4 : Math.max(pad, r.top - 4 - maxHeight),
      left: Math.min(r.left, window.innerWidth - Math.min(r.width, 420) - pad),
      width: Math.max(r.width, Math.min(420, window.innerWidth - pad * 2)),
      maxHeight,
    })
  }, [])

  React.useEffect(() => {
    if (!open) return
    updatePos()
    const onScroll = () => updatePos()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (triggerRef.current?.contains(t) || listRef.current?.contains(t)) return
      setOpen(false)
    }
    window.addEventListener('resize', onScroll)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      window.removeEventListener('resize', onScroll)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open, updatePos])

  React.useEffect(() => {
    if (!open) return
    const idx = Math.max(
      0,
      items.findIndex((o) => o.value === value),
    )
    setActiveIdx(idx)
    // Defer focus so the portal list exists.
    requestAnimationFrame(() => listRef.current?.focus())
  }, [open, value, items])

  React.useEffect(() => {
    if (!open) return
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${activeIdx}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [activeIdx, open])

  const commit = (next: string) => {
    onChange(next)
    setOpen(false)
    triggerRef.current?.focus()
  }

  const onTriggerKeyDown = (e: React.KeyboardEvent) => {
    if (disabled) return
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setOpen(true)
    }
  }

  const onListKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx((i) => Math.min(items.length - 1, i + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx((i) => Math.max(0, i - 1))
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      const opt = items[activeIdx]
      if (opt && !opt.disabled) commit(opt.value)
    } else if (e.key === 'Home') {
      e.preventDefault()
      setActiveIdx(0)
    } else if (e.key === 'End') {
      e.preventDefault()
      setActiveIdx(items.length - 1)
    }
  }

  const menu =
    open && pos
      ? createPortal(
          <ul
            ref={listRef}
            role="listbox"
            tabIndex={-1}
            aria-label={ariaLabel || placeholder}
            className="fixed z-[80] overflow-auto rounded-xl border border-ink-200 bg-white py-1 shadow-lg outline-none ring-1 ring-ink-950/5"
            style={{
              top: pos.top,
              left: pos.left,
              width: pos.width,
              maxHeight: pos.maxHeight,
            }}
            onKeyDown={onListKeyDown}
          >
            {items.map((opt, idx) => {
              const active = idx === activeIdx
              const selected = opt.value === value
              return (
                <li
                  key={`${opt.value}::${idx}`}
                  role="option"
                  aria-selected={selected}
                  data-idx={idx}
                  aria-disabled={opt.disabled || undefined}
                  className={clsx(
                    'flex cursor-pointer items-start gap-2 px-3 py-2 text-left text-xs transition',
                    opt.disabled && 'cursor-not-allowed opacity-40',
                    active && !opt.disabled && 'bg-accent-50 text-accent-950',
                    !active && !opt.disabled && 'text-ink-800 hover:bg-ink-50',
                    selected && !active && 'bg-ink-50/80',
                  )}
                  onMouseEnter={() => setActiveIdx(idx)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    if (opt.disabled) return
                    commit(opt.value)
                  }}
                >
                  <span className="mt-0.5 w-3.5 shrink-0">
                    {selected ? <Check className="h-3.5 w-3.5 text-accent-600" /> : null}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span
                      className={clsx(
                        'block truncate font-medium',
                        mono && opt.value ? 'font-mono text-[11px]' : '',
                      )}
                    >
                      {opt.label}
                    </span>
                    {opt.description ? (
                      <span className="mt-0.5 block truncate font-mono text-[10px] text-ink-400">
                        {opt.description}
                      </span>
                    ) : null}
                  </span>
                </li>
              )
            })}
          </ul>,
          document.body,
        )
      : null

  return (
    <div className={clsx('relative', className)}>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel || placeholder}
        className={clsx(
          'field-control mt-0 inline-flex w-full items-center justify-between gap-2 text-left',
          mono && 'font-mono',
          disabled && 'cursor-not-allowed opacity-50',
          open && 'border-accent-400 ring-2 ring-accent-200/70',
          triggerClassName,
        )}
        onClick={() => {
          if (disabled) return
          setOpen((o) => !o)
        }}
        onKeyDown={onTriggerKeyDown}
      >
        <span
          className={clsx(
            'min-w-0 flex-1 truncate',
            !selected?.value && 'text-ink-400',
          )}
        >
          {triggerLabel}
        </span>
        <ChevronDown
          className={clsx('h-3.5 w-3.5 shrink-0 text-ink-400 transition', open && 'rotate-180')}
        />
      </button>
      {menu}
    </div>
  )
}
