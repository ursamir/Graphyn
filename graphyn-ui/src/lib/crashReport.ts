/** Plain-text crash report for the per-view error boundary's Report button. */
export function buildCrashReport(viewLabel: string, error: Error, stack?: string | null): string {
  const lines = [
    `Graphyn console — "${viewLabel}" page failed`,
    `URL: ${typeof window !== 'undefined' ? window.location.href : ''}`,
    `Time: ${new Date().toISOString()}`,
    `Error: ${error.name}: ${error.message}`,
  ]
  const s = (stack ?? error.stack ?? '').split('\n').slice(0, 12).join('\n')
  if (s) lines.push('', s)
  return lines.join('\n')
}
