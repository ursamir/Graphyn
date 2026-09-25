import React from 'react'
import { AlertTriangle, Cpu, Radio } from 'lucide-react'
import { EmptyState, PageHeader } from '../../components/ui'
import { paths } from '../../routes/paths'
import { navigatePath } from '../../routes/parsePath'

/**
 * Devices inventory — honesty stub until device registry / flash / OTA APIs exist.
 * FR-SHIP-006 / EDGE-007 / SHIP-006: no fake devices, flash, or OTA UI.
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

  const honesty = (
    <div
      className="rounded-xl border border-amber-300 bg-amber-50 px-3 py-2.5 text-sm text-amber-950"
      role="status"
      data-testid="devices-needs-api"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" aria-hidden />
        <div className="space-y-1">
          <div className="font-semibold">
            needs-API — device registry / flash / OTA not shipped
          </div>
          <p className="text-xs text-amber-900/90">
            Ship <strong>package</strong> create/download works today. Device inventory, flash, and
            OTA status require a device registry API (FR-SHIP-006, EDGE-007). This tab is an IA slot
            only — there is no fake fleet, flash button, or OTA progress.
          </p>
        </div>
      </div>
    </div>
  )

  const body = (
    <div className="space-y-3">
      {honesty}
      <EmptyState
        title="No device registry yet"
        description="When the device API lands, inventory and OTA status will appear here. Until then this page stays an honest empty slot."
        action={
          <div className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold uppercase tracking-wide text-amber-900">
            <Radio className="h-3.5 w-3.5" />
            <Cpu className="h-3.5 w-3.5" /> needs-API
          </div>
        }
      />
    </div>
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
        description="Global device fleet — needs-API until device registry ships (no fake OTA)."
      />
      {body}
    </div>
  )
}
