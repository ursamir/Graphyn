/**
 * Standard IDE page: ViewShell chrome + scrollable workbench body.
 * Use for Library/Admin screens that are not MasterDetail.
 */
import React from 'react'
import clsx from 'clsx'
import { ViewShell } from './ViewShell'

type WorkbenchPageProps = {
  title: string
  description?: string
  actions?: React.ReactNode
  toolbar?: React.ReactNode
  children: React.ReactNode
  /** Extra class on the scroll body (default horizontal/vertical padding). */
  bodyClassName?: string
  className?: string
}

export function WorkbenchPage({
  title,
  description,
  actions,
  toolbar,
  children,
  bodyClassName,
  className,
}: WorkbenchPageProps) {
  return (
    <ViewShell
      title={title}
      description={description}
      actions={actions}
      toolbar={toolbar}
      className={className}
    >
      <div className={clsx('workbench-scroll', bodyClassName)}>{children}</div>
    </ViewShell>
  )
}
