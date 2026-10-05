/** True when project/version appears in a loaded Outputs catalogue. */
export function outputSelectionKnown(
  outputs: Array<{ project: string; versions: string[] }>,
  project: string,
  version: string,
): boolean {
  if (!project.trim() || !version.trim()) return false
  const row = outputs.find((o) => o.project === project)
  return Boolean(row && row.versions.includes(version))
}
