/** Fleet sections addressable by URL: `/deploy/workers[/queue|/join]` (F18 carried / F19). */
export type FleetTab = 'workers' | 'queue' | 'join'

export function fleetTabFromPath(pathname: string): FleetTab {
  const parts = pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  if (parts[0] === 'deploy' && parts[1] === 'workers') {
    if (parts[2] === 'queue') return 'queue'
    if (parts[2] === 'join' || parts[2] === 'enrollment') return 'join'
  }
  return 'workers'
}

export function fleetTabPath(tab: FleetTab): string {
  return tab === 'workers' ? '/deploy/workers' : `/deploy/workers/${tab}`
}
