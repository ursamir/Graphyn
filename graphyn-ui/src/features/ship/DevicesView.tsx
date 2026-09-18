import React from 'react'
import { Cpu, Radio } from 'lucide-react'
import { EmptyState, PageHeader } from '../../components/ui'
import { paths } from '../../routes/paths'
import { navigatePath } from '../../routes/parsePath'

/**
 * Devices inventory — UI shell until device registry / OTA APIs exist (C1).
 * Standalone hit with a workspace redirects into Ship → Devices.
 */
export default function DevicesView({
  workspaceId,
  embedded,
}: {
  workspaceId?: string | null
  /** When true, omit outer page chrome (Ship tab hosts the header). */
  embedded?: boolean
}) {
  React.useEffect(() => {
    if (embedded) return
    const W = workspaceId?.trim()
    if (W) navigatePath(paths.shipDevices(W), true)
  }, [workspaceId, embedded])

  const body = (
    <EmptyState
      title="No device registry yet"
      description="Ship package download works today. Device inventory, flash, and OTA status need backend APIs (plan C1). This page is the product slot so routing and IA stay stable."
      action={
        <div className="inline-flex items-center gap-2 text-sm text-ink-500">
          <Radio className="h-4 w-4" />
          <Cpu className="h-4 w-4" /> needs-API
        </div>
      }
    />
  )

  if (embedded) {
    return <div className="space-y-3">{body}</div>
  }

  // Brief placeholder while redirecting into Ship → Devices when workspace is open.
  if (workspaceId?.trim()) {
    return (
      <div className="h-full min-h-0 overflow-y-auto p-6 space-y-4">
        <PageHeader
          title="Devices"
          description={`Opening Ship → Devices for workspace ${workspaceId}…`}
        />
        {body}
      </div>
    )
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6 space-y-4">
      <PageHeader
        title="Devices"
        description="Global device fleet. Register devices when the device API is available."
      />
      {body}
    </div>
  )
}
