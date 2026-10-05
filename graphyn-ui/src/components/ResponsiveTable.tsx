/**
 * Horizontal-scroll container for tables inside cards / narrow panes, with a
 * sticky first column (`.responsive-table` in index.css). Pass `stickyFirst={false}`
 * for tables whose first column is not an identifier.
 */
import React from 'react'
import clsx from 'clsx'

export function ResponsiveTable({
  children,
  className,
  stickyFirst = true,
}: {
  children: React.ReactNode
  className?: string
  stickyFirst?: boolean
}) {
  return (
    <div className={clsx('responsive-table', !stickyFirst && 'responsive-table-plain', className)}>
      {children}
    </div>
  )
}
